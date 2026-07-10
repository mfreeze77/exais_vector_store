from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

ROOT = Path(__file__).resolve().parents[1]
RELEASE_DIR = ROOT / "scripts" / "release"
INSTANCE_AGENT_DIR = ROOT / "apps" / "instance_agent"
sys.path.insert(0, str(RELEASE_DIR))
sys.path.insert(0, str(INSTANCE_AGENT_DIR))

from provenance_common import ImageDigest, write_release_manifest  # noqa: E402
from release_common import APP_IMAGE_ENV_VARS, APP_IMAGES, all_image_tags, version  # noqa: E402
from svs_instance_agent import main as instance_agent  # noqa: E402


def release_images(
    registry_prefix: str = "registry.internal/exais",
    *,
    digest_source: str = "repository_digest",
) -> list[ImageDigest]:
    images = []
    for index, (service, image) in enumerate(zip(APP_IMAGES, all_image_tags(registry_prefix, version())), start=1):
        digest = f"sha256:{index:064x}"
        provenance = {"source": "unit-test", "digest_source": digest_source}
        if digest_source == "repository_digest":
            provenance["repository_digest"] = f"{image.rsplit(':', 1)[0]}@{digest}"
        images.append(
            ImageDigest(
                service=service,
                image=image,
                tag=version(),
                digest=digest,
                provenance=provenance,
            )
        )
    return images


def write_instance_manifest(path: Path) -> Path:
    path.write_text(
        "\n".join(
            [
                "apiVersion: svs/v1",
                "kind: Instance",
                "metadata:",
                "  instanceId: inst_unit",
                "  slug: unit",
                "product:",
                f"  version: {version()}",
                "runtime:",
                "  composeProjectName: svs_unit",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def request_paths(tmp_path: Path, *, digest_source: str = "repository_digest") -> tuple[Path, Path]:
    instance_path = write_instance_manifest(tmp_path / "instance.yaml")
    instance_path.with_name(".env.instance").write_text("SVS_DEV_MODE=true\n", encoding="utf-8")
    release_path = write_release_manifest(
        release_images(digest_source=digest_source),
        tmp_path / "release-manifest.json",
    )
    return instance_path, release_path


def configure_agent_paths(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(instance_agent, "WORKDIR", tmp_path)
    monkeypatch.setattr(instance_agent, "INSTANCE_PIN_ROOT", tmp_path / ".release" / "instances")
    monkeypatch.setattr(instance_agent, "INSTANCE_COMPOSE_FILE", ROOT / "infra" / "docker" / "compose.instance.yml")


def deploy_request(instance_path: Path, release_path: Path, *, dry_run: bool = False):
    return instance_agent.DeployRequest(
        manifest_path=str(instance_path),
        release_manifest_path=str(release_path),
        env_file_path=str(instance_path.with_name(".env.instance")),
        version=version(),
        dry_run=dry_run,
    )


def test_instance_compose_requires_digest_pin_variables_without_tag_fallback():
    body = (ROOT / "infra" / "docker" / "compose.instance.yml").read_text(encoding="utf-8")

    for service in instance_agent.INSTANCE_SERVICES:
        env_name = APP_IMAGE_ENV_VARS[service]
        assert f"image: ${{{env_name}:?{env_name} is required}}" in body
    assert "SVS_VERSION" not in body
    assert "SVS_REGISTRY_PREFIX" not in body


def test_instance_deploy_dry_run_derives_exact_digest_refs(tmp_path, monkeypatch):
    configure_agent_paths(monkeypatch, tmp_path)
    instance_path, release_path = request_paths(tmp_path)
    preflight_calls = []
    compose_calls = []
    monkeypatch.setattr(
        instance_agent,
        "ensure_app_images_available",
        lambda references, services: preflight_calls.append((references, services)),
    )
    monkeypatch.setattr(
        instance_agent,
        "run",
        lambda command, cwd=None, env=None: compose_calls.append((command, env))
        or {"command": command, "returncode": 0, "stdout": "rendered", "stderr": ""},
    )

    result = instance_agent.deploy(deploy_request(instance_path, release_path, dry_run=True))

    assert set(result["image_references"]) == set(instance_agent.INSTANCE_SERVICES)
    assert all("@sha256:" in reference for reference in result["image_references"].values())
    assert result["command"][-4:] == ["up", "-d", "--pull", "never"]
    assert "pull" not in result["command"][:-2]
    assert preflight_calls and preflight_calls[0][1] == instance_agent.INSTANCE_SERVICES
    assert compose_calls[0][0][-1] == "config"
    assert compose_calls[0][1]["SVS_CELL_ENV_FILE"].endswith(".env.instance")
    assert result["compose_validation"]["returncode"] == 0
    assert not instance_agent.active_pin_path("svs_unit").exists()


def test_instance_deploy_rejects_local_image_id_manifest(tmp_path, monkeypatch):
    configure_agent_paths(monkeypatch, tmp_path)
    instance_path, release_path = request_paths(tmp_path, digest_source="local_image_id")

    with pytest.raises(HTTPException) as exc_info:
        instance_agent.deploy(deploy_request(instance_path, release_path, dry_run=True))

    assert exc_info.value.status_code == 400
    assert "local image IDs cannot pin cell startup" in str(exc_info.value.detail)


def test_instance_dry_run_compose_failure_has_no_active_pin(tmp_path, monkeypatch):
    configure_agent_paths(monkeypatch, tmp_path)
    instance_path, release_path = request_paths(tmp_path)
    monkeypatch.setattr(instance_agent, "ensure_app_images_available", lambda references, services: None)
    monkeypatch.setattr(
        instance_agent,
        "run",
        lambda command, cwd=None, env=None: {
            "command": command,
            "returncode": 1,
            "stdout": "",
            "stderr": "invalid compose plan",
        },
    )

    with pytest.raises(HTTPException) as exc_info:
        instance_agent.deploy(deploy_request(instance_path, release_path, dry_run=True))

    assert exc_info.value.detail["step"] == "compose_config"
    assert not instance_agent.active_pin_path("svs_unit").exists()


def test_instance_preflight_failure_preserves_active_pins(tmp_path, monkeypatch):
    configure_agent_paths(monkeypatch, tmp_path)
    instance_path, release_path = request_paths(tmp_path)
    active_path = instance_agent.active_pin_path("svs_unit")
    active_path.parent.mkdir(parents=True)
    previous = b"SVS_IMAGE_API=previous-approved-digest\n"
    active_path.write_bytes(previous)
    monkeypatch.setattr(
        instance_agent,
        "ensure_app_images_available",
        lambda references, services: (_ for _ in ()).throw(RuntimeError("simulated pull failure")),
    )
    monkeypatch.setattr(instance_agent, "run", lambda *args, **kwargs: pytest.fail("compose must not run"))

    with pytest.raises(HTTPException) as exc_info:
        instance_agent.deploy(deploy_request(instance_path, release_path))

    assert exc_info.value.detail["step"] == "image_preflight"
    assert active_path.read_bytes() == previous


def test_instance_compose_env_overrides_host_image_vars_with_verified_refs(tmp_path, monkeypatch):
    configure_agent_paths(monkeypatch, tmp_path)
    instance_path, release_path = request_paths(tmp_path)
    monkeypatch.setenv("SVS_IMAGE_API", "registry.invalid/api:mutable")
    monkeypatch.setattr(instance_agent, "ensure_app_images_available", lambda references, services: None)
    calls = []

    def fake_run(command, cwd=None, env=None):
        calls.append((command, env))
        return {"command": command, "returncode": 0, "stdout": "", "stderr": ""}

    monkeypatch.setattr(instance_agent, "run", fake_run)

    result = instance_agent.deploy(deploy_request(instance_path, release_path))

    assert result["up"]["returncode"] == 0
    for _command, env in calls:
        assert env["SVS_IMAGE_API"] == result["image_references"]["api"]
        assert ":mutable" not in env["SVS_IMAGE_API"]


def test_instance_up_failure_restores_previous_active_pins(tmp_path, monkeypatch):
    configure_agent_paths(monkeypatch, tmp_path)
    instance_path, release_path = request_paths(tmp_path)
    active_path = instance_agent.active_pin_path("svs_unit")
    active_path.parent.mkdir(parents=True)
    previous = b"previous-active-pin-bytes\n"
    active_path.write_bytes(previous)
    monkeypatch.setattr(instance_agent, "ensure_app_images_available", lambda references, services: None)
    monkeypatch.setattr(
        instance_agent,
        "run",
        lambda command, cwd=None, env=None: {
            "command": command,
            "returncode": 1,
            "stdout": "",
            "stderr": "simulated compose failure",
        },
    )

    with pytest.raises(HTTPException) as exc_info:
        instance_agent.deploy(deploy_request(instance_path, release_path))

    assert exc_info.value.detail["step"] == "up"
    assert active_path.read_bytes() == previous


def test_instance_up_exception_restores_previous_active_pins(tmp_path, monkeypatch):
    configure_agent_paths(monkeypatch, tmp_path)
    instance_path, release_path = request_paths(tmp_path)
    active_path = instance_agent.active_pin_path("svs_unit")
    active_path.parent.mkdir(parents=True)
    previous = b"previous-active-pin-bytes\n"
    active_path.write_bytes(previous)
    monkeypatch.setattr(instance_agent, "ensure_app_images_available", lambda references, services: None)
    monkeypatch.setattr(
        instance_agent,
        "run",
        lambda command, cwd=None, env=None: (_ for _ in ()).throw(FileNotFoundError("docker missing")),
    )

    with pytest.raises(FileNotFoundError, match="docker missing"):
        instance_agent.deploy(deploy_request(instance_path, release_path))

    assert active_path.read_bytes() == previous


def test_instance_rollback_requires_and_reuses_verified_release_manifest(tmp_path, monkeypatch):
    configure_agent_paths(monkeypatch, tmp_path)
    instance_path, release_path = request_paths(tmp_path)
    monkeypatch.setattr(instance_agent, "ensure_app_images_available", lambda references, services: None)
    monkeypatch.setattr(
        instance_agent,
        "run",
        lambda command, cwd=None, env=None: {
            "command": command,
            "returncode": 0,
            "stdout": "rendered",
            "stderr": "",
        },
    )

    result = instance_agent.rollback(
        instance_agent.RollbackRequest(
            manifest_path=str(instance_path),
            release_manifest_path=str(release_path),
            env_file_path=str(instance_path.with_name(".env.instance")),
            version=version(),
            dry_run=True,
        )
    )

    assert result["status"] == "planned"
    assert result["deployment"]["release_manifest_path"] == str(release_path)
    assert set(result["deployment"]["image_references"]) == set(instance_agent.INSTANCE_SERVICES)


def test_release_cell_agent_packages_docker_and_mounts_supported_inputs():
    dockerfile = (ROOT / "apps" / "instance_agent" / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "infra" / "docker" / "compose.cell.yml").read_text(encoding="utf-8")

    assert "docker-cli" in dockerfile
    assert "docker-compose" in dockerfile
    assert ":/workspace/instances:ro" in compose
    assert ":/workspace/.release/cells:ro" in compose
    assert ":/workspace/.release/instances" in compose
    assert "SVS_AGENT_WORKDIR: /workspace" in compose
    assert "SVS_INSTANCE_PIN_ROOT: /workspace/.release/instances" in compose


def test_instance_callers_forward_release_manifest_contract():
    svsctl = (ROOT / "scripts" / "svsctl.py").read_text(encoding="utf-8")
    deploy_script = (ROOT / "scripts" / "deploy-instance.sh").read_text(encoding="utf-8")
    fleet_script = (ROOT / "scripts" / "fleet-upgrade.sh").read_text(encoding="utf-8")
    dockerfile = (ROOT / "apps" / "instance_agent" / "Dockerfile").read_text(encoding="utf-8")

    assert "release_manifest_path" in svsctl
    assert "--release-manifest" in svsctl
    assert "--instance-env" in svsctl
    assert "release_manifest_path" in deploy_script
    assert "env_file_path" in deploy_script
    assert "RELEASE_MANIFEST" in fleet_script
    assert "provenance_common.py" in dockerfile
    assert "compose.instance.yml" in dockerfile
