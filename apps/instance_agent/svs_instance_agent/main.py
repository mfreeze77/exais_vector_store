from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from svs_common.config import get_settings
from svs_common.instance_manifest import load_instance_manifest, render_compose_project_name

ROOT = Path(__file__).resolve().parents[3]
RELEASE_HELPER_DIR = ROOT / "scripts" / "release"
if str(RELEASE_HELPER_DIR) not in sys.path:
    sys.path.insert(0, str(RELEASE_HELPER_DIR))

from provenance_common import format_manifest_report, release_image_references, verify_release_manifest  # noqa: E402
from release_common import (  # noqa: E402
    APP_IMAGE_ENV_VARS,
    ensure_app_images_available,
    restore_pinned_image_env_file,
    write_pinned_image_env_file,
)

settings = get_settings()
settings.validate_runtime_guards()
WORKDIR = Path(os.getenv("SVS_AGENT_WORKDIR", "/workspace"))
if not WORKDIR.exists():
    WORKDIR = Path.cwd()
INSTANCE_COMPOSE_FILE = Path(
    os.getenv("SVS_INSTANCE_COMPOSE_FILE", str(ROOT / "infra" / "docker" / "compose.instance.yml"))
)
INSTANCE_PIN_ROOT = Path(os.getenv("SVS_INSTANCE_PIN_ROOT", str(WORKDIR / ".release" / "instances")))
INSTANCE_SERVICES = ("api", "worker", "model-gateway")

app = FastAPI(title="exai_vector_store Instance Agent", version=settings.svs_product_version)


class DeployRequest(BaseModel):
    manifest_path: str
    release_manifest_path: str
    env_file_path: str | None = None
    version: str | None = None
    dry_run: bool = False


class BackupRequest(BaseModel):
    manifest_path: str
    dest_root: str = "backups"


class RollbackRequest(BaseModel):
    manifest_path: str
    release_manifest_path: str
    env_file_path: str | None = None
    version: str
    dry_run: bool = False


def run(cmd: list[str], cwd: str | None = None, env: dict[str, str] | None = None) -> dict:
    proc = subprocess.run(cmd, cwd=cwd or str(WORKDIR), capture_output=True, text=True, env=env)
    return {"command": cmd, "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}


def require_success(result: dict) -> dict:
    if result["returncode"] != 0:
        raise HTTPException(status_code=500, detail=result)
    return result


def resolve_existing_path(raw_path: str, label: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        path = WORKDIR / path
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{label} not found")
    return path


def verified_instance_image_references(
    release_manifest_path: Path,
    target_version: str,
) -> tuple[dict[str, str], str]:
    report = verify_release_manifest(release_manifest_path)
    if not report.ok:
        raise HTTPException(status_code=400, detail=format_manifest_report(report))
    if report.product_version != target_version:
        raise HTTPException(
            status_code=400,
            detail=(
                f"release manifest product_version {report.product_version!r} "
                f"does not match requested version {target_version!r}"
            ),
        )
    try:
        complete_references = release_image_references(report)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    references = {service: complete_references[service] for service in INSTANCE_SERVICES}
    if not report.registry_prefix:
        raise HTTPException(status_code=400, detail="release manifest registry_prefix is required")
    return references, report.registry_prefix


def active_pin_path(project: str) -> Path:
    return INSTANCE_PIN_ROOT / project / ".env.images"


def compose_command(project: str, pins_path: Path, *args: str) -> list[str]:
    return [
        "docker",
        "compose",
        "--env-file",
        str(pins_path),
        "-f",
        str(INSTANCE_COMPOSE_FILE),
        "-p",
        project,
        *args,
    ]


def compose_environment(references: dict[str, str], env_file_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    for env_name in APP_IMAGE_ENV_VARS.values():
        env.pop(env_name, None)
    for service in INSTANCE_SERVICES:
        env[APP_IMAGE_ENV_VARS[service]] = references[service]
    env["SVS_CELL_ENV_FILE"] = str(env_file_path)
    return env


def resolve_instance_env_path(instance_path: Path, requested_path: str | None) -> Path:
    raw_path = requested_path or str(instance_path.with_name(".env.instance"))
    return resolve_existing_path(raw_path, "Instance env file")


def preflight_instance_images(references: dict[str, str]) -> None:
    try:
        ensure_app_images_available(references, services=INSTANCE_SERVICES)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        raise HTTPException(status_code=500, detail={"step": "image_preflight", "error": str(exc)}) from exc


def validate_compose_plan(
    project: str,
    references: dict[str, str],
    registry_prefix: str,
    compose_env: dict[str, str],
) -> dict:
    with TemporaryDirectory(prefix="svs-instance-agent-") as temporary_dir:
        candidate_pins = Path(temporary_dir) / ".env.images"
        write_pinned_image_env_file(
            candidate_pins,
            references,
            registry_prefix=registry_prefix,
            services=INSTANCE_SERVICES,
        )
        command = compose_command(project, candidate_pins, "config")
        try:
            result = run(command, env=compose_env)
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail={"step": "compose_config", "error": str(exc)},
            ) from exc
    if result["returncode"] != 0:
        raise HTTPException(
            status_code=500,
            detail={"step": "compose_config", "returncode": result["returncode"]},
        )
    return {"command": command, "returncode": 0}


@app.get("/healthz")
def healthz():
    return {"ok": True, "service": "svs-instance-agent", "version": settings.svs_product_version}


@app.post("/agent/v1/instances/deploy")
def deploy(req: DeployRequest):
    instance_path = resolve_existing_path(req.manifest_path, "Instance manifest")
    release_path = resolve_existing_path(req.release_manifest_path, "Release manifest")
    instance_env_path = resolve_instance_env_path(instance_path, req.env_file_path)
    manifest = load_instance_manifest(instance_path)
    project = render_compose_project_name(manifest)
    target_version = req.version or str(manifest.product.get("version") or "")
    if not target_version:
        raise HTTPException(status_code=400, detail="A fixed deployment version is required")
    references, registry_prefix = verified_instance_image_references(release_path, target_version)
    pins_path = active_pin_path(project)
    up_command = compose_command(project, pins_path, "up", "-d", "--pull", "never")
    compose_env = compose_environment(references, instance_env_path)
    preflight_instance_images(references)
    if req.dry_run:
        compose_validation = validate_compose_plan(project, references, registry_prefix, compose_env)
        return {
            "dry_run": True,
            "compose_project_name": project,
            "manifest": manifest.model_dump(),
            "release_manifest_path": str(release_path),
            "env_file_path": str(instance_env_path),
            "version": target_version,
            "image_references": references,
            "command": up_command,
            "compose_validation": compose_validation,
        }

    previous_pins = pins_path.read_bytes() if pins_path.exists() else None
    write_pinned_image_env_file(
        pins_path,
        references,
        registry_prefix=registry_prefix,
        services=INSTANCE_SERVICES,
    )
    try:
        up = run(up_command, env=compose_env)
    except BaseException:
        restore_pinned_image_env_file(pins_path, previous_pins)
        raise
    if up["returncode"] != 0:
        restore_pinned_image_env_file(pins_path, previous_pins)
        raise HTTPException(status_code=500, detail={"step": "up", **up})
    ps = run(compose_command(project, pins_path, "ps"), env=compose_env)
    return {
        "project": project,
        "version": target_version,
        "release_manifest_path": str(release_path),
        "env_file_path": str(instance_env_path),
        "image_references": references,
        "up": up,
        "ps": ps,
    }


@app.post("/agent/v1/instances/backup")
def backup(req: BackupRequest):
    path = resolve_existing_path(req.manifest_path, "Manifest")
    result = require_success(run(["bash", "scripts/backup-instance.sh", str(path), req.dest_root]))
    return {
        "status": "completed",
        "bundle": result["stdout"].strip().splitlines()[-1] if result["stdout"].strip() else None,
        "result": result,
    }


@app.post("/agent/v1/instances/rollback")
def rollback(req: RollbackRequest):
    resolve_existing_path(req.manifest_path, "Manifest")
    deployment = deploy(
        DeployRequest(
            manifest_path=req.manifest_path,
            release_manifest_path=req.release_manifest_path,
            env_file_path=req.env_file_path,
            version=req.version,
            dry_run=req.dry_run,
        )
    )
    return {"status": "rolled_back" if not req.dry_run else "planned", "deployment": deployment}
