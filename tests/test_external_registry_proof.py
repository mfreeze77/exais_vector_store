from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


RELEASE_DIR = Path(__file__).resolve().parents[1] / "scripts" / "release"
sys.path.insert(0, str(RELEASE_DIR))

from provenance_common import ImageDigest, write_release_manifest  # noqa: E402
from release_common import APP_IMAGES, all_image_tags  # noqa: E402


def load_release_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, RELEASE_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def digest(index: int) -> str:
    return f"sha256:{index:064x}"


def manifest_images(registry_prefix: str, version: str) -> list[ImageDigest]:
    images: list[ImageDigest] = []
    for index, (service, image) in enumerate(zip(APP_IMAGES, all_image_tags(registry_prefix, version)), start=1):
        images.append(
            ImageDigest(
                service=service,
                image=image,
                tag=version,
                digest=digest(index),
                image_id=digest(index + 20),
                size=1000 + index,
                labels={
                    "org.opencontainers.image.version": version,
                    "com.exais.service": service,
                },
                provenance={"source": "unit-test", "digest_source": "unit-test"},
            )
        )
    return images


def test_external_registry_proof_writes_clean_pull_by_digest_evidence(tmp_path):
    proof_script = load_release_script("external_registry_proof_test", "external-registry-proof.py")
    registry_prefix = "registry.internal/exais"
    version = "0.9.8-production-candidate"
    manifest_path = write_release_manifest(manifest_images(registry_prefix, version), tmp_path / "release-manifest.json")
    proof_output = tmp_path / "external-registry-proof.json"
    seen_commands: list[list[str]] = []

    def fake_runner(args):
        seen_commands.append([str(arg) for arg in args])
        return SimpleNamespace(returncode=0, stdout="ok\n")

    result = proof_script.run_external_registry_proof(
        cell="customer-001",
        registry_prefix=registry_prefix,
        product_version=version,
        manifest_path=manifest_path,
        proof_output=proof_output,
        runner=fake_runner,
    )

    payload = json.loads(result.read_text(encoding="utf-8"))
    assert result == proof_output
    assert payload["verdict"] == "pass"
    assert "does not prove VPS readiness" in payload["claim_boundary"]
    assert payload["registry_prefix"] == registry_prefix
    assert payload["product_version"] == version
    assert len(payload["pull_by_digest"]) == len(APP_IMAGES)
    assert all(entry["digest_reference"].startswith(registry_prefix + "/") for entry in payload["pull_by_digest"])
    assert all("@sha256:" in entry["digest_reference"] for entry in payload["pull_by_digest"])

    script_commands = [Path(command[1]).name for command in seen_commands if len(command) > 1 and command[1].endswith(".py")]
    assert script_commands == ["build-images.py", "publish-images.py", "remove-local-app-images.py"]
    assert len([command for command in seen_commands if command[:2] == ["docker", "pull"]]) == len(APP_IMAGES)
    assert len([command for command in seen_commands if command[:3] == ["docker", "image", "inspect"]]) == len(APP_IMAGES)
    assert not any("login" in part for command in seen_commands for part in command)


def test_external_registry_proof_rejects_local_registry_prefix():
    proof_script = load_release_script("external_registry_proof_local_test", "external-registry-proof.py")

    with pytest.raises(ValueError, match="non-local"):
        proof_script.validate_external_registry_prefix("localhost:5000/expertaiservices")


def test_external_registry_proof_rejects_embedded_credentials():
    proof_script = load_release_script("external_registry_proof_credentials_test", "external-registry-proof.py")

    with pytest.raises(ValueError, match="credentials"):
        proof_script.validate_external_registry_prefix("https://user:pass@registry.example.com/exais")


def test_external_registry_proof_dry_run_does_not_write_json(tmp_path, capsys):
    proof_script = load_release_script("external_registry_proof_dry_run_test", "external-registry-proof.py")

    proof_script.print_dry_run("customer-001", "registry.internal/exais", "0.9.8-production-candidate", tmp_path / "missing.json")

    output = capsys.readouterr().out
    assert "no Docker commands executed" in output
    assert "no proof JSON written" in output
    assert "Pull-by-digest commands will be derived" in output
    assert not (tmp_path / "external-registry-proof.json").exists()
