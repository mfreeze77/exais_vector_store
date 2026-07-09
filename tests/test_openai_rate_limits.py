from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import HTTPException

from svs_api import main as api_main
from svs_common.request_controls import enforce_resource_rate_limit
from svs_common.schemas import OpenAIVectorStoreSearchRequest, Principal, VectorStoreUpdateRequest


class _Rows:
    def mappings(self):
        return self

    def first(self):
        return None

    def all(self):
        return []


class _Db:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.committed = False

    def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params or {}))
        return _Rows()

    def commit(self) -> None:
        self.committed = True


def _principal(scopes: list[str] | None = None) -> Principal:
    return Principal(
        tenant_id="tenant",
        business_instance_id="biz",
        user_id="user",
        api_key_id="key_rate",
        scopes=scopes or [
            "retrieval:read",
            "documents:write",
            "vector_stores:read",
            "vector_stores:write",
            "api_keys:write",
        ],
    )


def _rejecting_limiter(seen: list[str]):
    def reject(_db, _principal, bucket: str, *_args, **_kwargs):
        seen.append(bucket)
        raise HTTPException(status_code=429, detail=f"Rate limit exceeded for {bucket}: 1/minute")

    return reject


def _passing_limiter(seen: list[str]):
    def allow(_db, _principal, bucket: str, *_args, **_kwargs):
        seen.append(bucket)

    return allow


def _rejecting_resource_limiter(seen: list[tuple[str, str, str]]):
    def reject(_db, _principal, *, resource_id: str, bucket: str, limit_per_minute: int, resource_label: str):
        seen.append((resource_id, bucket, resource_label))
        raise HTTPException(status_code=429, detail=f"Rate limit exceeded for {resource_label} {resource_id}: {limit_per_minute}/minute")

    return reject


def test_resource_rate_limit_uses_resource_subject_and_system_bypass():
    db = _Db()
    principal = _principal(["documents:write"])

    enforce_resource_rate_limit(
        db,
        principal,
        resource_id="vs_123",
        bucket="vector_store_file_adds",
        limit_per_minute=300,
        resource_label="vector store file additions for",
    )

    assert len(db.calls) == 1
    assert db.calls[0][1]["subject_id"] == "resource:vs_123"
    assert db.calls[0][1]["bucket"] == "vector_store_file_adds"

    system_db = _Db()
    enforce_resource_rate_limit(
        system_db,
        _principal(["system"]),
        resource_id="vs_123",
        bucket="vector_store_file_adds",
        limit_per_minute=300,
        resource_label="vector store file additions for",
    )
    assert system_db.calls == []


def test_create_response_rate_limit_blocks_before_file_search(monkeypatch):
    seen: list[str] = []
    search_called = False

    async def fail_search(*_args, **_kwargs):
        nonlocal search_called
        search_called = True
        raise AssertionError("rate-limited Responses should not execute file search")

    monkeypatch.setattr(api_main, "enforce_rate_limit", _rejecting_limiter(seen))
    monkeypatch.setattr(api_main, "_openai_vector_store_search_page", fail_search)

    db = _Db()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api_main.create_response(
            {
                "model": "gpt-5.4-mini",
                "input": "Where is the evidence?",
                "tools": [{"type": "file_search", "vector_store_ids": ["vs_rate"]}],
            },
            _principal(["retrieval:read"]),
            db,
        ))

    assert exc.value.status_code == 429
    assert seen == ["responses.create"]
    assert search_called is False
    assert db.calls == []
    assert db.committed is False


def test_vector_store_search_rate_limit_blocks_before_retrieval(monkeypatch):
    seen: list[str] = []

    async def fail_search_page(*_args, **_kwargs):
        raise AssertionError("rate-limited vector-store search should not run retrieval")

    monkeypatch.setattr(api_main, "enforce_rate_limit", _rejecting_limiter(seen))
    monkeypatch.setattr(api_main, "_openai_vector_store_search_page", fail_search_page)

    db = _Db()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api_main.vector_store_search(
            "vs_rate",
            OpenAIVectorStoreSearchRequest(query="rate limited query"),
            _principal(["retrieval:read"]),
            db,
        ))

    assert exc.value.status_code == 429
    assert seen == ["vector_stores.search"]
    assert db.calls == []
    assert db.committed is False


def test_vector_store_update_rate_limit_blocks_before_idempotency_and_mutation(monkeypatch):
    seen: list[str] = []

    def fail_idempotency(*_args, **_kwargs):
        raise AssertionError("rate-limited vector-store update should not check idempotency")

    def fail_update(*_args, **_kwargs):
        raise AssertionError("rate-limited vector-store update should not mutate")

    monkeypatch.setattr(api_main, "enforce_rate_limit", _rejecting_limiter(seen))
    monkeypatch.setattr(api_main, "check_idempotency", fail_idempotency)
    monkeypatch.setattr(api_main.vs_repo, "update", fail_update)

    db = _Db()
    with pytest.raises(HTTPException) as exc:
        api_main.update_vector_store(
            "vs_rate",
            VectorStoreUpdateRequest(name="Limited"),
            _principal(["vector_stores:write"]),
            db,
            idempotency_key="idem_rate",
        )

    assert exc.value.status_code == 429
    assert seen == ["vector_stores.update"]
    assert db.calls == []
    assert db.committed is False


def test_vector_store_file_create_rate_limit_blocks_before_attach(monkeypatch):
    seen: list[str] = []

    def fail_idempotency(*_args, **_kwargs):
        raise AssertionError("rate-limited file attach should not check idempotency")

    async def fail_attach(*_args, **_kwargs):
        raise AssertionError("rate-limited file attach should not attach documents")

    monkeypatch.setattr(api_main, "enforce_rate_limit", _rejecting_limiter(seen))
    monkeypatch.setattr(api_main, "check_idempotency", fail_idempotency)
    monkeypatch.setattr(api_main, "_attach_existing_document_ids_to_vector_store", fail_attach)

    db = _Db()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api_main.attach_file(
            "vs_rate",
            {"file_id": "file_rate"},
            _principal(["documents:write"]),
            db,
            idempotency_key="idem_attach_rate",
        ))

    assert exc.value.status_code == 429
    assert seen == ["vector_store_files.create"]
    assert db.calls == []
    assert db.committed is False


def test_vector_store_file_create_per_store_rate_limit_blocks_before_idempotency(monkeypatch):
    route_seen: list[str] = []
    resource_seen: list[tuple[str, str, str]] = []

    def fail_idempotency(*_args, **_kwargs):
        raise AssertionError("per-store rate-limited file attach should not check idempotency")

    async def fail_attach(*_args, **_kwargs):
        raise AssertionError("per-store rate-limited file attach should not attach documents")

    monkeypatch.setattr(api_main, "enforce_rate_limit", _passing_limiter(route_seen))
    monkeypatch.setattr(api_main, "enforce_resource_rate_limit", _rejecting_resource_limiter(resource_seen))
    monkeypatch.setattr(api_main, "check_idempotency", fail_idempotency)
    monkeypatch.setattr(api_main, "_attach_existing_document_ids_to_vector_store", fail_attach)

    db = _Db()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api_main.attach_file(
            "vs_rate",
            {"file_id": "file_rate"},
            _principal(["documents:write"]),
            db,
            idempotency_key="idem_attach_rate",
        ))

    assert exc.value.status_code == 429
    assert route_seen == ["vector_store_files.create"]
    assert resource_seen == [("vs_rate", api_main.VECTOR_STORE_FILE_ADD_RATE_LIMIT_BUCKET, "vector store file additions for")]
    assert db.calls == []
    assert db.committed is False


def test_file_batch_create_per_store_rate_limit_blocks_before_batch_work(monkeypatch):
    route_seen: list[str] = []
    resource_seen: list[tuple[str, str, str]] = []

    def fail_idempotency(*_args, **_kwargs):
        raise AssertionError("per-store rate-limited file batch should not check idempotency")

    async def fail_attach(*_args, **_kwargs):
        raise AssertionError("per-store rate-limited file batch should not attach documents")

    def fail_enqueue(*_args, **_kwargs):
        raise AssertionError("per-store rate-limited file batch should not enqueue inline ingests")

    monkeypatch.setattr(api_main, "enforce_rate_limit", _passing_limiter(route_seen))
    monkeypatch.setattr(api_main, "enforce_resource_rate_limit", _rejecting_resource_limiter(resource_seen))
    monkeypatch.setattr(api_main, "check_idempotency", fail_idempotency)
    monkeypatch.setattr(api_main, "_attach_existing_document_ids_to_vector_store", fail_attach)
    monkeypatch.setattr(api_main.ingestion, "enqueue", fail_enqueue)

    db = _Db()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api_main.create_file_batch(
            "vs_rate",
            {"file_ids": ["file_rate"]},
            _principal(["documents:write"]),
            db,
            idempotency_key="idem_batch_rate",
        ))

    assert exc.value.status_code == 429
    assert route_seen == ["file_batches.create"]
    assert resource_seen == [("vs_rate", api_main.VECTOR_STORE_FILE_ADD_RATE_LIMIT_BUCKET, "vector store file additions for")]
    assert db.calls == []
    assert db.committed is False


def test_admin_api_key_create_uses_admin_rate_limit_bucket(monkeypatch):
    seen: list[str] = []

    def fail_create_key(*_args, **_kwargs):
        raise AssertionError("rate-limited API-key create should not create a key")

    monkeypatch.setattr(api_main, "enforce_rate_limit", _rejecting_limiter(seen))
    monkeypatch.setattr(api_main, "create_api_key", fail_create_key)

    db = _Db()
    with pytest.raises(HTTPException) as exc:
        api_main.create_instance_api_key(
            label="limited",
            scopes="retrieval:read",
            principal=_principal(["api_keys:write"]),
            db=db,
        )

    assert exc.value.status_code == 429
    assert seen == ["admin.api_keys.create"]
    assert db.calls == []
    assert db.committed is False
