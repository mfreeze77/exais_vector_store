from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from svs_api import main as api_main


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


class _SessionDb:
    def __init__(self, api_key_row=None, group_slugs=None):
        self.api_key_row = api_key_row
        self.group_slugs = list(group_slugs or [])
        self.calls = []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.calls.append((sql, params or {}))
        if "FROM api_keys" in sql and "WHERE key_hash=:key_hash" in sql:
            return _Rows(row=self.api_key_row)
        if "FROM group_memberships" in sql:
            return _Rows(rows=[{"slug": slug} for slug in self.group_slugs])
        if "FROM users" in sql and "WHERE id=:user_id" in sql and self.api_key_row and self.api_key_row.get("user_id"):
            # WAVE-125: a bound user must resolve as active or the key fails closed.
            return _Rows(row={"external_id": None, "status": "active"})
        return _Rows()


@pytest.fixture(autouse=True)
def _reset_app_overrides():
    api_main.app.dependency_overrides.clear()
    yield
    api_main.app.dependency_overrides.clear()


def _client(monkeypatch, db):
    monkeypatch.setattr(api_main.settings, "svs_dev_mode", False)
    api_main.app.dependency_overrides[api_main.get_session] = lambda: db
    return TestClient(api_main.app)


def test_admin_session_missing_credential_fails_closed(monkeypatch):
    response = _client(monkeypatch, _SessionDb()).get("/api/v1/admin/session")

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing bearer token"


def test_admin_session_dev_identity_headers_fail_closed_in_production(monkeypatch):
    response = _client(monkeypatch, _SessionDb()).get(
        "/api/v1/admin/session",
        headers={
            "x-svs-tenant-id": "ten_dev",
            "x-svs-business-instance-id": "biz_dev",
            "x-svs-user-id": "usr_dev",
            "x-svs-groups": "admins",
            "x-svs-roles": "owner",
            "x-svs-max-security-level": "5",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Missing bearer token"


def test_admin_session_invalid_or_expired_key_fails_closed(monkeypatch):
    db = _SessionDb(api_key_row=None)
    response = _client(monkeypatch, db).get(
        "/api/v1/admin/session",
        headers={"Authorization": "Bearer svs_live_expired"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or expired API key"
    lookup_sql = db.calls[1][0]
    assert "status='active'" in lookup_sql
    assert "(expires_at IS NULL OR expires_at > now())" in lookup_sql


def test_admin_session_insufficient_scope_is_forbidden(monkeypatch):
    db = _SessionDb(
        api_key_row={
            "id": "key_read_only",
            "tenant_id": "tenant",
            "business_instance_id": "biz",
            "user_id": None,
            "scopes": ["documents:read"],
            "max_security_level": 2,
        }
    )

    response = _client(monkeypatch, db).get(
        "/api/v1/admin/session",
        headers={"Authorization": "Bearer svs_live_read_only"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["error"] == "insufficient_scope"
    assert response.json()["detail"]["any_of"] is True


def test_admin_session_scoped_principal_success(monkeypatch):
    db = _SessionDb(
        api_key_row={
            "id": "key_admin",
            "tenant_id": "tenant",
            "business_instance_id": "biz",
            "user_id": "user_owner",
            "scopes": ["api_keys:read", "role:owner"],
            "max_security_level": 4,
        },
        group_slugs=["admins"],
    )

    response = _client(monkeypatch, db).get(
        "/api/v1/admin/session",
        headers={"Authorization": "Bearer svs_live_admin"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "object": "admin.session",
        "authenticated": True,
        "tenant_id": "tenant",
        "business_instance_id": "biz",
        "user_id": "user_owner",
        "api_key_id": "key_admin",
        "scopes": ["api_keys:read", "role:owner"],
        "roles": ["owner"],
        "groups": ["admins"],
        "max_security_level": 4,
    }


def test_admin_ui_request_decoration_uses_bearer_and_no_production_dev_headers():
    root = Path(__file__).resolve().parents[1]
    auth_source = (root / "apps/admin_ui/src/auth.ts").read_text()
    main_source = (root / "apps/admin_ui/src/main.tsx").read_text()

    assert "throw new MissingAdminCredentialError()" in auth_source
    assert "Authorization: normalizeBearerCredential(apiKey)" in auth_source
    assert "removeDevIdentityHeaders(headersToRecord(init.headers))" in auth_source
    assert "if (envFlag(env.PROD)) return false" in auth_source
    assert "VITE_SVS_DEV_MODE" in auth_source
    assert "buildDevIdentityHeaders" in auth_source
    assert "decorateAdminRequest" in main_source
    assert "x-svs-tenant-id" not in main_source
    assert "localStorage.getItem('svs_tenant')" not in main_source
