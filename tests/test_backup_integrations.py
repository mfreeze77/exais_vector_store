from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE_DIR = ROOT / "scripts" / "release"
sys.path.insert(0, str(RELEASE_DIR))

from backup_common import (  # noqa: E402
    REQUIRED_ARTIFACT_KINDS,
    BackupArtifact,
    sha256_file,
    validate_backup_manifest,
    write_backup_manifest,
)


def issue_codes(report):
    return {issue.code for issue in report.issues}


def write_checksums(bundle_dir: Path) -> Path:
    checksum_path = bundle_dir / "CHECKSUMS.sha256"
    files = sorted(
        candidate
        for candidate in bundle_dir.rglob("*")
        if candidate.is_file() and candidate.name not in {"CHECKSUMS.sha256", "manifest.json"}
    )
    checksum_path.write_text(
        "".join(f"{sha256_file(candidate)}  ./{candidate.relative_to(bundle_dir).as_posix()}\n" for candidate in files),
        encoding="utf-8",
    )
    return checksum_path


def complete_bundle(bundle_dir: Path) -> list[BackupArtifact]:
    files = {
        "postgres/svs.dump": "postgres dump\n",
        "qdrant/snapshot-create-response.json": '{"result":"ok"}\n',
        "opensearch/indices.json": "[]\n",
        "object-store/local-files.txt": "./objects/doc-1.txt\n",
        "config/config-metadata.json": '{"source_manifest":"instance.yaml"}\n',
        "audit/audit-export.json": "[]\n",
    }
    for relative_path, content in files.items():
        target = bundle_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    write_checksums(bundle_dir)
    return [
        BackupArtifact("postgres_metadata", "postgres/svs.dump", True, "pg_dump"),
        BackupArtifact("qdrant_vectors", "qdrant/snapshot-create-response.json", True, "qdrant_snapshot_api"),
        BackupArtifact("opensearch_sparse", "opensearch/indices.json", True, "opensearch_index_listing"),
        BackupArtifact("object_store", "object-store/local-files.txt", True, "local_object_store_listing"),
        BackupArtifact("config_metadata", "config/config-metadata.json", True, "instance_manifest"),
        BackupArtifact("audit_export", "audit/audit-export.json", True, "audit_export"),
        BackupArtifact("checksum_metadata", "CHECKSUMS.sha256", True, "sha256sum"),
    ]


def test_backup_manifest_round_trips_required_artifacts(tmp_path):
    bundle_dir = tmp_path / "unit-bundle"
    bundle_dir.mkdir()
    manifest_path = write_backup_manifest(bundle_dir, complete_bundle(bundle_dir))

    report = validate_backup_manifest(manifest_path)

    assert report.ok
    assert report.artifact_kinds == REQUIRED_ARTIFACT_KINDS
    assert report.bundle_id == "unit-bundle"
    assert report.product_version


def test_backup_manifest_detects_duplicate_missing_and_corrupt_artifacts(tmp_path):
    bundle_dir = tmp_path / "unit-bundle"
    bundle_dir.mkdir()
    manifest_path = write_backup_manifest(bundle_dir, complete_bundle(bundle_dir))
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["artifacts"].append(dict(data["artifacts"][0]))
    data["artifacts"] = [artifact for artifact in data["artifacts"] if artifact["kind"] != "audit_export"]
    manifest_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (bundle_dir / "postgres" / "svs.dump").write_text("changed\n", encoding="utf-8")

    report = validate_backup_manifest(manifest_path)

    assert {"DUPLICATE_KIND", "MISSING_REQUIRED_KIND", "SHA256_MISMATCH"} <= issue_codes(report)


def test_backup_manifest_rejects_unsafe_relative_paths_without_crashing(tmp_path):
    bundle_dir = tmp_path / "unit-bundle"
    bundle_dir.mkdir()
    manifest_path = write_backup_manifest(bundle_dir, complete_bundle(bundle_dir))
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["artifacts"][0]["relative_path"] = "../outside.dump"
    manifest_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    report = validate_backup_manifest(manifest_path)

    assert "BAD_RELATIVE_PATH" in issue_codes(report)


def test_backup_manifest_external_markers_are_optional_for_rm006(tmp_path):
    bundle_dir = tmp_path / "unit-bundle"
    bundle_dir.mkdir()
    manifest_path = write_backup_manifest(bundle_dir, complete_bundle(bundle_dir))

    local_report = validate_backup_manifest(manifest_path, require_external=False)
    external_report = validate_backup_manifest(manifest_path, require_external=True)

    assert local_report.ok
    assert "MISSING_EXTERNAL_MARKER" in issue_codes(external_report)


def test_restore_preflight_validates_manifest_without_database_url(tmp_path):
    bundle_dir = tmp_path / "unit-bundle"
    bundle_dir.mkdir()
    write_backup_manifest(bundle_dir, complete_bundle(bundle_dir))
    bundle_path = tmp_path / "unit-bundle.tar.gz"
    with tarfile.open(bundle_path, "w:gz") as archive:
        archive.add(bundle_dir, arcname=bundle_dir.name)

    env = os.environ.copy()
    env.pop("DATABASE_URL_SYNC", None)
    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "restore-instance.sh"), "--preflight-only", str(bundle_path), str(tmp_path / "restore")],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )

    assert result.returncode == 0, result.stdout
    assert "Backup manifest verified:" in result.stdout
    assert "postgres_metadata: postgres/svs.dump" in result.stdout
    assert "No restore commands were run." in result.stdout


def test_backup_instance_script_writes_preflight_manifest_with_markers(tmp_path):
    manifest = tmp_path / "instances" / "unit" / "instance.yaml"
    manifest.parent.mkdir(parents=True)
    manifest.write_text("metadata:\n  name: unit-cell\n", encoding="utf-8")
    env = os.environ.copy()
    for key in ("DATABASE_URL_SYNC", "QDRANT_URL", "OPENSEARCH_URL", "SVS_AUDIT_EXPORT_PATH"):
        env.pop(key, None)
    env["SVS_LOCAL_OBJECT_STORE_PATH"] = str(tmp_path / "missing-object-store")

    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "backup-instance.sh"), str(manifest), str(tmp_path / "backups")],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )

    assert result.returncode == 0, result.stdout
    bundle_path = Path(result.stdout.strip().splitlines()[-1])
    assert bundle_path.is_file()
    bundle_dirs = [path for path in (tmp_path / "backups").iterdir() if path.is_dir()]
    assert len(bundle_dirs) == 1
    report = validate_backup_manifest(bundle_dirs[0] / "manifest.json")

    assert report.ok
    assert report.artifact_kinds == REQUIRED_ARTIFACT_KINDS
    assert {artifact.kind: artifact.source for artifact in report.artifacts}["qdrant_vectors"] == "metadata_marker"
