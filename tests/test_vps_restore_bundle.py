from __future__ import annotations

import importlib.util
import json
import sys
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
RELEASE_DIR = ROOT / "scripts" / "release"
sys.path.insert(0, str(RELEASE_DIR))

from backup_common import validate_backup_manifest, write_backup_manifest  # noqa: E402


def load_script(filename: str = "export-cell-restore-bundle.py"):
    module_name = filename.replace("-", "_").replace(".", "_") + "_test"
    spec = importlib.util.spec_from_file_location(module_name, RELEASE_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_qdrant_collection_and_snapshot_response_parsing():
    script = load_script()

    collections = script.qdrant_collections(
        {
            "result": {
                "collections": [
                    {"name": "ks_civics_court_decisions"},
                    {"name": "ks_civics_topeka_municipal_code"},
                ]
            }
        }
    )

    assert collections == ["ks_civics_court_decisions", "ks_civics_topeka_municipal_code"]
    assert script.qdrant_snapshot_name({"result": {"name": "store-2026.snapshot"}}) == "store-2026.snapshot"
    with pytest.raises(RuntimeError, match="result.name"):
        script.qdrant_snapshot_name({"result": True})


def test_qdrant_curl_command_propagates_api_key_without_embedding_secret(monkeypatch, tmp_path):
    script = load_script()
    monkeypatch.setenv("QDRANT_REAL_KEY", "secret-value-that-must-not-be-in-command")

    args = script.qdrant_curl_args(
        network="unit_default",
        method="GET",
        path="/collections",
        curl_image="curlimages/curl:8.10.1",
        qdrant_api_key_env="QDRANT_REAL_KEY",
        output_relative_path="qdrant/out.snapshot",
        bundle_dir=tmp_path,
    )

    rendered = " ".join(args)
    assert "secret-value-that-must-not-be-in-command" not in rendered
    assert "SVS_QDRANT_API_KEY" in args
    assert script.qdrant_subprocess_env("QDRANT_REAL_KEY")["SVS_QDRANT_API_KEY"] == "secret-value-that-must-not-be-in-command"


def test_restorable_bundle_manifest_accepts_qdrant_snapshots_and_volume_index(tmp_path):
    script = load_script()
    bundle = tmp_path / "ks-state-civics-vps-restore-20260828T000000Z"
    (bundle / "postgres").mkdir(parents=True)
    (bundle / "qdrant" / "ks_civics_cases").mkdir(parents=True)
    (bundle / "object-store" / "volumes").mkdir(parents=True)
    (bundle / "opensearch").mkdir(parents=True)
    (bundle / "config").mkdir(parents=True)
    (bundle / "audit").mkdir(parents=True)

    (bundle / "postgres" / "svs.dump").write_bytes(b"pg-dump")
    snapshot = bundle / "qdrant" / "ks_civics_cases" / "snapshot.snapshot"
    snapshot.write_bytes(b"qdrant-snapshot")
    volume = bundle / "object-store" / "volumes" / "object-store.tar.gz"
    volume.write_bytes(b"object-volume")
    script.write_json(
        bundle / "qdrant" / "snapshots.json",
        {
            "schema_version": 1,
            "collections": [
                {
                    "collection": "ks_civics_cases",
                    "snapshot_name": "snapshot.snapshot",
                    "relative_path": "qdrant/ks_civics_cases/snapshot.snapshot",
                    "sha256": script.sha256_file(snapshot),
                    "size_bytes": snapshot.stat().st_size,
                }
            ],
        },
    )
    script.write_json(
        bundle / "object-store" / "volumes.json",
        {
            "schema_version": 1,
            "volumes": [
                {
                    "compose_volume": "object-store",
                    "source_volume": "exais-vector-store-ks-state-civics_object-store",
                    "relative_path": "object-store/volumes/object-store.tar.gz",
                    "sha256": script.sha256_file(volume),
                    "size_bytes": volume.stat().st_size,
                }
            ],
        },
    )
    script.write_marker(
        bundle / "opensearch" / "sparse-unavailable.json",
        kind="opensearch_sparse",
        status="not_configured",
        message="not used",
    )
    script.write_json(bundle / "config" / "config-metadata.json", {"capture_status": "captured"})
    script.write_marker(
        bundle / "audit" / "audit-unavailable.json",
        kind="audit_export",
        status="not_configured",
        message="not used",
    )
    script.write_checksums(bundle)
    manifest_path = write_backup_manifest(bundle, script.backup_artifacts())

    report = validate_backup_manifest(manifest_path)

    assert report.ok
    assert {artifact.kind: artifact.relative_path for artifact in report.artifacts}["qdrant_vectors"] == "qdrant/snapshots.json"
    assert {artifact.kind: artifact.relative_path for artifact in report.artifacts}["object_store"] == "object-store/volumes.json"


def test_export_quiesces_and_restarts_write_services(monkeypatch, tmp_path):
    script = load_script()
    calls: list[tuple[str, ...]] = []

    def fake_qdrant_export(**kwargs):
        script.write_json(kwargs["bundle_dir"] / "qdrant" / "snapshots.json", {"collections": []})
        return []

    def fake_volume_export(**kwargs):
        script.write_json(kwargs["bundle_dir"] / "object-store" / "volumes.json", {"volumes": []})
        return []

    monkeypatch.setattr(script, "stop_write_services", lambda project: calls.append(("stop", project)) or ["api-1", "worker-1"])
    monkeypatch.setattr(script, "restart_containers", lambda containers: calls.append(("restart", ",".join(containers))))
    monkeypatch.setattr(script, "pg_dump_from_container", lambda project, destination, timeout: destination.write_bytes(b"pg"))
    monkeypatch.setattr(script, "export_qdrant_snapshots", fake_qdrant_export)
    monkeypatch.setattr(script, "export_object_volumes", fake_volume_export)
    monkeypatch.setattr(script, "copy_optional_config", lambda cell, bundle_dir: script.write_json(bundle_dir / "config" / "config-metadata.json", {"cell": cell}) or [])
    monkeypatch.setattr(script, "create_bundle_archive", lambda bundle_dir: (bundle_dir.with_suffix(".tar.gz"), Path(str(bundle_dir) + ".tar.gz.sha256")))

    result = script.export_cell_restore_bundle(
        cell="ks-state-civics",
        output_root=tmp_path,
        collections=None,
        quiesce_writes=True,
        curl_image="curl",
        alpine_image="alpine",
        qdrant_api_key_env="SVS_QDRANT_API_KEY",
        timeout=30,
        allow_missing_volumes=True,
    )

    assert result.name.endswith(".tar.gz")
    assert calls[0] == ("stop", "exais-vector-store-ks-state-civics")
    assert calls[-1] == ("restart", "api-1,worker-1")


def test_dry_run_does_not_call_docker(capsys):
    script = load_script()

    script.print_dry_run(
        SimpleNamespace(
            cell="ks-state-civics",
            output_root=None,
            collection=["ks_civics_cases"],
            quiesce_writes=True,
        )
    )

    output = capsys.readouterr().out
    assert "Dry run only" in output
    assert "Secret env files are excluded" in output
    assert "ks_civics_cases" in output


def test_restore_preflight_rejects_corrupt_indexed_snapshot(tmp_path):
    export_script = load_script()
    restore_script = load_script("restore-cell-restore-bundle.py")
    bundle = tmp_path / "bundle"
    (bundle / "postgres").mkdir(parents=True)
    (bundle / "qdrant" / "ks_civics_cases").mkdir(parents=True)
    (bundle / "object-store" / "volumes").mkdir(parents=True)
    (bundle / "opensearch").mkdir(parents=True)
    (bundle / "config").mkdir(parents=True)
    (bundle / "audit").mkdir(parents=True)

    (bundle / "postgres" / "svs.dump").write_bytes(b"pg")
    snapshot = bundle / "qdrant" / "ks_civics_cases" / "snapshot.snapshot"
    snapshot.write_bytes(b"snapshot")
    volume = bundle / "object-store" / "volumes" / "object-store.tar.gz"
    volume.write_bytes(b"volume")
    export_script.write_json(
        bundle / "qdrant" / "snapshots.json",
        {
            "collections": [
                {
                    "collection": "ks_civics_cases",
                    "snapshot_name": "snapshot.snapshot",
                    "relative_path": "qdrant/ks_civics_cases/snapshot.snapshot",
                    "sha256": "0" * 64,
                    "size_bytes": snapshot.stat().st_size,
                }
            ]
        },
    )
    export_script.write_json(
        bundle / "object-store" / "volumes.json",
        {
            "volumes": [
                {
                    "compose_volume": "object-store",
                    "source_volume": "exais-vector-store-ks-state-civics_object-store",
                    "relative_path": "object-store/volumes/object-store.tar.gz",
                    "sha256": export_script.sha256_file(volume),
                    "size_bytes": volume.stat().st_size,
                }
            ]
        },
    )
    export_script.write_marker(bundle / "opensearch" / "sparse-unavailable.json", kind="opensearch_sparse", status="not_configured", message="not used")
    export_script.write_json(bundle / "config" / "config-metadata.json", {"capture_status": "captured"})
    export_script.write_marker(bundle / "audit" / "audit-unavailable.json", kind="audit_export", status="not_configured", message="not used")
    export_script.write_checksums(bundle)
    write_backup_manifest(bundle, export_script.backup_artifacts())

    issues = restore_script.validate_bundle(bundle)

    assert any("Qdrant snapshot" in issue and "checksum mismatch" in issue for issue in issues)


def test_restore_preflight_rejects_archive_links(tmp_path):
    restore_script = load_script("restore-cell-restore-bundle.py")
    archive_path = tmp_path / "unsafe.tar.gz"
    target = tarfile.TarInfo("bundle/link")
    target.type = tarfile.SYMTYPE
    target.linkname = "../outside"
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.addfile(target)

    with pytest.raises(RuntimeError, match="not allowed"):
        restore_script.safe_extract(archive_path, tmp_path / "restore")
