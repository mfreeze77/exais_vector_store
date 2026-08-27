from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_script(path: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class _FakeLifecycleClient:
    def __init__(self):
        self.calls: list[tuple[str, str, str, object]] = []
        self.created_key_index = 0
        self.vector_store_index = 0

    def post_json(self, path, token, payload=None):
        self.calls.append(("POST", path, token, payload))
        if path.startswith("/api/v1/admin/api-keys?"):
            self.created_key_index += 1
            if self.created_key_index == 1:
                return {
                    "id": "key_ingest",
                    "api_key": "svs_live_ingest_secret",
                    "label": "proof-ingest",
                    "scopes": ["retrieval:read", "vector_stores:read", "vector_stores:write", "documents:write"],
                    "max_security_level": 5,
                }
            return {
                "id": "key_search",
                "api_key": "svs_live_search_secret",
                "label": "proof-search",
                "scopes": ["retrieval:read", "vector_stores:read"],
                "max_security_level": 5,
            }
        if path == "/v1/vector_stores":
            self.vector_store_index += 1
            vector_store_id = "vs_ks_law" if self.vector_store_index == 1 else "vs_ks_courts"
            return {"id": vector_store_id, "name": payload["name"], "object": "vector_store"}
        if path.endswith("/files"):
            return {"id": "vsf_attach", "object": "vector_store.file", "status": "completed"}
        if path.endswith("/file_batches"):
            return {"id": "vsfb_batch", "object": "vector_store.file_batch", "status": "completed"}
        if path.endswith("/search"):
            vector_store_id = path.split("/")[3]
            return {
                "object": "vector_store.search_results.page",
                "data": [{
                    "file_id": "file_lifecycle",
                    "filename": "instance-caller-lifecycle-proof.txt",
                    "content": [{
                        "type": "text",
                        "text": "Kansas caller lifecycle proof unique precedent [source]",
                        "annotations": [{
                            "type": "file_citation",
                            "index": 50,
                            "file_id": "file_lifecycle",
                            "filename": "instance-caller-lifecycle-proof.txt",
                        }],
                    }],
                    "citation": {
                        "file_id": "file_lifecycle",
                        "filename": "instance-caller-lifecycle-proof.txt",
                        "chunk_id": f"chk_{vector_store_id}",
                    },
                }],
                "citations": [{"file_id": "file_lifecycle", "vector_store_id": vector_store_id}],
            }
        if path == "/v1/responses":
            return {
                "id": "resp_lifecycle",
                "object": "response",
                "output": [{
                    "type": "message",
                    "content": [{
                        "type": "output_text",
                        "text": "Found cited support [source]",
                        "annotations": [{
                            "type": "file_citation",
                            "index": 20,
                            "file_id": "file_lifecycle",
                            "filename": "instance-caller-lifecycle-proof.txt",
                        }],
                    }],
                }],
                "citations": [{
                    "file_id": "file_lifecycle",
                    "vector_store_ids": ["vs_ks_law", "vs_ks_courts"],
                }],
            }
        raise AssertionError(f"unexpected POST {path}")

    def post_multipart(self, path, token, *, fields, files):
        self.calls.append(("MULTIPART", path, token, {"fields": fields, "files": list(files)}))
        assert path == "/v1/files"
        assert fields == {"purpose": "assistants"}
        assert "file" in files
        return {
            "id": "file_lifecycle",
            "object": "file",
            "filename": "instance-caller-lifecycle-proof.txt",
        }

    def delete_json(self, path, token):
        self.calls.append(("DELETE", path, token, None))
        return {"id": path.rsplit("/", 1)[-1], "deleted": True}


class _FakeBootstrapConn:
    def __init__(self):
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.committed = False

    def execute(self, sql, params=()):
        self.calls.append((str(sql), tuple(params)))

    def commit(self):
        self.committed = True


def test_instance_caller_lifecycle_proof_uses_instance_keys_without_secret_leakage():
    script = _load_script("scripts/release/instance-caller-lifecycle-proof.py", "instance_lifecycle_proof")
    client = _FakeLifecycleClient()

    proof = script.run_lifecycle(
        script.LifecycleConfig(
            api_base="https://api.example.test",
            admin_key="svs_live_admin_secret",
            label_prefix="proof",
        ),
        client=client,
    )

    serialized = json.dumps(proof, sort_keys=True)
    assert "svs_live_admin_secret" not in serialized
    assert "svs_live_ingest_secret" not in serialized
    assert "svs_live_search_secret" not in serialized
    assert proof["instance_scoped_api_key_model"] is True
    assert proof["per_key_vector_store_grants"] is False
    assert [store["id"] for store in proof["vector_stores"]] == ["vs_ks_law", "vs_ks_courts"]
    assert proof["responses_file_search"]["searched_vector_store_ids"] == ["vs_ks_law", "vs_ks_courts"]
    assert proof["responses_file_search"]["has_citations"] is True
    assert proof["temporary_keys_revoked"] == ["key_ingest", "key_search"]

    search_calls = [call for call in client.calls if call[0] == "POST" and str(call[1]).endswith("/search")]
    assert search_calls
    assert all(call[2] == "svs_live_search_secret" for call in search_calls)
    assert ("DELETE", "/api/v1/admin/api-keys/key_ingest", "svs_live_admin_secret", None) in client.calls
    assert ("DELETE", "/api/v1/admin/api-keys/key_search", "svs_live_admin_secret", None) in client.calls


def test_bootstrap_admin_key_writes_secret_outside_repo_and_never_in_sql(tmp_path, monkeypatch):
    script = _load_script("scripts/release/bootstrap-instance-admin-key.py", "bootstrap_instance_admin_key")
    secret_output = tmp_path / "bootstrap-admin.json"
    conn = _FakeBootstrapConn()
    monkeypatch.setattr(script, "api_key_hash", lambda raw, pepper: f"hashed:{pepper}:{raw[-6:]}")
    config = script.BootstrapConfig(
        database_url="postgresql://owner:secret@db/svs",
        api_key_pepper="unit-test-pepper",
        tenant_id="ten_customer",
        tenant_name="Customer",
        tenant_slug="customer",
        business_instance_id="biz_customer",
        business_name="Customer",
        business_slug="customer",
        user_id="usr_customer_admin",
        user_email="operator@example.com",
        user_display_name="Customer Admin",
        group_id="grp_customer_admins",
        group_name="Admins",
        group_slug="admins",
        knowledge_base_id="kb_customer",
        knowledge_base_name="Customer KB",
        knowledge_base_slug="customer",
        label="bootstrap-admin",
        scopes=script.DEFAULT_ADMIN_SCOPES,
        max_security_level=5,
        secret_output=secret_output,
    )

    metadata, raw_key = script.bootstrap_first_admin_key(
        conn,
        config,
        raw_key="svs_live_bootstrap_secret",
        key_id="key_bootstrap",
    )
    script.write_secret_output(secret_output, metadata, raw_key)

    assert conn.committed is True
    assert metadata["id"] == "key_bootstrap"
    assert metadata["redacted_value"] == "svs_live_...secret"
    assert "svs_live_bootstrap_secret" not in json.dumps(metadata, sort_keys=True)
    for _sql, params in conn.calls:
        assert "svs_live_bootstrap_secret" not in json.dumps(params, default=str)
    saved = json.loads(secret_output.read_text(encoding="utf-8"))
    assert saved["api_key"] == "svs_live_bootstrap_secret"
    assert saved["metadata"]["id"] == "key_bootstrap"


def test_bootstrap_secret_output_rejects_repo_paths():
    script = _load_script("scripts/release/bootstrap-instance-admin-key.py", "bootstrap_instance_admin_key_paths")

    with pytest.raises(ValueError):
        script.validate_secret_output_path(ROOT / "bootstrap-admin.json")
