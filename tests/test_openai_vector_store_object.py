from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from svs_api import main as api_main
from svs_common.schemas import ChunkRecord, OpenAIVectorStoreSearchRequest, Principal, VectorStoreCreateRequest, VectorStoreUpdateRequest
from svs_common.vector_store_repo import (
    OPENAI_CHUNKING_STRATEGY_ATTRIBUTE,
    OPENAI_DESCRIPTION_ATTRIBUTE,
    VectorStoreRepository,
    VectorStoreUnavailableError,
    _expires_at_from_policy,
    _vector_store_response_from_row,
    refresh_vector_store_activity,
    require_active_vector_store,
)


class _Rows:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []

    def mappings(self):
        return self

    def first(self):
        return self.row

    def all(self):
        return self.rows


class _Db:
    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []

    def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params or {}))
        result = self.rows.pop(0) if self.rows else None
        if isinstance(result, list):
            return _Rows(rows=result)
        return _Rows(row=result)

    def commit(self):
        self.committed = True


@pytest.fixture(autouse=True)
def _disable_route_rate_limits(monkeypatch):
    monkeypatch.setattr(api_main, "enforce_rate_limit", lambda *args, **kwargs: None)


def test_openai_vector_store_create_accepts_empty_body_and_current_fields():
    empty = VectorStoreCreateRequest()
    assert empty.name is None
    assert empty.file_ids == []

    req = VectorStoreCreateRequest.model_validate(
        {
            "name": "Support FAQ",
            "description": "Customer support corpus",
            "file_ids": ["doc_123"],
            "metadata": {"region": "us"},
            "expires_after": {"anchor": "last_active_at", "days": 7},
            "chunking_strategy": {"type": "auto"},
        }
    )

    assert req.description == "Customer support corpus"
    assert req.file_ids == ["doc_123"]
    assert req.expires_after == {"anchor": "last_active_at", "days": 7}
    assert req.chunking_strategy == {"type": "auto"}


def test_openai_vector_store_create_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        VectorStoreCreateRequest.model_validate({"name": "Docs", "silently_ignored": True})


def test_openai_vector_store_update_accepts_empty_body_and_rejects_unknown_fields():
    assert VectorStoreUpdateRequest().model_dump(exclude_unset=True) == {}

    with pytest.raises(ValidationError):
        VectorStoreUpdateRequest.model_validate({"unknown": "drift"})


@pytest.mark.parametrize("model", [VectorStoreCreateRequest, VectorStoreUpdateRequest])
def test_openai_vector_store_metadata_accepts_documented_string_limits(model):
    metadata = {f"k{i}": "v" for i in range(16)}

    req = model.model_validate({"metadata": metadata})

    assert req.metadata == metadata
    assert model.model_validate({"attributes": {"region": "us"}}).attributes == {"region": "us"}


@pytest.mark.parametrize("model", [VectorStoreCreateRequest, VectorStoreUpdateRequest])
@pytest.mark.parametrize(
    "metadata",
    [
        0,
        [],
        {f"k{i}": "v" for i in range(17)},
        {"": "v"},
        {"k" * 65: "v"},
        {"region": "x" * 513},
        {"rank": 1},
        {"_openai_description": "spoof"},
        {"_openai_chunking_strategy": "spoof"},
    ],
)
def test_openai_vector_store_metadata_rejects_openai_incompatible_maps(model, metadata):
    with pytest.raises(ValidationError):
        model.model_validate({"metadata": metadata})


@pytest.mark.parametrize("model", [VectorStoreCreateRequest, VectorStoreUpdateRequest])
def test_openai_vector_store_rejects_invalid_chunking_strategy(model):
    assert model.model_validate({
        "chunking_strategy": {
            "type": "static",
            "max_chunk_size_tokens": 1200,
            "chunk_overlap_tokens": 200,
        }
    }).chunking_strategy == {
        "type": "static",
        "max_chunk_size_tokens": 1200,
        "chunk_overlap_tokens": 200,
    }

    invalid_values = [
        {"type": "unknown"},
        {"type": "auto", "max_chunk_size_tokens": 800},
        {"type": "static", "max_chunk_size_tokens": 99},
        {"type": "static", "max_chunk_size_tokens": 4097},
        {"type": "static", "max_chunk_size_tokens": 800, "chunk_overlap_tokens": -1},
        {"type": "static", "max_chunk_size_tokens": 800, "chunk_overlap_tokens": 401},
        {"type": "static", "chunk_overlap_tokens": 401},
        {"type": "static", "unexpected": True},
    ]
    for chunking_strategy in invalid_values:
        with pytest.raises(ValidationError):
            model.model_validate({"chunking_strategy": chunking_strategy})


def test_create_vector_store_file_ids_apply_chunking_strategy_to_attached_files(monkeypatch):
    created = api_main.VectorStoreResponse(id="vs_123", name="Support FAQ")
    captured: dict[str, object] = {}

    def fake_create(db, principal, req):
        captured["create_request"] = req
        return created

    def fake_get(db, principal, vector_store_id):
        captured["get_vector_store_id"] = vector_store_id
        return created

    async def fake_attach(db, principal, vector_store_id, file_ids, *, attributes=None, file_batch_id=None):
        captured["attach_vector_store_id"] = vector_store_id
        captured["attach_file_ids"] = file_ids
        captured["attach_attributes"] = attributes
        captured["attach_file_batch_id"] = file_batch_id
        return ["vsf_123"]

    monkeypatch.setattr(api_main, "check_idempotency", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_main, "store_idempotency", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_main.vs_repo, "create", fake_create)
    monkeypatch.setattr(api_main.vs_repo, "get", fake_get)
    monkeypatch.setattr(api_main, "_attach_existing_document_ids_to_vector_store", fake_attach)

    req = VectorStoreCreateRequest.model_validate({
        "name": "Support FAQ",
        "file_ids": ["file_abc"],
        "metadata": {"region": "us"},
        "chunking_strategy": {
            "type": "static",
            "max_chunk_size_tokens": 1200,
            "chunk_overlap_tokens": 200,
        },
    })
    response = asyncio.run(api_main.create_vector_store(
        req,
        idempotency_key=None,
        principal=Principal(
            tenant_id="tenant",
            business_instance_id="biz",
            scopes=["vector_stores:write", "documents:write"],
        ),
        db=_Db([]),
    ))

    assert response == created
    assert captured["get_vector_store_id"] == "vs_123"
    assert captured["attach_vector_store_id"] == "vs_123"
    assert captured["attach_file_ids"] == ["file_abc"]
    assert captured["attach_file_batch_id"] is None
    assert captured["attach_attributes"] == {
        api_main.VECTOR_STORE_FILE_CHUNKING_STRATEGY_ATTRIBUTE: {
            "type": "static",
            "max_chunk_size_tokens": 1200,
            "chunk_overlap_tokens": 200,
        },
    }


@pytest.mark.parametrize("model", [VectorStoreCreateRequest, VectorStoreUpdateRequest])
def test_openai_vector_store_expires_after_accepts_only_last_active_days_shape(model):
    assert model.model_validate({"expires_after": {"anchor": "last_active_at", "days": 1}}).expires_after == {
        "anchor": "last_active_at",
        "days": 1,
    }
    assert model.model_validate({"expires_after": None}).expires_after is None

    invalid_policies = [
        {"anchor": "created_at", "days": 7},
        {"anchor": "last_active_at"},
        {"anchor": "last_active_at", "days": 0},
        {"anchor": "last_active_at", "days": -1},
        {"anchor": "last_active_at", "days": True},
        {"anchor": "last_active_at", "days": "7"},
        {"anchor": "last_active_at", "days": 7, "duration_days": 7},
        {"anchor_timestamp": "last_active_at", "days": 7},
        ["last_active_at", 7],
    ]
    for policy in invalid_policies:
        with pytest.raises(ValidationError):
            model.model_validate({"expires_after": policy})


def test_vector_store_response_projects_openai_object_fields_without_internal_metadata():
    row = {
        "id": "vs_123",
        "name": "Support FAQ",
        "status": "completed",
        "usage_bytes": 139920,
        "attributes": {
            "region": "us",
            OPENAI_DESCRIPTION_ATTRIBUTE: "Customer support corpus",
            OPENAI_CHUNKING_STRATEGY_ATTRIBUTE: {"type": "auto"},
        },
        "expires_after": {"anchor": "last_active_at", "days": 7},
        "created_at": 1699061776,
        "expires_at": None,
        "last_active_at": 1699061999,
        "file_counts": {"completed": 3, "total": 3},
    }

    payload = _vector_store_response_from_row(row).model_dump()

    assert payload["object"] == "vector_store"
    assert payload["description"] == "Customer support corpus"
    assert payload["bytes"] == 139920
    assert payload["usage_bytes"] == 139920
    assert payload["file_counts"] == {
        "in_progress": 0,
        "completed": 3,
        "failed": 0,
        "cancelled": 0,
        "total": 3,
    }
    assert payload["metadata"] == {"region": "us"}
    assert payload["attributes"] == {"region": "us"}


def test_vector_store_update_metadata_preserves_internal_description_and_chunking():
    expected_attrs = {
        "region": "eu",
        OPENAI_DESCRIPTION_ATTRIBUTE: "Customer support corpus",
        OPENAI_CHUNKING_STRATEGY_ATTRIBUTE: {"type": "auto"},
    }
    response_row = {
        "id": "vs_123",
        "name": "Support FAQ",
        "status": "completed",
        "usage_bytes": 0,
        "attributes": expected_attrs,
        "expires_after": None,
        "created_at": 1699061776,
        "expires_at": None,
        "last_active_at": 1699061999,
        "file_counts": {},
    }
    db = _Db([
        {
            "attributes": {
                "region": "us",
                "old": "gone",
                OPENAI_DESCRIPTION_ATTRIBUTE: "Customer support corpus",
                OPENAI_CHUNKING_STRATEGY_ATTRIBUTE: {"type": "auto"},
            }
        },
        None,
        response_row,
    ])
    principal = Principal(tenant_id="tenant", business_instance_id="biz")

    response = VectorStoreRepository().update(
        db,
        principal,
        "vs_123",
        VectorStoreUpdateRequest.model_validate({"metadata": {"region": "eu"}}),
    )

    update_call = [call for call in db.calls if "UPDATE vector_stores SET" in call[0]][0]
    assert json.loads(update_call[1]["attrs"]) == expected_attrs
    assert response.metadata == {"region": "eu"}
    assert response.description == "Customer support corpus"


def test_expires_at_from_policy_uses_supplied_activity_anchor():
    anchor = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    assert _expires_at_from_policy({"anchor": "last_active_at", "days": 7}, anchor_time=anchor) == anchor + timedelta(days=7)
    assert _expires_at_from_policy({"anchor": "last_active_at", "duration_days": "2"}, anchor_time=anchor) == anchor + timedelta(days=2)
    assert _expires_at_from_policy({"anchor": "created_at", "days": 7}, anchor_time=anchor) is None
    assert _expires_at_from_policy({"duration_days": "2"}, anchor_time=anchor) is None
    assert _expires_at_from_policy({"anchor": "last_active_at"}, anchor_time=anchor) is None
    assert _expires_at_from_policy({"anchor": "last_active_at", "days": 0}, anchor_time=anchor) is None
    assert _expires_at_from_policy({"anchor": "last_active_at", "days": True}, anchor_time=anchor) is None
    assert _expires_at_from_policy({"anchor": "last_active_at", "days": "bad"}, anchor_time=anchor) is None


def test_refresh_vector_store_activity_slides_last_active_expiration():
    principal = Principal(tenant_id="tenant", business_instance_id="biz")
    db = _Db([{"id": "vs_123"}])

    refreshed = refresh_vector_store_activity(db, principal, "vs_123", usage_bytes_delta=42)

    assert refreshed is True
    sql, params = db.calls[0]
    assert "last_active_at=now()" in sql
    assert "usage_bytes=usage_bytes + :usage_bytes_delta" in sql
    assert "coalesce(expires_after->>'anchor', expires_after->>'anchor_timestamp') = 'last_active_at'" in sql
    assert "^[1-9][0-9]*$" in sql
    assert "(expires_at IS NULL OR expires_at > now())" in sql
    assert params["usage_bytes_delta"] == 42
    assert params["tenant_id"] == "tenant"
    assert params["biz_id"] == "biz"


def test_require_active_vector_store_rejects_expired_store_before_sweeper():
    principal = Principal(tenant_id="tenant", business_instance_id="biz")
    db = _Db([{"id": "vs_123", "status": "completed", "is_expired": True}])

    with pytest.raises(VectorStoreUnavailableError) as exc:
        require_active_vector_store(db, principal, "vs_123")

    assert exc.value.reason == "expired"


def test_openai_search_page_fails_closed_before_retrieval_for_expired_store(monkeypatch):
    principal = Principal(tenant_id="tenant", business_instance_id="biz")
    req = OpenAIVectorStoreSearchRequest(query="what changed?")

    def fail_refresh(_db, _principal, vector_store_id, *, usage_bytes_delta=0):
        assert vector_store_id == "vs_expired"
        assert usage_bytes_delta == 0
        raise HTTPException(status_code=404, detail="Vector store not found or expired")

    async def retrieval_should_not_run(*_args, **_kwargs):
        raise AssertionError("retrieval should not run for expired vector stores")

    monkeypatch.setattr(api_main, "_refresh_vector_store_activity_or_404", fail_refresh)
    monkeypatch.setattr(api_main.retrieval, "search", retrieval_should_not_run)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(api_main._openai_vector_store_search_page("vs_expired", req, principal, object()))

    assert exc.value.status_code == 404


def test_openai_search_page_uses_next_page_cursor(monkeypatch):
    principal = Principal(tenant_id="tenant", business_instance_id="biz")
    chunks = [
        ChunkRecord(id=f"chk_{index}", document_id=f"doc_{index}", ordinal=index, text=f"chunk {index}", score=1.0 - (index * 0.1))
        for index in range(4)
    ]
    captured_top_k: list[int] = []

    def fake_refresh(_db, _principal, vector_store_id, *, usage_bytes_delta=0):
        assert vector_store_id == "vs_123"
        assert usage_bytes_delta == 0

    async def fake_search(_db, _principal, req):
        captured_top_k.append(req.top_k)
        return SimpleNamespace(results=chunks[:req.top_k])

    monkeypatch.setattr(api_main, "_refresh_vector_store_activity_or_404", fake_refresh)
    monkeypatch.setattr(api_main.retrieval, "search", fake_search)
    monkeypatch.setattr(api_main, "_vector_store_file_lookup", lambda *_args, **_kwargs: {})

    first_page = asyncio.run(api_main._openai_vector_store_search_page(
        "vs_123",
        OpenAIVectorStoreSearchRequest(query="payment terms", max_num_results=2),
        principal,
        object(),
    ))
    second_page = asyncio.run(api_main._openai_vector_store_search_page(
        "vs_123",
        OpenAIVectorStoreSearchRequest(
            query="payment terms",
            max_num_results=2,
            next_page=first_page["next_page"],
        ),
        principal,
        object(),
    ))

    assert captured_top_k == [3, 5]
    assert [item["file_id"] for item in first_page["data"]] == ["doc_0", "doc_1"]
    assert first_page["has_more"] is True
    assert first_page["next_page"] is not None
    assert [item["file_id"] for item in second_page["data"]] == ["doc_2", "doc_3"]
    assert second_page["has_more"] is False
    assert second_page["next_page"] is None


def test_existing_vector_store_file_attach_refreshes_activity(monkeypatch):
    principal = Principal(tenant_id="tenant", business_instance_id="biz")
    db = _Db([{"id": "vsf_existing"}])
    refresh_calls = []

    def fake_refresh(_db, _principal, vector_store_id, *, usage_bytes_delta=0):
        refresh_calls.append((vector_store_id, usage_bytes_delta))

    monkeypatch.setattr(api_main, "_refresh_vector_store_activity_or_404", fake_refresh)

    result = api_main._link_existing_document_to_vector_store(db, principal, "vs_123", "doc_123")

    assert result == "vsf_existing"
    assert refresh_calls == [("vs_123", 0)]
    assert "SELECT id FROM vector_store_files" in db.calls[0][0]


def test_update_vector_store_returns_cached_idempotency_response(monkeypatch):
    cached = {
        "id": "vs_cached",
        "object": "vector_store",
        "name": "Cached",
        "status": "completed",
        "usage_bytes": 0,
        "bytes": 0,
        "attributes": {},
        "metadata": {},
        "file_counts": {"in_progress": 0, "completed": 0, "failed": 0, "cancelled": 0, "total": 0},
        "created_at": None,
        "description": None,
        "expires_after": None,
        "expires_at": None,
        "last_active_at": None,
    }

    def fail_update(*args, **kwargs):
        raise AssertionError("cached idempotency response should skip vector store update")

    monkeypatch.setattr(api_main, "check_idempotency", lambda *args, **kwargs: cached)
    monkeypatch.setattr(api_main.vs_repo, "update", fail_update)

    response = api_main.update_vector_store(
        "vs_cached",
        VectorStoreUpdateRequest(name="Cached"),
        Principal(tenant_id="tenant", business_instance_id="biz", scopes=["vector_stores:write"]),
        _Db([]),
        idempotency_key="idem_vs_update",
    )

    assert response == cached


def test_vector_store_list_cursors_use_stable_created_at_id_tie_breaker():
    principal = Principal(tenant_id="tenant", business_instance_id="biz")
    db = _Db([
        {"id": "vs_cursor", "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc)},
        [],
    ])

    data, has_more = VectorStoreRepository().list(
        db,
        principal,
        limit=2,
        after="vs_cursor",
        order="desc",
    )

    assert data == []
    assert has_more is False
    cursor_sql, cursor_params = db.calls[0]
    list_sql, list_params = db.calls[1]
    assert "SELECT id, created_at FROM vector_stores" in cursor_sql
    assert "AND (vs.created_at < :after_created_at OR (vs.created_at=:after_created_at AND vs.id < :after_id))" in list_sql
    assert "ORDER BY vs.created_at DESC, vs.id DESC" in list_sql
    assert cursor_params["after"] == "vs_cursor"
    assert list_params["after_id"] == "vs_cursor"


def test_vector_store_list_before_cursor_uses_stable_ascending_tie_breaker():
    principal = Principal(tenant_id="tenant", business_instance_id="biz")
    db = _Db([
        {"id": "vs_cursor", "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc)},
        [],
    ])

    data, has_more = VectorStoreRepository().list(
        db,
        principal,
        limit=2,
        before="vs_cursor",
        order="asc",
    )

    assert data == []
    assert has_more is False
    list_sql, list_params = db.calls[1]
    assert "AND (vs.created_at < :before_created_at OR (vs.created_at=:before_created_at AND vs.id < :before_id))" in list_sql
    assert "ORDER BY vs.created_at ASC, vs.id ASC" in list_sql
    assert list_params["before_id"] == "vs_cursor"


def test_delete_vector_store_returns_cached_idempotency_response(monkeypatch):
    cached = {"id": "vs_cached", "object": "vector_store.deleted", "deleted": True}

    def fail_delete(*args, **kwargs):
        raise AssertionError("cached idempotency response should skip vector store delete")

    monkeypatch.setattr(api_main, "check_idempotency", lambda *args, **kwargs: cached)
    monkeypatch.setattr(api_main.vs_repo, "delete", fail_delete)

    response = api_main.delete_vector_store(
        "vs_cached",
        Principal(tenant_id="tenant", business_instance_id="biz", scopes=["vector_stores:write"]),
        _Db([]),
        idempotency_key="idem_vs_delete",
    )

    assert response == cached


def test_update_vector_store_idempotency_key_reuse_with_changed_body_returns_409(monkeypatch):
    db = _Db([{
        "response": {"id": "vs_cached"},
        "request_fingerprint": "different-fingerprint",
        "status_code": 200,
    }])

    def fail_update(*args, **kwargs):
        raise AssertionError("mismatched idempotency key should fail before update")

    monkeypatch.setattr(api_main.vs_repo, "update", fail_update)

    with pytest.raises(HTTPException) as exc:
        api_main.update_vector_store(
            "vs_cached",
            VectorStoreUpdateRequest(name="Changed"),
            Principal(tenant_id="tenant", business_instance_id="biz", scopes=["vector_stores:write"]),
            db,
            idempotency_key="idem_vs_update",
        )

    assert exc.value.status_code == 409
    assert "different request body" in exc.value.detail
