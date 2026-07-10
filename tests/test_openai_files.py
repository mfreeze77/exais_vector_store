from __future__ import annotations

import asyncio
import re
from hashlib import sha256
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from svs_api import main as api_main
from svs_common.schemas import (
    OpenAIVectorStoreFileContentResponse,
    OpenAIVectorStoreFileDeletedResponse,
    OpenAIVectorStoreFileBatch,
    OpenAIVectorStoreFileBatchFilesPage,
    OpenAIVectorStoreFileListResponse,
    Principal,
)


class _Rows:
    def __init__(self, row=None):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row

    def all(self):
        return self.row if isinstance(self.row, list) else ([] if self.row is None else [self.row])


class _Db:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.calls = []
        self.committed = False

    def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params or {}))
        row = self.rows.pop(0) if self.rows else None
        return _Rows(row)

    def commit(self):
        self.committed = True


class _Upload:
    def __init__(self, *, filename: str, content_type: str, content: bytes):
        self.filename = filename
        self.content_type = content_type
        self._content = content

    async def read(self):
        return self._content


@pytest.fixture(autouse=True)
def _disable_route_rate_limits(monkeypatch):
    monkeypatch.setattr(api_main, "enforce_rate_limit", lambda *args, **kwargs: None)


def test_openai_file_object_uses_uploaded_file_metadata():
    row = {
        "id": "doc_123",
        "filename": "policy.md",
        "created_at": 1710000000,
        "expires_at": None,
        "bytes": 12,
        "file_attributes": {
            api_main.OPENAI_FILE_ID_ATTRIBUTE: "file_abc",
            api_main.OPENAI_FILE_PURPOSE_ATTRIBUTE: "assistants",
            api_main.OPENAI_FILE_BYTES_ATTRIBUTE: 99,
        },
    }

    assert api_main._openai_file_object_from_row(row) == {
        "id": "file_abc",
        "object": "file",
        "bytes": 99,
        "created_at": 1710000000,
        "filename": "policy.md",
        "purpose": "assistants",
    }


def test_new_openai_file_id_matches_current_openai_prefix():
    assert re.fullmatch(r"file-[0-9a-f]{24}", api_main._new_openai_file_id())


def test_decode_openai_text_upload_accepts_openai_text_encodings():
    assert api_main._decode_openai_text_upload(b"plain ascii") == "plain ascii"
    assert api_main._decode_openai_text_upload("hello utf8".encode("utf-8")) == "hello utf8"
    assert api_main._decode_openai_text_upload("\ufeffhello bom".encode("utf-8")) == "hello bom"
    assert api_main._decode_openai_text_upload("hello utf16".encode("utf-16")) == "hello utf16"


def test_decode_openai_text_upload_rejects_unsupported_binary_bytes():
    with pytest.raises(HTTPException) as exc:
        api_main._decode_openai_text_upload(b"\x80\x81\x82")

    assert exc.value.status_code == 415
    assert "UTF-8, UTF-16, or ASCII" in exc.value.detail


def test_openai_file_content_returns_plain_text_for_non_text_stored_mime(monkeypatch):
    principal = Principal(
        tenant_id="tenant",
        business_instance_id="biz",
        scopes=["documents:read"],
    )
    monkeypatch.setattr(
        api_main,
        "_resolve_document_row_for_file_id",
        lambda *args: {
            "id": "doc_pdf",
            "object_key": "parsed/doc_pdf.md",
            "mime_type": "application/pdf",
        },
    )
    monkeypatch.setattr(
        api_main,
        "ObjectStore",
        lambda: SimpleNamespace(get_text=lambda object_key: "Extracted PDF text"),
    )

    api_main.app.dependency_overrides[api_main.get_request_principal] = lambda: principal
    api_main.app.dependency_overrides[api_main.db_for_principal] = lambda: _Db()
    try:
        response = TestClient(api_main.app).get("/v1/files/file-pdf/content")
    finally:
        api_main.app.dependency_overrides.pop(api_main.get_request_principal, None)
        api_main.app.dependency_overrides.pop(api_main.db_for_principal, None)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.content == b"Extracted PDF text"


def test_openai_file_upload_expiration_seconds_validates_created_at_policy():
    assert api_main._openai_file_upload_expiration_seconds(None, None) is None
    assert api_main._openai_file_upload_expiration_seconds("created_at", "3600") == 3600
    assert api_main._openai_file_upload_expiration_seconds("created_at", 7200) == 7200

    invalid = [
        ("last_active_at", 3600),
        ("created_at", 0),
        ("created_at", -1),
        ("created_at", "soon"),
        (None, 3600),
    ]
    for anchor, seconds in invalid:
        with pytest.raises(HTTPException) as exc:
            api_main._openai_file_upload_expiration_seconds(anchor, seconds)
        assert exc.value.status_code == 422


def test_create_openai_file_decodes_utf16_text_upload(monkeypatch):
    captured = {}
    principal = Principal(
        tenant_id="tenant",
        business_instance_id="biz",
        scopes=["documents:write"],
        max_security_level=5,
    )
    db = _Db()

    async def fake_ingest_now(db_session, principal_arg, req):
        captured["req"] = req
        return SimpleNamespace(document_id="doc_utf16")

    monkeypatch.setattr(api_main, "enforce_rate_limit", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_main.ingestion, "ingest_now", fake_ingest_now)
    monkeypatch.setattr(api_main, "_new_openai_file_id", lambda: "file-utf16")
    monkeypatch.setattr(
        api_main,
        "_get_openai_file_row",
        lambda db_session, principal_arg, file_id: {
            "id": "doc_utf16",
            "filename": "utf16.txt",
            "created_at": 1710000000,
            "expires_at": None,
            "bytes": 24,
            "file_attributes": {
                api_main.OPENAI_FILE_ID_ATTRIBUTE: file_id,
                api_main.OPENAI_FILE_PURPOSE_ATTRIBUTE: "assistants",
                api_main.OPENAI_FILE_BYTES_ATTRIBUTE: 24,
            },
        },
    )

    payload = asyncio.run(api_main.create_openai_file(
        _Upload(
            filename="utf16.txt",
            content_type="text/plain",
            content="decoded utf16 text".encode("utf-16"),
        ),
        "assistants",
        principal,
        db,
    ))

    assert captured["req"].content == "decoded utf16 text"
    assert captured["req"].filename == "utf16.txt"
    assert captured["req"].attributes[api_main.OPENAI_FILE_ID_ATTRIBUTE] == "file-utf16"
    assert payload["id"] == "file-utf16"
    assert db.committed is True


def test_create_openai_file_persists_created_at_expiration(monkeypatch):
    principal = Principal(
        tenant_id="tenant",
        business_instance_id="biz",
        scopes=["documents:write"],
        max_security_level=5,
    )
    db = _Db()

    async def fake_ingest_now(db_session, principal_arg, req):
        return SimpleNamespace(document_id="doc_expiring")

    monkeypatch.setattr(api_main, "enforce_rate_limit", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_main.ingestion, "ingest_now", fake_ingest_now)
    monkeypatch.setattr(api_main, "_new_openai_file_id", lambda: "file-expiring")
    monkeypatch.setattr(
        api_main,
        "_get_openai_file_row",
        lambda db_session, principal_arg, file_id: {
            "id": "doc_expiring",
            "filename": "expiring.txt",
            "created_at": 1710000000,
            "expires_at": 1710003600,
            "bytes": 13,
            "file_attributes": {
                api_main.OPENAI_FILE_ID_ATTRIBUTE: file_id,
                api_main.OPENAI_FILE_PURPOSE_ATTRIBUTE: "assistants",
                api_main.OPENAI_FILE_BYTES_ATTRIBUTE: 13,
            },
        },
    )

    payload = asyncio.run(api_main.create_openai_file(
        _Upload(filename="expiring.txt", content_type="text/plain", content=b"expiring text"),
        "assistants",
        principal,
        db,
        expires_after_anchor="created_at",
        expires_after_seconds=3600,
    ))

    assert payload["expires_at"] == 1710003600
    expiration_update = [call for call in db.calls if "SET expires_at = created_at" in call[0]]
    assert expiration_update
    assert expiration_update[0][1] == {
        "seconds": 3600,
        "document_id": "doc_expiring",
        "tenant_id": "tenant",
        "biz_id": "biz",
    }
    assert db.committed is True


def test_list_openai_files_after_cursor_uses_public_id_tie_breaker_for_desc():
    principal = Principal(
        tenant_id="tenant",
        business_instance_id="biz",
        scopes=["documents:read"],
    )
    cursor_row = {
        "id": "doc_b",
        "public_file_id": "file_b",
        "filename": "b.txt",
        "created_at": 1710000000,
        "created_at_ts": "2024-03-09T16:00:00Z",
        "expires_at": None,
        "bytes": 1,
        "file_attributes": {
            api_main.OPENAI_FILE_ID_ATTRIBUTE: "file_b",
            api_main.OPENAI_FILE_PURPOSE_ATTRIBUTE: "assistants",
        },
    }
    page_row = {
        "id": "doc_a",
        "public_file_id": "file_a",
        "filename": "a.txt",
        "created_at": 1710000000,
        "created_at_ts": "2024-03-09T16:00:00Z",
        "expires_at": None,
        "bytes": 1,
        "file_attributes": {
            api_main.OPENAI_FILE_ID_ATTRIBUTE: "file_a",
            api_main.OPENAI_FILE_PURPOSE_ATTRIBUTE: "assistants",
        },
    }
    db = _Db([cursor_row, [page_row]])

    page = api_main.list_openai_files(
        limit=1,
        order="desc",
        after="file_b",
        principal=principal,
        db=db,
    )

    cursor_sql = db.calls[0][0]
    list_sql, list_params = db.calls[-1]
    assert "AS public_file_id" in cursor_sql
    assert "ORDER BY d.created_at DESC, public_file_id DESC LIMIT :limit" in list_sql
    assert "coalesce(dv.metadata #>> '{attributes,_openai_file_id}', d.id::text) < :after_file_id" in list_sql
    assert list_params["after_created_at"] == "2024-03-09T16:00:00Z"
    assert list_params["after_file_id"] == "file_b"
    assert page["data"][0]["id"] == "file_a"
    assert page["first_id"] == "file_a"
    assert page["has_more"] is False


def test_list_openai_files_after_cursor_uses_public_id_tie_breaker_for_asc():
    principal = Principal(
        tenant_id="tenant",
        business_instance_id="biz",
        scopes=["documents:read"],
    )
    cursor_row = {
        "id": "doc_b",
        "public_file_id": "file_b",
        "filename": "b.txt",
        "created_at": 1710000000,
        "created_at_ts": "2024-03-09T16:00:00Z",
        "expires_at": None,
        "bytes": 1,
        "file_attributes": {
            api_main.OPENAI_FILE_ID_ATTRIBUTE: "file_b",
            api_main.OPENAI_FILE_PURPOSE_ATTRIBUTE: "assistants",
        },
    }
    page_row = {
        "id": "doc_c",
        "public_file_id": "file_c",
        "filename": "c.txt",
        "created_at": 1710000000,
        "created_at_ts": "2024-03-09T16:00:00Z",
        "expires_at": None,
        "bytes": 1,
        "file_attributes": {
            api_main.OPENAI_FILE_ID_ATTRIBUTE: "file_c",
            api_main.OPENAI_FILE_PURPOSE_ATTRIBUTE: "assistants",
        },
    }
    db = _Db([cursor_row, [page_row]])

    page = api_main.list_openai_files(
        limit=1,
        order="asc",
        after="file_b",
        principal=principal,
        db=db,
    )

    list_sql, list_params = db.calls[-1]
    assert "ORDER BY d.created_at ASC, public_file_id ASC LIMIT :limit" in list_sql
    assert "coalesce(dv.metadata #>> '{attributes,_openai_file_id}', d.id::text) > :after_file_id" in list_sql
    assert list_params["after_file_id"] == "file_b"
    assert page["data"][0]["id"] == "file_c"


def test_create_openai_file_returns_cached_idempotency_response(monkeypatch):
    principal = Principal(
        tenant_id="tenant",
        business_instance_id="biz",
        scopes=["documents:write"],
        max_security_level=5,
    )
    db = _Db()
    cached = {
        "id": "file_cached",
        "object": "file",
        "bytes": 12,
        "created_at": 1710000000,
        "filename": "cached.txt",
        "purpose": "assistants",
    }
    seen = {}

    async def fail_ingest(*args, **kwargs):
        raise AssertionError("cached idempotency response should skip ingest")

    def fake_check(db_session, principal_arg, key, fingerprint):
        seen["key"] = key
        seen["fingerprint"] = fingerprint
        return cached

    monkeypatch.setattr(api_main, "enforce_rate_limit", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_main, "check_idempotency", fake_check)
    monkeypatch.setattr(api_main.ingestion, "ingest_now", fail_ingest)

    payload = asyncio.run(api_main.create_openai_file(
        _Upload(filename="cached.txt", content_type="text/plain", content=b"cached text"),
        "assistants",
        principal,
        db,
        idempotency_key="idem_file",
    ))

    expected_fingerprint = api_main._openai_idempotency_fingerprint(
        "POST /v1/files",
        {
            "filename": "cached.txt",
            "content_type": "text/plain",
            "purpose": "assistants",
            "expires_after": None,
            "bytes": len(b"cached text"),
            "sha256": sha256(b"cached text").hexdigest(),
        },
    )
    assert payload == cached
    assert seen == {"key": "idem_file", "fingerprint": expected_fingerprint}
    assert db.committed is False


def test_create_openai_file_idempotency_key_reuse_with_changed_upload_returns_409(monkeypatch):
    principal = Principal(
        tenant_id="tenant",
        business_instance_id="biz",
        scopes=["documents:write"],
        max_security_level=5,
    )
    db = _Db([{
        "response": {"id": "file_cached"},
        "request_fingerprint": "different-fingerprint",
        "status_code": 200,
    }])

    async def fail_ingest(*args, **kwargs):
        raise AssertionError("mismatched idempotency key should fail before ingest")

    monkeypatch.setattr(api_main, "enforce_rate_limit", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_main.ingestion, "ingest_now", fail_ingest)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(api_main.create_openai_file(
            _Upload(filename="changed.txt", content_type="text/plain", content=b"changed text"),
            "assistants",
            principal,
            db,
            idempotency_key="idem_file",
        ))

    assert exc.value.status_code == 409
    assert "different request body" in exc.value.detail
    assert db.committed is False


def test_openai_vector_store_file_payload_keeps_internal_row_id():
    row = {
        "id": "vsf_123",
        "public_file_id": "file_abc",
        "vector_store_id": "vs_123",
        "document_id": "doc_123",
        "status": "completed",
        "attributes": {
            "source": "upload",
            "attached_from_file_id": "file_abc",
            "_file_batch_id": "vsfb_123",
            api_main.VECTOR_STORE_FILE_CHUNKING_STRATEGY_ATTRIBUTE: {"type": "static"},
        },
        "usage_bytes": 99,
        "created_at": 1710000000,
        "completed_at": 1710000001,
        "last_error": None,
    }

    assert api_main._openai_vector_store_file_payload(row) == {
        "id": "file_abc",
        "object": "vector_store.file",
        "vector_store_id": "vs_123",
        "document_id": "doc_123",
        "vector_store_file_id": "vsf_123",
        "status": "completed",
        "attributes": {"source": "upload"},
        "usage_bytes": 99,
        "created_at": 1710000000,
        "completed_at": 1710000001,
        "last_error": None,
        "chunking_strategy": {"type": "static"},
    }


def test_openai_vector_store_file_public_attributes_hide_internal_keys():
    assert api_main._public_vector_store_file_attributes(
        {
            "region": "us",
            "attached_from_file_id": "file_abc",
            "_file_batch_id": "vsfb_123",
            api_main.VECTOR_STORE_FILE_CHUNKING_STRATEGY_ATTRIBUTE: {"type": "static"},
        }
    ) == {"region": "us"}


def test_openai_vector_store_file_patch_preserves_attachment_pointer():
    row = {
        "attributes": {
            "attached_from_file_id": "file_abc",
            "_file_batch_id": "vsfb_123",
            api_main.VECTOR_STORE_FILE_CHUNKING_STRATEGY_ATTRIBUTE: {"type": "static"},
            "source": "upload",
        }
    }

    attrs = api_main._vector_store_file_patch_attributes(row, {"attributes": {"region": "us"}})

    assert attrs == {
        "region": "us",
        "attached_from_file_id": "file_abc",
        "_file_batch_id": "vsfb_123",
        api_main.VECTOR_STORE_FILE_CHUNKING_STRATEGY_ATTRIBUTE: {"type": "static"},
    }


def test_openai_vector_store_file_attributes_accept_openai_scalar_limits():
    attrs = {f"k{i}": "v" for i in range(13)}
    attrs.update({"region": "us", "rank": 3, "active": True})
    row = {
        "attributes": {
            "attached_from_file_id": "file_abc",
            "_file_batch_id": "vsfb_123",
            api_main.VECTOR_STORE_FILE_CHUNKING_STRATEGY_ATTRIBUTE: {"type": "static"},
            "old": "value",
        }
    }

    result = api_main._vector_store_file_patch_attributes(row, {"attributes": attrs})

    assert result["region"] == "us"
    assert result["rank"] == 3
    assert result["active"] is True
    assert "old" not in result
    assert result["attached_from_file_id"] == "file_abc"
    assert result["_file_batch_id"] == "vsfb_123"
    assert result[api_main.VECTOR_STORE_FILE_CHUNKING_STRATEGY_ATTRIBUTE] == {"type": "static"}


@pytest.mark.parametrize(
    "attrs",
    [
        0,
        [],
        {f"k{i}": "v" for i in range(17)},
        {"": "v"},
        {"bad key": "v"},
        {"k" * 65: "v"},
        {"region": "x" * 513},
        {"region": {"nested": "no"}},
        {"api_key": "secret"},
        {"attached_from_file_id": "file_abc"},
        {"score": float("inf")},
    ],
)
def test_openai_vector_store_file_attributes_reject_invalid_public_values(attrs):
    with pytest.raises(HTTPException) as exc:
        api_main._vector_store_file_patch_attributes({"attributes": {}}, {"attributes": attrs})

    assert exc.value.status_code == 422


def test_openai_file_batch_files_split_file_refs_from_inline_ingests():
    file_refs, inline_files = api_main._split_openai_file_batch_files([
        {
            "file_id": "file_abc",
            "attributes": {"region": "us"},
            "chunking_strategy": {"type": "static", "max_chunk_size_tokens": 1200, "chunk_overlap_tokens": 200},
        },
        {"title": "Inline", "content": "queued inline ingest"},
    ])

    assert file_refs == [{
        "file_id": "file_abc",
        "attributes": {
            "region": "us",
            api_main.VECTOR_STORE_FILE_CHUNKING_STRATEGY_ATTRIBUTE: {
                "type": "static",
                "max_chunk_size_tokens": 1200,
                "chunk_overlap_tokens": 200,
            },
        },
    }]
    assert inline_files == [{"title": "Inline", "content": "queued inline ingest"}]


def test_openai_file_batch_inline_file_attributes_are_normalized():
    parts = api_main._openai_file_batch_request_parts({
        "files": [
            {
                "title": "Inline",
                "content": "queued inline ingest",
                "metadata": {"region": "us"},
                "chunking_strategy": {"type": "static", "max_chunk_size_tokens": 1200, "chunk_overlap_tokens": 200},
            }
        ],
    })

    assert parts["inline_files"][0]["attributes"] == {
        "region": "us",
        api_main.VECTOR_STORE_FILE_CHUNKING_STRATEGY_ATTRIBUTE: {
            "type": "static",
            "max_chunk_size_tokens": 1200,
            "chunk_overlap_tokens": 200,
        },
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"file_ids": ["file_1"], "metadata": {"api_key": "secret"}},
        {"files": [{"file_id": "file_1", "attributes": {"region": {"nested": "no"}}}]},
        {"files": [{"title": "Inline", "content": "body", "attributes": {"_file_batch_id": "vsfb_123"}}]},
    ],
)
def test_openai_file_batch_request_rejects_invalid_global_and_per_file_attributes(payload):
    with pytest.raises(HTTPException) as exc:
        api_main._openai_file_batch_request_parts(payload)

    assert exc.value.status_code == 422


def test_openai_file_batch_request_rejects_mixed_file_inputs():
    with pytest.raises(HTTPException) as exc:
        api_main._openai_file_batch_request_parts({
            "file_ids": ["file_1"],
            "files": [{"file_id": "file_2"}],
        })

    assert exc.value.status_code == 422
    assert "mutually exclusive" in exc.value.detail


def test_openai_file_batch_request_rejects_non_list_inputs():
    with pytest.raises(HTTPException) as files_exc:
        api_main._openai_file_batch_request_parts({"files": "file_1"})
    with pytest.raises(HTTPException) as file_ids_exc:
        api_main._openai_file_batch_request_parts({"file_ids": "file_1"})

    assert files_exc.value.status_code == 422
    assert "files must be a list" in files_exc.value.detail
    assert file_ids_exc.value.status_code == 422
    assert "file_ids must be a list" in file_ids_exc.value.detail


def test_openai_vector_store_file_attach_rejects_invalid_chunking_strategy():
    with pytest.raises(HTTPException) as exc:
        api_main._vector_store_file_attach_attributes({
            "chunking_strategy": {
                "type": "static",
                "max_chunk_size_tokens": 800,
                "chunk_overlap_tokens": 401,
            }
        })

    assert exc.value.status_code == 422
    assert "chunk_overlap_tokens" in exc.value.detail


def test_openai_file_batch_request_rejects_oversized_batches():
    with pytest.raises(HTTPException) as exc:
        api_main._openai_file_batch_request_parts({
            "file_ids": [f"file_{i}" for i in range(api_main.OPENAI_FILE_BATCH_MAX_FILES + 1)],
        })

    assert exc.value.status_code == 422
    assert str(api_main.OPENAI_FILE_BATCH_MAX_FILES) in exc.value.detail


def test_openai_file_batch_request_applies_global_metadata_to_file_ids():
    parts = api_main._openai_file_batch_request_parts({
        "file_ids": ["file_1", "file_2"],
        "metadata": {"region": "us"},
        "chunking_strategy": {"type": "static", "max_chunk_size_tokens": 1200},
    })

    assert parts["file_ids"] == ["file_1", "file_2"]
    assert parts["file_id_attributes"] == {
        "region": "us",
        api_main.VECTOR_STORE_FILE_CHUNKING_STRATEGY_ATTRIBUTE: {
            "type": "static",
            "max_chunk_size_tokens": 1200,
        },
    }
    assert parts["file_refs"] == []
    assert parts["inline_files"] == []
    assert parts["total"] == 2


def test_openai_file_batch_payload_fills_zero_counts_and_omits_null_completed_at():
    payload = api_main._openai_file_batch_payload({
        "id": "vsfb_123",
        "vector_store_id": "vs_123",
        "status": "completed",
        "file_counts": {"completed": 1, "total": 1},
        "created_at": 1710000000,
        "completed_at": None,
    })

    assert payload == {
        "id": "vsfb_123",
        "object": "vector_store.file_batch",
        "vector_store_id": "vs_123",
        "status": "completed",
        "file_counts": {
            "in_progress": 0,
            "completed": 1,
            "failed": 0,
            "cancelled": 0,
            "total": 1,
        },
        "created_at": 1710000000,
    }


def test_openai_file_batch_response_models_preserve_runtime_payloads():
    batch = {
        "id": "vsfb_contract",
        "object": "vector_store.file_batch",
        "vector_store_id": "vs_contract",
        "status": "completed",
        "file_counts": {
            "in_progress": 0,
            "completed": 2,
            "failed": 0,
            "cancelled": 0,
            "total": 2,
        },
        "created_at": 1710000000,
    }
    page = {
        "object": "list",
        "data": [{
            "id": "file_contract",
            "object": "vector_store.file",
            "vector_store_id": "vs_contract",
            "document_id": "doc_contract",
            "vector_store_file_id": "vsf_contract",
            "status": "completed",
            "attributes": {"region": "us"},
            "usage_bytes": 7,
            "created_at": 1710000001,
            "completed_at": 1710000002,
            "last_error": None,
            "chunking_strategy": {"type": "auto"},
        }],
        "first_id": "file_contract",
        "last_id": "file_contract",
        "has_more": False,
    }

    assert OpenAIVectorStoreFileBatch.model_validate(batch).model_dump(mode="python", exclude_unset=True) == batch
    assert OpenAIVectorStoreFileBatchFilesPage.model_validate(page).model_dump(mode="python", exclude_unset=True) == page


def test_openai_vector_store_file_response_models_preserve_runtime_payloads():
    page = {
        "object": "list",
        "data": [{
            "id": "file_contract",
            "object": "vector_store.file",
            "vector_store_id": "vs_contract",
            "document_id": "doc_contract",
            "vector_store_file_id": "vsf_contract",
            "status": "completed",
            "attributes": {"region": "us"},
            "usage_bytes": 7,
            "created_at": 1710000001,
            "completed_at": 1710000002,
            "last_error": None,
        }],
        "first_id": "file_contract",
        "last_id": "file_contract",
        "has_more": False,
    }
    deleted = {
        "id": "file_contract",
        "object": "vector_store.file.deleted",
        "deleted": True,
    }
    content = {
        "object": "vector_store.file_content",
        "data": [{
            "type": "text",
            "text": "parsed content",
            "heading_path": ["A"],
            "page_start": 1,
            "page_end": 2,
        }],
    }

    assert OpenAIVectorStoreFileListResponse.model_validate(page).model_dump(mode="python", exclude_unset=True) == page
    assert OpenAIVectorStoreFileDeletedResponse.model_validate(deleted).model_dump(mode="python", exclude_unset=True) == deleted
    assert OpenAIVectorStoreFileContentResponse.model_validate(content).model_dump(mode="python", exclude_unset=True) == content


def test_attach_file_returns_cached_idempotency_response(monkeypatch):
    principal = Principal(
        tenant_id="tenant",
        business_instance_id="biz",
        scopes=["documents:write"],
    )
    cached = {
        "id": "file_cached",
        "object": "vector_store.file",
        "vector_store_id": "vs_123",
        "status": "completed",
    }

    async def fail_attach(*args, **kwargs):
        raise AssertionError("cached idempotency response should skip attach")

    monkeypatch.setattr(api_main, "check_idempotency", lambda *args, **kwargs: cached)
    monkeypatch.setattr(api_main, "_attach_existing_document_ids_to_vector_store", fail_attach)

    payload = asyncio.run(api_main.attach_file(
        "vs_123",
        {"file_id": "file_cached"},
        principal,
        _Db(),
        idempotency_key="idem_attach",
    ))

    assert payload == cached


def test_create_file_batch_returns_cached_idempotency_response(monkeypatch):
    principal = Principal(
        tenant_id="tenant",
        business_instance_id="biz",
        scopes=["documents:write"],
    )
    cached = {
        "id": "vsfb_cached",
        "object": "vector_store.file_batch",
        "vector_store_id": "vs_123",
        "status": "completed",
        "file_counts": {"in_progress": 0, "completed": 1, "failed": 0, "cancelled": 0, "total": 1},
        "created_at": 1710000000,
    }

    def fail_refresh(*args, **kwargs):
        raise AssertionError("cached idempotency response should skip vector store refresh")

    monkeypatch.setattr(api_main, "check_idempotency", lambda *args, **kwargs: cached)
    monkeypatch.setattr(api_main, "_refresh_vector_store_activity_or_404", fail_refresh)

    payload = asyncio.run(api_main.create_file_batch(
        "vs_123",
        {"file_ids": ["file_cached"]},
        principal,
        _Db(),
        idempotency_key="idem_batch",
    ))

    assert payload == cached


def test_delete_openai_file_returns_cached_idempotency_response(monkeypatch):
    principal = Principal(
        tenant_id="tenant",
        business_instance_id="biz",
        scopes=["documents:write"],
    )
    cached = {"id": "file_cached", "object": "file", "deleted": True}

    def fail_resolve(*args, **kwargs):
        raise AssertionError("cached idempotency response should skip file delete lookup")

    monkeypatch.setattr(api_main, "check_idempotency", lambda *args, **kwargs: cached)
    monkeypatch.setattr(api_main, "_resolve_document_row_for_file_id", fail_resolve)

    payload = api_main.delete_openai_file(
        "file_cached",
        principal,
        _Db(),
        idempotency_key="idem_file_delete",
    )

    assert payload == cached


def test_update_vector_store_file_returns_cached_idempotency_response(monkeypatch):
    principal = Principal(
        tenant_id="tenant",
        business_instance_id="biz",
        scopes=["vector_stores:write"],
    )
    cached = {
        "id": "file_cached",
        "object": "vector_store.file",
        "vector_store_id": "vs_123",
        "status": "completed",
        "attributes": {"region": "us"},
    }

    def fail_row_lookup(*args, **kwargs):
        raise AssertionError("cached idempotency response should skip vector-store file update")

    monkeypatch.setattr(api_main, "check_idempotency", lambda *args, **kwargs: cached)
    monkeypatch.setattr(api_main, "_vector_store_file_row", fail_row_lookup)

    payload = api_main.update_vector_store_file(
        "vs_123",
        "file_cached",
        {"attributes": {"region": "us"}},
        principal,
        _Db(),
        idempotency_key="idem_vsf_update",
    )

    assert payload == cached


def test_delete_vector_store_file_returns_cached_idempotency_response(monkeypatch):
    principal = Principal(
        tenant_id="tenant",
        business_instance_id="biz",
        scopes=["vector_stores:write"],
    )
    cached = {"id": "file_cached", "object": "vector_store.file.deleted", "deleted": True}

    def fail_row_lookup(*args, **kwargs):
        raise AssertionError("cached idempotency response should skip vector-store file delete")

    monkeypatch.setattr(api_main, "check_idempotency", lambda *args, **kwargs: cached)
    monkeypatch.setattr(api_main, "_vector_store_file_row", fail_row_lookup)

    payload = api_main.delete_vector_store_file(
        "vs_123",
        "file_cached",
        principal,
        _Db(),
        idempotency_key="idem_vsf_delete",
    )

    assert payload == cached


def test_cancel_file_batch_returns_cached_idempotency_response(monkeypatch):
    principal = Principal(
        tenant_id="tenant",
        business_instance_id="biz",
        scopes=["documents:write"],
    )
    cached = {
        "id": "vsfb_cached",
        "object": "vector_store.file_batch",
        "vector_store_id": "vs_123",
        "status": "cancelled",
        "file_counts": {"in_progress": 0, "completed": 0, "failed": 0, "cancelled": 1, "total": 1},
        "created_at": 1710000000,
        "completed_at": 1710000001,
    }
    db = _Db()

    monkeypatch.setattr(api_main, "check_idempotency", lambda *args, **kwargs: cached)

    payload = api_main.cancel_file_batch(
        "vs_123",
        "vsfb_cached",
        principal,
        db,
        idempotency_key="idem_batch_cancel",
    )

    assert payload == cached
    assert db.calls == []


def test_cancel_file_batch_targets_queued_jobs_and_returns_without_read_scope():
    principal = Principal(
        tenant_id="tenant",
        business_instance_id="biz",
        scopes=["documents:write"],
    )
    db = _Db([
        None,
        {
            "id": "vsfb_123",
            "vector_store_id": "vs_123",
            "status": "cancelled",
            "file_counts": {"in_progress": 0, "completed": 1, "failed": 0, "cancelled": 2, "total": 3},
            "created_at": 1710000000,
            "completed_at": 1710000001,
        },
    ])

    payload = api_main.cancel_file_batch("vs_123", "vsfb_123", principal, db)

    assert payload["object"] == "vector_store.file_batch"
    assert payload["status"] == "cancelled"
    assert payload["file_counts"]["cancelled"] == 2
    assert db.committed is True
    cancel_jobs_sql = db.calls[0][0]
    cancel_batch_sql = db.calls[1][0]
    assert "payload->>'file_batch_id'=:batch_id" in cancel_jobs_sql
    assert "payload #>> '{document,attributes,_file_batch_id}' = :batch_id" in cancel_jobs_sql
    assert "coalesce((file_counts->>'cancelled')::int,0) + coalesce((file_counts->>'in_progress')::int,0)" in cancel_batch_sql
    assert "RETURNING id, vector_store_id, status, file_counts" in cancel_batch_sql


def test_list_file_batch_files_delegates_batch_filters(monkeypatch):
    principal = Principal(
        tenant_id="tenant",
        business_instance_id="biz",
        scopes=["vector_stores:read"],
    )
    seen = {}

    def fake_list_rows(db, principal, vector_store_id, **kwargs):
        seen.update(kwargs)
        return ([{
            "id": "vsf_123",
            "public_file_id": "file_123",
            "vector_store_id": vector_store_id,
            "document_id": "doc_123",
            "status": "completed",
            "attributes": {},
            "usage_bytes": 7,
            "created_at": 1710000000,
            "completed_at": 1710000001,
            "last_error": None,
        }], False)

    monkeypatch.setattr(api_main, "_list_vector_store_file_rows", fake_list_rows)

    page = api_main.list_file_batch_files(
        "vs_123",
        "vsfb_123",
        limit=5,
        order="asc",
        after="file_before",
        before=None,
        status_filter="completed",
        principal=principal,
        db=object(),
    )

    assert seen == {
        "limit": 5,
        "order": "asc",
        "after": "file_before",
        "before": None,
        "status_filter": "completed",
        "batch_id": "vsfb_123",
    }
    assert page["object"] == "list"
    assert page["data"][0]["id"] == "file_123"
