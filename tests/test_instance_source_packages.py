from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release" / "instance_source_packages.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("instance_source_packages", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["instance_source_packages"] = module
    spec.loader.exec_module(module)
    return module


def test_ks_civics_source_package_validates_in_production():
    module = _load_module()

    packages, issues = module.validate_instance_source_packages(
        "ks-state-civics",
        root=ROOT,
        production=True,
    )

    assert len(packages) == 1
    assert issues == []
    package = packages[0]
    assert package.vector_store_slug == "kansas-court-decisions"
    assert module.get_path(package.source, "ingestion.mode") == "api"
    assert module.get_path(package.source, "vectorStore.id") == "vs_a0d3ac76893e4f6f83bf2992"


def test_validator_fails_vector_store_without_source_package(tmp_path):
    module = _load_module()
    store_dir = tmp_path / "instances" / "unit" / "vector-stores" / "empty-store"
    store_dir.mkdir(parents=True)
    (store_dir / "store.yaml").write_text("apiVersion: svs/v1\nkind: InstanceVectorStore\n", encoding="utf-8")

    _packages, issues = module.validate_instance_source_packages("unit", root=tmp_path, production=True)

    assert [issue.code for issue in issues] == ["SOURCE_PACKAGE_MISSING"]


def test_production_path_policy_rejects_local_only_source(tmp_path):
    module = _load_module()
    package = _write_minimal_package(tmp_path)
    source_path = package / "sources" / "unit-source" / "source.yaml"
    data = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    data["source"]["storage"] = {
        "localProofPath": r"C:\only\local\manifest.csv",
        "localProofOnly": True,
    }
    source_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    _packages, issues = module.validate_instance_source_packages("unit", root=tmp_path, production=True)

    assert "LOCAL_PATH_ONLY_SOURCE" in {issue.code for issue in issues}
    assert "REQUIRED_FIELD_MISSING" in {issue.code for issue in issues}


def test_production_path_policy_allows_marked_local_proof_with_portable_uri(tmp_path):
    module = _load_module()
    _write_minimal_package(tmp_path)

    _packages, issues = module.validate_instance_source_packages("unit", root=tmp_path, production=True)

    assert issues == []


def test_manifest_diff_counts_added_changed_unchanged_and_removed(tmp_path):
    module = _load_module()
    previous = tmp_path / "previous.csv"
    current = tmp_path / "current.csv"
    previous.write_text(
        "document_id,docket_number,filename,sha256\n"
        "1,A,one.pdf,aaa\n"
        "2,B,two.pdf,bbb\n"
        "3,C,three.pdf,ccc\n",
        encoding="utf-8",
    )
    current.write_text(
        "document_id,docket_number,filename,sha256\n"
        "1,A,one.pdf,aaa\n"
        "2,B,two.pdf,changed\n"
        "4,D,four.pdf,ddd\n",
        encoding="utf-8",
    )

    prev = module.load_manifest_records(
        previous,
        manifest_format="csv",
        identity_fields=["document_id", "docket_number", "filename"],
        checksum_field="sha256",
    )
    curr = module.load_manifest_records(
        current,
        manifest_format="csv",
        identity_fields=["document_id", "docket_number", "filename"],
        checksum_field="sha256",
    )

    diff = module.diff_manifest_records(prev, curr)

    assert diff["added"] == 1
    assert diff["changed"] == 1
    assert diff["unchanged"] == 1
    assert diff["removed"] == 1


def test_dry_run_update_plan_is_api_only_and_does_not_mutate(tmp_path):
    module = _load_module()
    _write_minimal_package(tmp_path)
    packages, issues = module.validate_instance_source_packages("unit", root=tmp_path, production=True)
    assert issues == []

    plan = module.build_update_plan(packages[0])

    assert plan["api_only_update_path"] is True
    assert plan["direct_storage_writes"] is False
    assert plan["manifest_status"] == "matches_lock"
    assert plan["diff"] == {
        "added": 0,
        "changed": 0,
        "unchanged": 2,
        "removed": 0,
        "examples": {"added": [], "changed": [], "removed": []},
    }
    assert "secret" not in json.dumps(plan).lower()


def _write_minimal_package(root: Path) -> Path:
    store_dir = root / "instances" / "unit" / "vector-stores" / "unit-store"
    source_dir = store_dir / "sources" / "unit-source"
    source_dir.mkdir(parents=True)
    manifest = source_dir / "manifest.csv"
    manifest.write_text(
        "document_id,docket_number,filename,sha256\n"
        "1,A,one.pdf,aaa\n"
        "2,B,two.pdf,bbb\n",
        encoding="utf-8",
    )
    digest = _sha256(manifest)
    (store_dir / "store.yaml").write_text(
        yaml.safe_dump({
            "apiVersion": "svs/v1",
            "kind": "InstanceVectorStore",
            "metadata": {"instanceSlug": "unit", "vectorStoreSlug": "unit-store"},
        }, sort_keys=False),
        encoding="utf-8",
    )
    source = {
        "apiVersion": "svs/v1",
        "kind": "VectorStoreSourcePackage",
        "metadata": {
            "instanceSlug": "unit",
            "vectorStoreSlug": "unit-store",
            "sourceSlug": "unit-source",
            "productionReady": True,
        },
        "vectorStore": {
            "id": "vs_unit",
            "name": "Unit Store",
            "tenantId": "ten_unit",
            "businessInstanceId": "biz_unit",
            "knowledgeBaseId": "kb_unit",
        },
        "source": {
            "type": "unit",
            "connector": {"kind": "external_repo", "entrypoint": "collector/unit.py"},
            "storage": {
                "rawCorpusUri": "object-store://unit/raw/",
                "manifestUri": "object-store://unit/manifest.csv",
                "localProofPath": str(manifest),
                "localProofOnly": True,
            },
            "manifest": {
                "format": "csv",
                "stableIdentityFields": ["document_id", "docket_number", "filename"],
                "checksumField": "sha256",
                "savedPathField": "filename",
                "lockFile": "source.lock.json",
                "rowCount": 2,
                "sha256": digest,
                "byteCount": manifest.stat().st_size,
            },
        },
        "ingestion": {
            "mode": "api",
            "runner": "scripts/release/unit-ingest.py",
            "command": ["python", "scripts/release/unit-ingest.py", "--api-base", "${EXAIS_API_BASE}"],
            "idempotency": "source_identity_sha256",
        },
        "updatePolicy": {
            "diffMode": "stable_identity_and_checksum",
            "removedRecords": "soft_delete_or_expire_after_operator_approval",
            "dryRunRequired": True,
        },
        "graph": {
            "enabled": True,
            "extractCommand": ["python", "graph-extract.py"],
            "loadCommand": ["python", "graph-load.py"],
            "evalCommand": ["python", "graph-eval.py"],
            "expectedProofArtifacts": ["graph-proof.json"],
        },
        "eval": {
            "command": ["python", "recall-eval.py"],
            "expectedProofArtifacts": ["recall-proof.json"],
        },
    }
    (source_dir / "source.yaml").write_text(yaml.safe_dump(source, sort_keys=False), encoding="utf-8")
    (source_dir / "source.lock.json").write_text(
        json.dumps({
            "sourceManifest": {
                "sha256": digest,
                "rowCount": 2,
                "byteCount": manifest.stat().st_size,
            }
        }, indent=2) + "\n",
        encoding="utf-8",
    )
    return store_dir


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()
