from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]
VERSION_FILE = ROOT / "VERSION"
COMPOSE_FILE = ROOT / "infra" / "docker" / "compose.cell.yml"
DEFAULT_REGISTRY_PREFIX = "localhost:5000/expertaiservices"
DEFAULT_CELL = "local"

APP_IMAGES = {
    "api": ("apps/api/Dockerfile", "exai-vector-store-api"),
    "worker": ("apps/worker/Dockerfile", "exai-vector-store-worker"),
    "model-gateway": ("apps/model_gateway/Dockerfile", "exai-vector-store-model-gateway"),
    "admin-ui": ("apps/admin_ui/Dockerfile", "exai-vector-store-admin-ui"),
    "instance-agent": ("apps/instance_agent/Dockerfile", "exai-vector-store-instance-agent"),
}
APP_IMAGE_ENV_VARS = {
    service: f"SVS_IMAGE_{service.upper().replace('-', '_')}"
    for service in APP_IMAGES
}
PINNED_IMAGE_ENV_FILENAME = ".env.images"
PINNED_IMAGE_REFERENCE_RE = re.compile(
    r"^(?P<repository>[^@\s]+)@sha256:(?P<digest>[0-9a-f]{64})$"
)


def version() -> str:
    return VERSION_FILE.read_text(encoding="utf-8").strip()


def release_dir(cell: str = DEFAULT_CELL) -> Path:
    return ROOT / ".release" / "cells" / cell


def env_file(cell: str = DEFAULT_CELL) -> Path:
    return release_dir(cell) / ".env.cell"


def pinned_image_env_file(cell: str = DEFAULT_CELL) -> Path:
    return release_dir(cell) / PINNED_IMAGE_ENV_FILENAME


def release_manifest_path(cell: str = DEFAULT_CELL) -> Path:
    return release_dir(cell) / "release-manifest.json"


def project_name(cell: str = DEFAULT_CELL) -> str:
    safe = "".join(c if c.isalnum() else "-" for c in cell.lower()).strip("-") or DEFAULT_CELL
    return f"exais-vector-store-{safe}"


def compose_network_name(cell: str = DEFAULT_CELL) -> str:
    return f"{project_name(cell)}_default"


def normalize_registry_prefix(registry_prefix: str | None = None) -> str:
    return (registry_prefix or os.getenv("SVS_REGISTRY_PREFIX") or DEFAULT_REGISTRY_PREFIX).rstrip("/")


def image_tag(service: str, registry_prefix: str | None = None, product_version: str | None = None) -> str:
    if service not in APP_IMAGES:
        raise KeyError(f"unknown app service: {service}")
    return f"{normalize_registry_prefix(registry_prefix)}/{APP_IMAGES[service][1]}:{product_version or version()}"


def all_image_tags(registry_prefix: str | None = None, product_version: str | None = None) -> list[str]:
    return [image_tag(service, registry_prefix, product_version) for service in APP_IMAGES]


def compose_cmd() -> list[str]:
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    if shutil.which("docker"):
        probe = subprocess.run(["docker", "compose", "version"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if probe.returncode == 0:
            return ["docker", "compose"]
    raise RuntimeError("Docker Compose was not found. Install docker-compose or the Docker compose plugin.")


def compose_base(cell: str = DEFAULT_CELL) -> list[str]:
    validate_pinned_image_env(cell)
    return compose_cmd() + [
        "--env-file",
        str(env_file(cell)),
        "--env-file",
        str(pinned_image_env_file(cell)),
        "-f",
        str(COMPOSE_FILE),
        "-p",
        project_name(cell),
    ]


def printable_command(args: list[str]) -> str:
    return " ".join(quote_arg(str(a)) for a in args)


def quote_arg(value: str) -> str:
    if not value:
        return "''"
    if any(ch.isspace() for ch in value) or any(ch in value for ch in ['"', "'", "$", "&", "(", ")"]):
        return '"' + value.replace('"', '\\"') + '"'
    return value


def run(args: list[str], *, check: bool = True, cwd: Path = ROOT, env: dict[str, str] | None = None, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    print(f"$ {printable_command(args)}", flush=True)
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    proc = subprocess.run(
        args,
        cwd=cwd,
        env=merged_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if proc.stdout:
        print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n", flush=True)
    print(f"[exit {proc.returncode}]", flush=True)
    if check and proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, args, proc.stdout)
    return proc


def inspect_local_repo_digests(reference: str) -> tuple[str, ...] | None:
    result = run(
        ["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", reference],
        check=False,
    )
    if result.returncode != 0:
        return None
    output = (result.stdout or "").strip().splitlines()
    if not output:
        return ()
    try:
        values = json.loads(output[-1])
    except json.JSONDecodeError:
        return ()
    if not isinstance(values, list):
        return ()
    return tuple(str(value) for value in values)


def ensure_app_images_available(
    image_references: dict[str, str],
    *,
    services: tuple[str, ...] | None = None,
) -> None:
    selected_services = _validate_service_selection(services)
    if set(image_references) != set(selected_services):
        raise RuntimeError("Digest-pinned image availability requires the exact selected APP_IMAGES mapping")
    for service in selected_services:
        reference = image_references[service]
        repo_digests = inspect_local_repo_digests(reference)
        if repo_digests is None:
            run(["docker", "pull", reference])
            repo_digests = inspect_local_repo_digests(reference)
        if repo_digests is None or reference not in repo_digests:
            raise RuntimeError(
                f"Digest-pinned image verification failed for {service}: local RepoDigests do not contain {reference}"
            )


def wait_for_services(cell: str, services: list[str], timeout_seconds: int = 240) -> None:
    deadline = time.time() + timeout_seconds
    names = [f"{project_name(cell)}-{service}-1" for service in services]
    while time.time() < deadline:
        unhealthy: list[str] = []
        for name in names:
            proc = run(
                ["docker", "inspect", "--format", "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}", name],
                check=False,
            )
            status = (proc.stdout or "").strip()
            if status not in {"healthy", "running"}:
                unhealthy.append(name)
        if not unhealthy:
            return
        print(f"Waiting for healthy services: {', '.join(unhealthy)}", flush=True)
        time.sleep(5)
    raise TimeoutError(f"Timed out waiting for services: {', '.join(names)}")


def read_env(cell: str = DEFAULT_CELL) -> dict[str, str]:
    return _read_env_file(env_file(cell))


def write_pinned_image_env(
    cell: str,
    image_references: dict[str, str],
    *,
    registry_prefix: str | None = None,
) -> Path:
    prefix = normalize_registry_prefix(registry_prefix or read_env(cell).get("SVS_REGISTRY_PREFIX"))
    return write_pinned_image_env_file(
        pinned_image_env_file(cell),
        image_references,
        registry_prefix=prefix,
        check_process_env=True,
    )


def write_pinned_image_env_file(
    path: Path,
    image_references: dict[str, str],
    *,
    registry_prefix: str,
    services: tuple[str, ...] | None = None,
    check_process_env: bool = False,
) -> Path:
    selected_services = _validate_service_selection(services)
    _validate_pinned_image_references(
        image_references,
        services=selected_services,
        registry_prefix=normalize_registry_prefix(registry_prefix),
        check_process_env=check_process_env,
    )
    lines = [
        "# Generated immutable app image references. Do not commit this file.",
        "# Values are non-secret and derive from a verified release manifest.",
    ]
    for service in selected_services:
        env_name = APP_IMAGE_ENV_VARS[service]
        lines.append(f"{env_name}={image_references[service]}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return path


def restore_pinned_image_env_file(path: Path, previous: bytes | None) -> None:
    if previous is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".rollback.tmp")
    try:
        temporary.write_bytes(previous)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_pinned_image_env(cell: str = DEFAULT_CELL) -> dict[str, str]:
    path = pinned_image_env_file(cell)
    if not path.exists():
        raise FileNotFoundError(
            f"Missing pinned image env file: {path}. Run cell-up.py with a verified release manifest first."
        )
    values = _read_env_file(path)
    expected_keys = set(APP_IMAGE_ENV_VARS.values())
    actual_keys = set(values)
    if actual_keys != expected_keys:
        missing = sorted(expected_keys - actual_keys)
        extra = sorted(actual_keys - expected_keys)
        details: list[str] = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unexpected " + ", ".join(extra))
        raise RuntimeError(f"Pinned image env must contain exactly the APP_IMAGES mapping ({'; '.join(details)})")
    image_references = {service: values[env_name] for service, env_name in APP_IMAGE_ENV_VARS.items()}
    registry_prefix = normalize_registry_prefix(read_env(cell).get("SVS_REGISTRY_PREFIX"))
    _validate_pinned_image_references(
        image_references,
        services=tuple(APP_IMAGES),
        registry_prefix=registry_prefix,
        check_process_env=True,
    )
    return image_references


def _validate_pinned_image_references(
    image_references: dict[str, str],
    *,
    services: tuple[str, ...],
    registry_prefix: str,
    check_process_env: bool,
) -> None:
    expected_services = set(services)
    actual_services = set(image_references)
    if actual_services != expected_services:
        raise RuntimeError("Pinned image references must match the selected APP_IMAGES services")
    issues: list[str] = []
    for service in services:
        _dockerfile, image_name = APP_IMAGES[service]
        reference = image_references[service]
        match = PINNED_IMAGE_REFERENCE_RE.fullmatch(reference)
        if not match:
            issues.append(f"{service} must use repository@sha256 digest syntax")
            continue
        expected_repository = f"{registry_prefix}/{image_name}"
        if match.group("repository") != expected_repository:
            issues.append(f"{service} repository does not match {expected_repository}")
        env_name = APP_IMAGE_ENV_VARS[service]
        if check_process_env and env_name in os.environ and os.environ[env_name] != reference:
            issues.append(f"process environment override {env_name} does not match the pinned digest")
    if issues:
        raise RuntimeError("Pinned image validation failed: " + "; ".join(issues))


def _validate_service_selection(services: tuple[str, ...] | None) -> tuple[str, ...]:
    selected = services or tuple(APP_IMAGES)
    if not selected or len(set(selected)) != len(selected):
        raise RuntimeError("Pinned image services must be a non-empty unique APP_IMAGES selection")
    unknown = sorted(set(selected) - set(APP_IMAGES))
    if unknown:
        raise RuntimeError("Unknown APP_IMAGES services: " + ", ".join(unknown))
    return selected


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def api_base(cell: str = DEFAULT_CELL) -> str:
    values = read_env(cell)
    return values.get("SVS_PUBLIC_API_BASE") or f"http://localhost:{values.get('SVS_API_PORT', '18080')}"


def ensure_env(cell: str = DEFAULT_CELL) -> None:
    if not env_file(cell).exists():
        raise FileNotFoundError(f"Missing generated env file: {env_file(cell)}. Run generate-cell-env.py first.")


def main_guard() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
