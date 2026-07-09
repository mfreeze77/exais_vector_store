from __future__ import annotations

import pytest
from fastapi import HTTPException

import svs_common.vector_store_repo as vector_store_repo
from svs_api import main as api_main
from svs_common.schemas import Principal
from svs_common.vector_store_repo import VectorStoreRepository


class _Rows:
    def __init__(self, *, row=None, rows=None, rowcount: int = 1):
        self.row = row
        self.rows = list(rows or [])
        self.rowcount = rowcount

    def mappings(self):
        return self

    def first(self):
        return self.row

    def all(self):
        return self.rows


class _Db:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls: list[tuple[str, dict]] = []
        self.committed = False

    def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params or {}))
        if self.results:
            result = self.results.pop(0)
            if isinstance(result, _Rows):
                return result
            if isinstance(result, list):
                return _Rows(rows=result)
            return _Rows(row=result)
        return _Rows(row=None, rows=[], rowcount=0)

    def commit(self):
        self.committed = True


def _principal(scopes: list[str] | None = None) -> Principal:
    return Principal(
        tenant_id="tenant_a",
        business_instance_id="biz_a",
        user_id="user_a",
        api_key_id="key_a",
        scopes=scopes or ["retrieval:read", "vector_stores:read", "vector_stores:write"],
    )


@pytest.fixture(autouse=True)
def _disable_route_rate_limits(monkeypatch):
    monkeypatch.setattr(api_main, "enforce_rate_limit", lambda *args, **kwargs: None)


def _compact(sql: str) -> str:
    return " ".join(sql.split())


def test_openai_response_lookup_fails_closed_to_principal_scope():
    db = _Db()

    with pytest.raises(HTTPException) as exc:
        api_main._get_openai_response_row(db, _principal(), "resp_shared")

    assert exc.value.status_code == 404
    sql, params = db.calls[0]
    sql = _compact(sql)
    assert "WHERE id=:id AND tenant_id=:tenant_id AND business_instance_id=:biz_id" in sql
    assert params == {"id": "resp_shared", "tenant_id": "tenant_a", "biz_id": "biz_a"}


def test_openai_response_delete_mutates_only_principal_scope():
    db = _Db(results=[
        {"id": "resp_123", "response": {}, "input_items": [], "deleted_at": None},
        _Rows(rowcount=1),
    ])

    payload = api_main.delete_response("resp_123", principal=_principal(["retrieval:read"]), db=db)

    update_sql, update_params = db.calls[1]
    update_sql = _compact(update_sql)
    assert payload == {"id": "resp_123", "object": "response", "deleted": True}
    assert "UPDATE openai_responses SET" in update_sql
    assert "WHERE id=:id AND tenant_id=:tenant_id AND business_instance_id=:biz_id" in update_sql
    assert update_params == {"id": "resp_123", "tenant_id": "tenant_a", "biz_id": "biz_a"}
    assert db.committed is True


def test_openai_file_lookup_uses_principal_scope_for_public_file_ids():
    db = _Db()

    row = api_main._get_openai_file_row(db, _principal(), "file_shared")

    assert row is None
    sql, params = db.calls[0]
    sql = _compact(sql)
    assert "WHERE d.tenant_id=:tenant_id AND d.business_instance_id=:biz_id" in sql
    assert "dv.metadata #>> '{attributes,_openai_file_id}' = :file_id" in sql
    assert params == {"tenant_id": "tenant_a", "biz_id": "biz_a", "file_id": "file_shared"}


def test_vector_store_repo_list_get_and_delete_are_principal_scoped(monkeypatch):
    repo = VectorStoreRepository()
    principal = _principal(["vector_stores:read", "vector_stores:write"])

    list_db = _Db(results=[None, []])
    data, has_more = repo.list(list_db, principal, limit=5, after="vs_cursor")

    assert data == []
    assert has_more is False
    cursor_sql, cursor_params = list_db.calls[0]
    list_sql, list_params = list_db.calls[1]
    assert "WHERE id=:after AND tenant_id=:tenant_id AND business_instance_id=:biz_id" in _compact(cursor_sql)
    assert "WHERE vs.tenant_id=:tenant_id AND vs.business_instance_id=:biz_id" in _compact(list_sql)
    assert cursor_params["tenant_id"] == "tenant_a"
    assert cursor_params["biz_id"] == "biz_a"
    assert list_params["tenant_id"] == "tenant_a"
    assert list_params["biz_id"] == "biz_a"

    get_db = _Db()
    assert repo.get(get_db, principal, "vs_shared") is None
    get_sql, get_params = get_db.calls[0]
    assert "WHERE vs.id=:id AND vs.tenant_id=:tenant_id AND vs.business_instance_id=:biz_id" in _compact(get_sql)
    assert get_params == {"id": "vs_shared", "tenant_id": "tenant_a", "biz_id": "biz_a"}

    monkeypatch.setattr(vector_store_repo, "enqueue_purge_stale_vectors", lambda *args, **kwargs: "job_test")
    delete_db = _Db(results=[
        {"id": "vs_shared"},
        _Rows(rowcount=1),
        _Rows(rowcount=0),
        _Rows(rowcount=1),
    ])
    assert repo.delete(delete_db, principal, "vs_shared") is True

    select_sql, select_params = delete_db.calls[0]
    update_sql, update_params = delete_db.calls[1]
    chunk_sql, chunk_params = delete_db.calls[3]
    assert "WHERE id=:id AND tenant_id=:tenant_id AND business_instance_id=:biz_id" in _compact(select_sql)
    assert "WHERE id=:id AND tenant_id=:tenant_id AND business_instance_id=:biz_id" in _compact(update_sql)
    assert "WHERE vector_store_id=:id AND tenant_id=:tenant_id AND business_instance_id=:biz_id" in _compact(chunk_sql)
    assert select_params["tenant_id"] == update_params["tenant_id"] == chunk_params["tenant_id"] == "tenant_a"
    assert select_params["biz_id"] == update_params["biz_id"] == chunk_params["biz_id"] == "biz_a"


def test_vector_store_file_helpers_resolve_public_ids_inside_principal_scope():
    principal = _principal(["vector_stores:read"])

    row_db = _Db()
    assert api_main._vector_store_file_row(row_db, principal, "vs_shared", "file_shared") is None
    row_sql, row_params = row_db.calls[0]
    row_sql = _compact(row_sql)
    assert "WHERE f.vector_store_id=:vs_id AND f.tenant_id=:tenant_id AND f.business_instance_id=:biz_id" in row_sql
    assert "f.attributes->>'attached_from_file_id' = :file_id" in row_sql
    assert "dv.metadata #>> '{attributes,_openai_file_id}' = :file_id" in row_sql
    assert row_params == {
        "file_id": "file_shared",
        "vs_id": "vs_shared",
        "tenant_id": "tenant_a",
        "biz_id": "biz_a",
    }

    list_db = _Db(results=[None, []])
    rows, has_more = api_main._list_vector_store_file_rows(
        list_db,
        principal,
        "vs_shared",
        after="file_cursor",
        batch_id="vsfb_shared",
    )

    assert rows == []
    assert has_more is False
    cursor_sql, cursor_params = list_db.calls[0]
    list_sql, list_params = list_db.calls[1]
    cursor_sql = _compact(cursor_sql)
    list_sql = _compact(list_sql)
    assert "f.tenant_id=:tenant_id" in cursor_sql
    assert "f.business_instance_id=:biz_id" in cursor_sql
    assert "AND f.file_batch_id=:batch_id" in cursor_sql
    assert "WHERE f.tenant_id=:tenant_id AND f.business_instance_id=:biz_id AND f.vector_store_id=:vs_id" in list_sql
    assert "f.file_batch_id=:batch_id" in list_sql
    assert cursor_params["tenant_id"] == list_params["tenant_id"] == "tenant_a"
    assert cursor_params["biz_id"] == list_params["biz_id"] == "biz_a"
    assert cursor_params["batch_id"] == list_params["batch_id"] == "vsfb_shared"


def test_existing_file_attach_cannot_link_document_outside_principal_scope():
    db = _Db(results=[None, None])

    with pytest.raises(HTTPException) as exc:
        api_main._link_existing_document_to_vector_store(db, _principal(), "vs_a", "file_other")

    assert exc.value.status_code == 404
    existing_sql, existing_params = db.calls[0]
    doc_sql, doc_params = db.calls[1]
    assert "WHERE tenant_id=:tenant_id AND business_instance_id=:biz_id" in _compact(existing_sql)
    assert "WHERE d.id=:doc_id AND d.tenant_id=:tenant_id AND d.business_instance_id=:biz_id" in _compact(doc_sql)
    assert existing_params["tenant_id"] == doc_params["tenant_id"] == "tenant_a"
    assert existing_params["biz_id"] == doc_params["biz_id"] == "biz_a"
