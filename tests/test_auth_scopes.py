import json

import pytest
from fastapi import HTTPException
from svs_api import main as api_main
from svs_common import auth as auth_mod
from svs_common.auth import (
    DEFAULT_API_KEY_SCOPES,
    api_key_metadata_from_row,
    create_api_key,
    ensure_scope,
    get_api_key,
    list_api_keys,
    openai_admin_api_key_create_response,
    openai_admin_api_key_from_metadata,
    openai_project_api_key_from_metadata,
    principal_has_scope,
    revoke_api_key,
    resolve_api_key_principal,
)
from svs_common.schemas import Principal


class _Rows:
    def __init__(self, rows=None, row=None):
        self.rows = rows or []
        self.row = row

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.row


class _Db:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls = []
        self.committed = False

    def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params or {}))
        if self.results:
            result = self.results.pop(0)
            if isinstance(result, list):
                return _Rows(rows=result)
            return _Rows(row=result)
        return _Rows()

    def commit(self):
        self.committed = True


def p(scopes):
    return Principal(tenant_id="t", business_instance_id="b", scopes=scopes)


@pytest.fixture(autouse=True)
def _disable_route_rate_limits(monkeypatch):
    monkeypatch.setattr(api_main, "enforce_rate_limit", lambda *args, **kwargs: None)


def test_exact_scope_required():
    assert principal_has_scope(p(["documents:write"]), "documents:write")
    assert not principal_has_scope(p(["documents:read"]), "documents:write")


def test_namespace_wildcard_scope():
    assert principal_has_scope(p(["vector_stores:*"]), "vector_stores:write")


def test_ensure_scope_blocks_missing():
    with pytest.raises(HTTPException):
        ensure_scope(p(["retrieval:read"]), "documents:write")


def test_create_api_key_reports_default_effective_scopes(monkeypatch):
    monkeypatch.setattr(auth_mod, "generate_api_key", lambda: "svs_live_test_secret")
    db = _Db()
    principal = Principal(tenant_id="tenant", business_instance_id="biz", user_id="user", max_security_level=3)

    result = create_api_key(db, principal, "default")

    assert result["api_key"] == "svs_live_test_secret"
    assert result["scopes"] == DEFAULT_API_KEY_SCOPES
    assert result["max_security_level"] == 3
    sql, params = db.calls[0]
    assert "INSERT INTO api_keys" in sql
    assert params["scopes"] == DEFAULT_API_KEY_SCOPES
    assert params["key_hash"] != "svs_live_test_secret"
    assert params["expires_at"] is None


def test_create_api_key_accepts_future_expiration(monkeypatch):
    monkeypatch.setattr(auth_mod, "generate_api_key", lambda: "svs_live_expiring_secret")
    monkeypatch.setattr(auth_mod.time, "time", lambda: 1710000000)
    db = _Db()
    principal = Principal(tenant_id="tenant", business_instance_id="biz", user_id="user", max_security_level=3)

    result = create_api_key(db, principal, "expiring", ["retrieval:read"], 2, expires_at=1710003600)

    assert result == {
        "id": result["id"],
        "api_key": "svs_live_expiring_secret",
        "label": "expiring",
        "scopes": ["retrieval:read"],
        "max_security_level": 2,
        "expires_at": 1710003600,
    }
    sql, params = db.calls[0]
    assert "expires_at" in sql
    assert "to_timestamp(CAST(:expires_at AS double precision))" in sql
    assert params["expires_at"] == 1710003600


def test_create_api_key_rejects_past_expiration(monkeypatch):
    monkeypatch.setattr(auth_mod.time, "time", lambda: 1710000000)
    monkeypatch.setattr(auth_mod, "generate_api_key", lambda: pytest.fail("expired key should fail before secret generation"))
    db = _Db()
    principal = Principal(tenant_id="tenant", business_instance_id="biz", user_id="user", max_security_level=3)

    with pytest.raises(HTTPException) as exc:
        create_api_key(db, principal, "expired", expires_at=1709999999)

    assert exc.value.status_code == 422
    assert "future Unix timestamp" in exc.value.detail
    assert db.calls == []


def test_create_api_key_route_passes_expiration_and_commits(monkeypatch):
    seen = {}

    def fake_create_key(db, principal, label, scopes, max_security_level, expires_at):
        seen["args"] = {
            "db": db,
            "principal": principal,
            "label": label,
            "scopes": scopes,
            "max_security_level": max_security_level,
            "expires_at": expires_at,
        }
        return {
            "id": "key_route",
            "api_key": "svs_live_route_secret",
            "label": label,
            "scopes": scopes,
            "max_security_level": max_security_level,
            "expires_at": expires_at,
        }

    monkeypatch.setattr(api_main, "create_api_key", fake_create_key)
    db = _Db()
    principal = Principal(tenant_id="tenant", business_instance_id="biz", scopes=["api_keys:write"])

    result = api_main.create_instance_api_key(
        label="route",
        scopes="retrieval:read, vector_stores:read",
        max_security_level=4,
        expires_at=1710003600,
        principal=principal,
        db=db,
    )

    assert result["expires_at"] == 1710003600
    assert seen["args"]["scopes"] == ["retrieval:read", "vector_stores:read"]
    assert seen["args"]["max_security_level"] == 4
    assert seen["args"]["expires_at"] == 1710003600
    assert db.committed is True


def test_api_key_metadata_payload_never_exposes_secret_material():
    payload = api_key_metadata_from_row({
        "id": "key_123",
        "label": "retrieval",
        "scopes": ["retrieval:read"],
        "max_security_level": 2,
        "status": "active",
        "created_at": 1710000000,
        "last_used_at": None,
        "expires_at": None,
        "key_hash": "must-not-leak",
        "api_key": "svs_live_must_not_leak",
    })

    assert payload == {
        "id": "key_123",
        "object": "api_key",
        "label": "retrieval",
        "scopes": ["retrieval:read"],
        "max_security_level": 2,
        "status": "active",
        "created_at": 1710000000,
    }


def test_openai_project_api_key_formatter_is_redacted_and_strict():
    payload = openai_project_api_key_from_metadata(
        {
            "id": "key_123456",
            "label": "retrieval",
            "scopes": ["retrieval:read"],
            "max_security_level": 2,
            "status": "active",
            "created_at": 1710000000,
            "last_used_at": None,
            "expires_at": None,
            "key_hash": "must-not-leak",
            "api_key": "svs_live_must_not_leak",
        },
        owner_user_id="user_abc",
    )
    serialized = json.dumps(payload, sort_keys=True)

    assert payload == {
        "object": "organization.project.api_key",
        "redacted_value": "svs_live_...123456",
        "name": "retrieval",
        "created_at": 1710000000,
        "id": "key_123456",
        "owner": {"type": "user", "user": {"id": "user_abc"}},
    }
    assert "key_hash" not in serialized
    assert "must-not-leak" not in serialized
    assert "svs_live_must_not_leak" not in serialized


def test_openai_admin_api_key_formatter_is_redacted_and_strict():
    payload = openai_admin_api_key_from_metadata(
        {
            "id": "key_abcdef",
            "label": "org admin",
            "scopes": ["api_keys:write"],
            "max_security_level": 5,
            "status": "active",
            "created_at": 1710000000,
            "expires_at": 1710003600,
            "last_used_at": 1710000100,
            "key_hash": "must-not-leak",
            "api_key": "svs_live_must_not_leak",
        },
        owner_user_id="user_owner",
    )
    serialized = json.dumps(payload, sort_keys=True)

    assert payload == {
        "object": "organization.admin_api_key",
        "id": "key_abcdef",
        "name": "org admin",
        "redacted_value": "svs_live_...abcdef",
        "created_at": 1710000000,
        "expires_at": 1710003600,
        "last_used_at": 1710000100,
        "owner": {
            "type": "user",
            "object": "organization.user",
            "id": "user_owner",
            "role": "owner",
        },
    }
    assert "key_hash" not in serialized
    assert "must-not-leak" not in serialized
    assert "svs_live_must_not_leak" not in serialized
    assert "scopes" not in serialized
    assert "max_security_level" not in serialized


def test_openai_admin_api_key_create_response_exposes_value_once():
    payload = openai_admin_api_key_create_response(
        {
            "id": "key_created",
            "api_key": "svs_live_created_secret",
            "label": "created admin",
            "scopes": ["api_keys:write"],
            "max_security_level": 4,
            "expires_at": 1710003600,
        },
        created_at=1710000000,
        owner_user_id="user_owner",
    )
    serialized = json.dumps(payload, sort_keys=True)

    assert payload == {
        "object": "organization.admin_api_key",
        "id": "key_created",
        "name": "created admin",
        "redacted_value": "svs_live_...reated",
        "created_at": 1710000000,
        "expires_at": 1710003600,
        "owner": {
            "type": "user",
            "object": "organization.user",
            "id": "user_owner",
            "role": "owner",
        },
        "value": "svs_live_created_secret",
    }
    assert "api_key" not in payload
    assert "key_hash" not in serialized
    assert "scopes" not in serialized
    assert "max_security_level" not in serialized


def test_list_api_keys_returns_metadata_page_without_hashes():
    principal = Principal(tenant_id="tenant", business_instance_id="biz")
    db = _Db(results=[[
        {
            "id": "key_2",
            "label": "second",
            "scopes": ["retrieval:read"],
            "max_security_level": 3,
            "status": "active",
            "created_at": 1710000002,
            "last_used_at": 1710000010,
            "expires_at": None,
        },
        {
            "id": "key_1",
            "label": "first",
            "scopes": ["documents:write"],
            "max_security_level": 2,
            "status": "revoked",
            "created_at": 1710000001,
            "last_used_at": None,
            "expires_at": None,
        },
    ]])

    data, has_more = list_api_keys(db, principal, limit=1)

    assert has_more is True
    assert data == [{
        "id": "key_2",
        "object": "api_key",
        "label": "second",
        "scopes": ["retrieval:read"],
        "max_security_level": 3,
        "status": "active",
        "created_at": 1710000002,
        "last_used_at": 1710000010,
    }]
    sql, params = db.calls[0]
    assert "key_hash" not in sql
    assert "business_instance_id IS NOT DISTINCT FROM :biz_id" in sql
    assert params["limit"] == 2


def test_list_api_keys_can_filter_active_for_openai_project_aliases():
    principal = Principal(tenant_id="tenant", business_instance_id="biz")
    db = _Db(results=[[{
        "id": "key_active",
        "label": "active",
        "scopes": ["retrieval:read"],
        "max_security_level": 2,
        "status": "active",
        "created_at": 1710000001,
        "last_used_at": None,
        "expires_at": None,
    }]])

    data, has_more = list_api_keys(db, principal, limit=20, status="active")

    assert has_more is False
    assert data[0]["id"] == "key_active"
    sql, params = db.calls[0]
    assert "AND status=:status" in sql
    assert params["status"] == "active"


def test_list_api_keys_after_cursor_uses_created_at_and_id_tie_breaker():
    principal = Principal(tenant_id="tenant", business_instance_id="biz")
    db = _Db(results=[
        {"id": "key_anchor", "created_at": "2026-07-08T12:00:00Z"},
        [{
            "id": "key_before_anchor",
            "label": "before",
            "scopes": ["retrieval:read"],
            "max_security_level": 2,
            "status": "active",
            "created_at": 1710000001,
            "last_used_at": None,
            "expires_at": None,
        }],
    ])

    data, has_more = list_api_keys(db, principal, limit=2, after="key_anchor")

    assert has_more is False
    assert data[0]["id"] == "key_before_anchor"
    cursor_sql, cursor_params = db.calls[0]
    assert "SELECT id, created_at" in cursor_sql
    assert "business_instance_id IS NOT DISTINCT FROM :biz_id" in cursor_sql
    assert cursor_params["after"] == "key_anchor"
    list_sql, list_params = db.calls[1]
    assert "AND (created_at < :after_created_at OR (created_at=:after_created_at AND id < :after_id))" in list_sql
    assert "ORDER BY created_at DESC, id DESC" in list_sql


def test_list_api_keys_admin_order_asc_uses_forward_cursor():
    principal = Principal(tenant_id="tenant", business_instance_id="biz")
    db = _Db(results=[
        {"id": "key_anchor", "created_at": "2026-07-08T12:00:00Z"},
        [{
            "id": "key_after_anchor",
            "label": "after",
            "scopes": ["api_keys:read"],
            "max_security_level": 2,
            "status": "active",
            "created_at": 1710000002,
            "last_used_at": None,
            "expires_at": None,
        }],
    ])

    data, has_more = list_api_keys(db, principal, limit=2, after="key_anchor", status="active", order="asc")

    assert has_more is False
    assert data[0]["id"] == "key_after_anchor"
    cursor_sql, cursor_params = db.calls[0]
    assert "AND status=:status" in cursor_sql
    assert cursor_params["status"] == "active"
    list_sql, list_params = db.calls[1]
    assert "AND (created_at > :after_created_at OR (created_at=:after_created_at AND id > :after_id))" in list_sql
    assert "ORDER BY created_at ASC, id ASC" in list_sql
    assert list_params["status"] == "active"
    assert list_params["after_created_at"] == "2026-07-08T12:00:00Z"
    assert list_params["after_id"] == "key_anchor"
    assert list_params["limit"] == 3


def test_get_api_key_returns_tenant_business_scoped_metadata_without_hashes():
    principal = Principal(tenant_id="tenant", business_instance_id="biz")
    db = _Db(results=[{
        "id": "key_123",
        "label": "retrieval",
        "scopes": ["retrieval:read"],
        "max_security_level": 2,
        "status": "active",
        "created_at": 1710000000,
        "last_used_at": None,
        "expires_at": None,
    }])

    payload = get_api_key(db, principal, "key_123", status="active")

    assert payload == {
        "id": "key_123",
        "object": "api_key",
        "label": "retrieval",
        "scopes": ["retrieval:read"],
        "max_security_level": 2,
        "status": "active",
        "created_at": 1710000000,
    }
    sql, params = db.calls[0]
    assert "key_hash" not in sql
    assert "business_instance_id IS NOT DISTINCT FROM :biz_id" in sql
    assert "AND status=:status" in sql
    assert params["id"] == "key_123"
    assert params["status"] == "active"


def test_revoke_api_key_scopes_update_to_tenant_business():
    principal = Principal(tenant_id="tenant", business_instance_id="biz")
    db = _Db(results=[{
        "id": "key_123",
        "label": "old",
        "scopes": ["retrieval:read"],
        "max_security_level": 1,
        "status": "revoked",
        "created_at": 1710000000,
        "last_used_at": None,
        "expires_at": None,
    }])

    payload = revoke_api_key(db, principal, "key_123")

    assert payload["status"] == "revoked"
    sql, params = db.calls[0]
    assert "SET status='revoked'" in sql
    assert "business_instance_id IS NOT DISTINCT FROM :biz_id" in sql
    assert params["id"] == "key_123"


def test_list_api_key_route_requires_read_or_write_scope():
    db = _Db(results=[[]])
    principal = Principal(tenant_id="tenant", business_instance_id="biz", scopes=["api_keys:read"])

    page = api_main.list_instance_api_keys(limit=20, principal=principal, db=db)

    assert page == {"object": "list", "data": [], "first_id": None, "last_id": None, "has_more": False}

    with pytest.raises(HTTPException) as exc:
        api_main.list_instance_api_keys(
            limit=20,
            principal=Principal(tenant_id="tenant", business_instance_id="biz", scopes=["retrieval:read"]),
            db=_Db(),
        )
    assert exc.value.status_code == 403


def test_list_api_key_route_uses_openai_default_limit_and_after_cursor(monkeypatch):
    seen = {}

    def fake_list_keys(db, principal, limit, *, after):
        seen["db"] = db
        seen["principal"] = principal
        seen["limit"] = limit
        seen["after"] = after
        return ([{"id": "key_after", "object": "api_key"}], False)

    monkeypatch.setattr(api_main, "list_api_keys", fake_list_keys)
    db = _Db()
    principal = Principal(tenant_id="tenant", business_instance_id="biz", scopes=["api_keys:read"])

    page = api_main.list_instance_api_keys(after="key_anchor", principal=principal, db=db)

    assert page == {
        "object": "list",
        "data": [{"id": "key_after", "object": "api_key"}],
        "first_id": "key_after",
        "last_id": "key_after",
        "has_more": False,
    }
    assert seen == {"db": db, "principal": principal, "limit": 20, "after": "key_anchor"}


def test_list_project_api_keys_returns_openai_shape_and_active_filter(monkeypatch):
    seen = {}

    def fake_list_keys(db, principal, limit, *, after, status):
        seen["db"] = db
        seen["principal"] = principal
        seen["limit"] = limit
        seen["after"] = after
        seen["status"] = status
        return ([{
            "id": "key_123456",
            "object": "api_key",
            "label": "retrieval",
            "status": "active",
            "created_at": 1710000000,
        }], False)

    monkeypatch.setattr(api_main, "list_api_keys", fake_list_keys)
    db = _Db()
    principal = Principal(
        tenant_id="tenant",
        business_instance_id="proj_abc",
        user_id="user_abc",
        scopes=["api_keys:read"],
    )

    page = api_main.list_project_api_keys("proj_abc", after="key_anchor", principal=principal, db=db)

    assert page == {
        "object": "list",
        "data": [{
            "object": "organization.project.api_key",
            "redacted_value": "svs_live_...123456",
            "name": "retrieval",
            "created_at": 1710000000,
            "id": "key_123456",
            "owner": {"type": "user", "user": {"id": "user_abc"}},
        }],
        "first_id": "key_123456",
        "last_id": "key_123456",
        "has_more": False,
    }
    assert seen == {"db": db, "principal": principal, "limit": 20, "after": "key_anchor", "status": "active"}


def test_list_admin_api_keys_returns_openai_shape_active_filter_and_order(monkeypatch):
    seen = {}

    def fake_list_keys(db, principal, limit, *, after, status, order):
        seen["db"] = db
        seen["principal"] = principal
        seen["limit"] = limit
        seen["after"] = after
        seen["status"] = status
        seen["order"] = order
        return ([{
            "id": "key_abcdef",
            "object": "api_key",
            "label": "org admin",
            "status": "active",
            "created_at": 1710000000,
            "last_used_at": 1710000100,
            "expires_at": 1710003600,
        }], False)

    monkeypatch.setattr(api_main, "list_api_keys", fake_list_keys)
    db = _Db()
    principal = Principal(
        tenant_id="tenant",
        business_instance_id="biz",
        user_id="user_owner",
        scopes=["api_keys:read"],
    )

    page = api_main.list_admin_api_keys(after="key_anchor", order="desc", principal=principal, db=db)

    assert page == {
        "object": "list",
        "data": [{
            "object": "organization.admin_api_key",
            "id": "key_abcdef",
            "name": "org admin",
            "redacted_value": "svs_live_...abcdef",
            "created_at": 1710000000,
            "expires_at": 1710003600,
            "last_used_at": 1710000100,
            "owner": {
                "type": "user",
                "object": "organization.user",
                "id": "user_owner",
                "role": "owner",
            },
        }],
        "first_id": "key_abcdef",
        "last_id": "key_abcdef",
        "has_more": False,
    }
    assert seen == {
        "db": db,
        "principal": principal,
        "limit": 20,
        "after": "key_anchor",
        "status": "active",
        "order": "desc",
    }


def test_create_admin_api_key_returns_openai_value_once_and_inherits_principal_scope(monkeypatch):
    seen = {}

    def fake_create_key(db, principal, label, scopes, max_security_level, expires_at):
        seen["db"] = db
        seen["principal"] = principal
        seen["label"] = label
        seen["scopes"] = scopes
        seen["max_security_level"] = max_security_level
        seen["expires_at"] = expires_at
        return {
            "id": "key_created",
            "api_key": "svs_live_created_secret",
            "label": label,
            "scopes": scopes,
            "max_security_level": max_security_level,
            "expires_at": expires_at,
        }

    monkeypatch.setattr(api_main, "create_api_key", fake_create_key)
    monkeypatch.setattr(api_main.time, "time", lambda: 1710000000)
    db = _Db()
    principal = Principal(
        tenant_id="tenant",
        business_instance_id="biz",
        user_id="user_owner",
        scopes=["api_keys:write", "retrieval:read", "vector_stores:read"],
        max_security_level=4,
    )

    payload = api_main.create_admin_api_key(
        api_main.OpenAIAdminApiKeyCreateRequest(name="  Created Admin  ", expires_in_seconds=3600),
        principal=principal,
        db=db,
    )

    assert payload == {
        "object": "organization.admin_api_key",
        "id": "key_created",
        "name": "Created Admin",
        "redacted_value": "svs_live_...reated",
        "created_at": 1710000000,
        "expires_at": 1710003600,
        "owner": {
            "type": "user",
            "object": "organization.user",
            "id": "user_owner",
            "role": "owner",
        },
        "value": "svs_live_created_secret",
    }
    assert seen == {
        "db": db,
        "principal": principal,
        "label": "Created Admin",
        "scopes": ["api_keys:write", "retrieval:read", "vector_stores:read"],
        "max_security_level": 4,
        "expires_at": 1710003600,
    }
    assert "api_key" not in payload
    assert "scopes" not in payload
    assert "max_security_level" not in payload
    assert db.committed is True


def test_retrieve_admin_api_key_returns_openai_shape(monkeypatch):
    seen = {}

    def fake_get_key(db, principal, api_key_id, *, status):
        seen["db"] = db
        seen["principal"] = principal
        seen["api_key_id"] = api_key_id
        seen["status"] = status
        return {
            "id": "key_fedcba",
            "object": "api_key",
            "label": "admin",
            "status": "active",
            "created_at": 1710000000,
            "last_used_at": 1710000100,
        }

    monkeypatch.setattr(api_main, "get_api_key", fake_get_key)
    db = _Db()
    principal = Principal(
        tenant_id="tenant",
        business_instance_id="biz",
        user_id="user_owner",
        scopes=["api_keys:read"],
    )

    payload = api_main.retrieve_admin_api_key("key_fedcba", principal=principal, db=db)

    assert payload == {
        "object": "organization.admin_api_key",
        "id": "key_fedcba",
        "name": "admin",
        "redacted_value": "svs_live_...fedcba",
        "created_at": 1710000000,
        "last_used_at": 1710000100,
        "owner": {
            "type": "user",
            "object": "organization.user",
            "id": "user_owner",
            "role": "owner",
        },
    }
    assert seen == {"db": db, "principal": principal, "api_key_id": "key_fedcba", "status": "active"}


def test_delete_admin_api_key_returns_openai_deleted_shape_without_metadata():
    principal = Principal(tenant_id="tenant", business_instance_id="biz", scopes=["api_keys:write"])
    db = _Db(results=[{
        "id": "key_123",
        "label": "old",
        "scopes": ["api_keys:read"],
        "max_security_level": 1,
        "status": "revoked",
        "created_at": 1710000000,
        "last_used_at": None,
        "expires_at": None,
    }])

    result = api_main.delete_admin_api_key("key_123", principal=principal, db=db)

    assert result == {"id": "key_123", "object": "organization.admin_api_key.deleted", "deleted": True}
    assert "data" not in result
    assert db.committed is True


def test_list_project_api_keys_rejects_cross_project_alias(monkeypatch):
    monkeypatch.setattr(api_main, "list_api_keys", lambda *args, **kwargs: pytest.fail("cross-project list must fail before lookup"))
    principal = Principal(tenant_id="tenant", business_instance_id="proj_abc", scopes=["api_keys:read"])

    with pytest.raises(HTTPException) as exc:
        api_main.list_project_api_keys("proj_other", principal=principal, db=_Db())

    assert exc.value.status_code == 404
    assert "Project not found" in exc.value.detail


def test_retrieve_project_api_key_returns_openai_shape(monkeypatch):
    seen = {}

    def fake_get_key(db, principal, api_key_id, *, status):
        seen["db"] = db
        seen["principal"] = principal
        seen["api_key_id"] = api_key_id
        seen["status"] = status
        return {
            "id": "key_654321",
            "object": "api_key",
            "label": "admin",
            "status": "active",
            "created_at": 1710000000,
            "last_used_at": 1710000100,
        }

    monkeypatch.setattr(api_main, "get_api_key", fake_get_key)
    db = _Db()
    principal = Principal(
        tenant_id="tenant",
        business_instance_id="proj_abc",
        user_id="user_abc",
        scopes=["api_keys:read"],
    )

    payload = api_main.retrieve_project_api_key("proj_abc", "key_654321", principal=principal, db=db)

    assert payload == {
        "object": "organization.project.api_key",
        "redacted_value": "svs_live_...654321",
        "name": "admin",
        "created_at": 1710000000,
        "last_used_at": 1710000100,
        "id": "key_654321",
        "owner": {"type": "user", "user": {"id": "user_abc"}},
    }
    assert seen == {"db": db, "principal": principal, "api_key_id": "key_654321", "status": "active"}


def test_delete_project_api_key_returns_openai_deleted_shape_without_metadata():
    principal = Principal(tenant_id="tenant", business_instance_id="proj_abc", scopes=["api_keys:write"])
    db = _Db(results=[{
        "id": "key_123",
        "label": "old",
        "scopes": ["retrieval:read"],
        "max_security_level": 1,
        "status": "revoked",
        "created_at": 1710000000,
        "last_used_at": None,
        "expires_at": None,
    }])

    result = api_main.delete_project_api_key("proj_abc", "key_123", principal=principal, db=db)

    assert result == {"id": "key_123", "object": "organization.project.api_key.deleted", "deleted": True}
    assert "data" not in result
    assert db.committed is True


def test_revoke_api_key_route_does_not_return_raw_secret_or_hash():
    principal = Principal(tenant_id="tenant", business_instance_id="biz", scopes=["api_keys:write"])
    db = _Db(results=[{
        "id": "key_123",
        "label": "old",
        "scopes": ["retrieval:read"],
        "max_security_level": 1,
        "status": "revoked",
        "created_at": 1710000000,
        "last_used_at": None,
        "expires_at": None,
    }])

    result = api_main.revoke_instance_api_key("key_123", principal=principal, db=db)

    assert result["deleted"] is True
    assert result["data"]["status"] == "revoked"
    assert "key_hash" not in result["data"]
    assert "api_key" not in result["data"]
    assert db.committed is True


def test_resolve_api_key_principal_filters_inactive_or_revoked_keys():
    db = _Db()

    with pytest.raises(HTTPException) as exc:
        resolve_api_key_principal(db, "Bearer svs_live_revoked")

    assert exc.value.status_code == 401
    assert "Invalid or expired API key" in exc.value.detail
    lookup_sql = db.calls[1][0]
    assert "status='active'" in lookup_sql
    assert "(expires_at IS NULL OR expires_at > now())" in lookup_sql
