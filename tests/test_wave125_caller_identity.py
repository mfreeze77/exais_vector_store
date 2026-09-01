"""WAVE-125: caller jurisdiction metadata and per-user API keys.

Contract, isolation, attribution, and filter-does-not-widen coverage using the
repository's fake-DB style (no Postgres). RLS enforcement itself is covered by
the integration suite; these tests prove the application SQL and route
behavior that sit above it.
"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from svs_api import main as api_main
from svs_common import auth as auth_mod
from svs_common import expert_profiles
from svs_common import retrieval as retrieval_mod
from svs_common import ingestion as ingestion_mod
from svs_common.auth import USER_BOUND_ALLOWED_SCOPES, create_api_key, list_api_keys, resolve_api_key_principal
from svs_common.expert_profiles import (
    ExpertProfileDefinition,
    ExpertVectorStoreBindingDefinition,
    list_expert_profiles,
    resolve_expert_profile,
)
from svs_common.expert_sessions import (
    create_or_resume_expert_session,
    get_expert_session,
    record_expert_turn_accounting,
)
from svs_common.users import get_user_by_external_id
from svs_common.request_controls import enforce_rate_limit
from svs_common.schemas import (
    EXPERT_CORPUS_KINDS,
    AdminUserCreateRequest,
    AdminUserResponse,
    ExpertCitationPolicy,
    ExpertMessageRequest,
    ExpertMessageResponse,
    ExpertModelMetadata,
    ExpertModelPolicy,
    ExpertProfile,
    ExpertRetrievalTrace,
    ExpertSessionForkRequest,
    ExpertToolLimits,
    ExpertChatUsage,
    ExpertChatFallback,
    Principal,
    UsageSummaryResponse,
)
from svs_common.users import create_or_get_user, deactivate_user, list_users


ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- fakes


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

    def scalar_one(self):
        return self.row


class _Db:
    """Queue-based fake: each execute pops the next queued result (list -> rows, dict -> row)."""

    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls: list[tuple[str, dict]] = []
        self.committed = False

    def execute(self, stmt, params=None):
        self.calls.append((str(stmt), dict(params or {})))
        if self.results:
            result = self.results.pop(0)
            if isinstance(result, list):
                return _Rows(rows=result)
            return _Rows(row=result)
        return _Rows()

    def commit(self):
        self.committed = True

    def sql(self, index: int) -> str:
        return " ".join(self.calls[index][0].split())


class _ScopedSessionDb:
    """Returns the stored expert session only when the caller's exact scope matches."""

    def __init__(self, session_row: dict):
        self.session_row = session_row
        self.calls: list[tuple[str, dict]] = []
        self.committed = False

    def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        params = dict(params or {})
        self.calls.append((sql, params))
        if "FROM expert_sessions" in sql and "WHERE id=:session_id" in sql:
            row = self.session_row
            if (
                params.get("session_id") == row["id"]
                and params.get("tenant_id") == row["tenant_id"]
                and params.get("biz_id") == row["business_instance_id"]
                and params.get("api_key_id") == row["api_key_id"]
                and params.get("user_id") == row["user_id"]
            ):
                return _Rows(row=row)
            return _Rows(row=None)
        return _Rows(rows=[])

    def commit(self):
        self.committed = True


def _principal(**overrides) -> Principal:
    values = dict(
        tenant_id="tenant",
        business_instance_id="biz",
        user_id="usr_admin",
        api_key_id="key_admin",
        scopes=["api_keys:write", "usage:read", "retrieval:read", "documents:write", "vector_stores:write", "vector_stores:read"],
        max_security_level=3,
    )
    values.update(overrides)
    return Principal(**values)


def _user_row(**overrides) -> dict:
    row = {
        "id": "usr_bound",
        "external_id": "ext-1",
        "email": None,
        "display_name": "Bound User",
        "status": "active",
        "business_instance_id": "biz",
        "created_at": 1710000000,
        "deactivated_at": None,
    }
    row.update(overrides)
    return row


def _definition(**overrides) -> ExpertProfileDefinition:
    values = dict(
        id="topeka-fixture",
        label="Topeka Fixture",
        description="fixture",
        system_prompt="Use retrieved sources only.",
        vector_store_bindings=(
            ExpertVectorStoreBindingDefinition(
                vector_store_id="vs_topeka",
                tenant_id="tenant",
                business_instance_id="biz",
                allowed_graph_lens_ids=(),
            ),
        ),
        citation_policy=ExpertCitationPolicy(),
        caveats=(),
        model_policy=ExpertModelPolicy(policy_id="fixture_v1"),
        tool_limits=ExpertToolLimits(max_retrieval_runs=1, max_results_per_run=5, max_graph_expansions=0, max_context_tokens=1000),
        jurisdiction_key="ks:city:topeka",
        corpus="municipal_code",
    )
    values.update(overrides)
    return ExpertProfileDefinition(**values)


def _store_results(vector_store_id: str = "vs_topeka") -> list[dict]:
    return [
        {"id": vector_store_id, "status": "completed", "is_expired": False},
        {
            "id": vector_store_id,
            "name": "Fixture store",
            "status": "completed",
            "usage_bytes": 0,
            "attributes": {"corpus": "topeka_municipal_code"},
            "expires_after": None,
            "created_at": 1,
            "expires_at": None,
            "last_active_at": 1,
            "file_counts": {},
        },
    ]


def _message_response(session_id: str = "exps_1") -> ExpertMessageResponse:
    return ExpertMessageResponse(
        expert_id="topeka-fixture",
        session_id=session_id,
        answer="A grounded answer.",
        citations=[],
        retrieval_trace=ExpertRetrievalTrace(status="not_run", runs=[]),
        model_metadata=ExpertModelMetadata(
            policy_id="fixture_v1",
            requested_model_profile_id="fixture_v1",
            model_profile_id="fixture_v1",
            provider="fixture",
            model="fixture-model",
            latency_ms=1,
            usage=ExpertChatUsage(input_tokens=10, output_tokens=5, total_tokens=15),
            finish_reason="stop",
            fallback=ExpertChatFallback(occurred=False, attempts=[]),
        ),
        caveats=[],
        follow_up_suggestions=[],
    )


@pytest.fixture(autouse=True)
def _quiet_route_controls(monkeypatch):
    monkeypatch.setattr(api_main, "enforce_rate_limit", lambda *args, **kwargs: None)
    api_main.app.dependency_overrides.clear()
    yield
    api_main.app.dependency_overrides.clear()


# --------------------------------------------------------------- Scope A: metadata


def test_registry_experts_declare_jurisdiction_and_corpus():
    by_id = {definition.id: definition for definition in expert_profiles.EXPERT_PROFILE_REGISTRY}
    assert by_id["kansas-court-decisions"].jurisdiction_key == "ks:state:kansas"
    assert by_id["kansas-court-decisions"].corpus == "court_decisions"
    assert by_id["topeka-municipal-code"].jurisdiction_key == "ks:city:topeka"
    assert by_id["topeka-municipal-code"].corpus == "municipal_code"
    for definition in by_id.values():
        assert definition.corpus in EXPERT_CORPUS_KINDS


def test_resolved_profile_surfaces_jurisdiction_and_corpus(monkeypatch):
    monkeypatch.setattr(expert_profiles, "EXPERT_PROFILE_REGISTRY", (_definition(),))
    profile = resolve_expert_profile(_Db(_store_results()), _principal(), "topeka-fixture")
    assert profile.jurisdiction_key == "ks:city:topeka"
    assert profile.corpus == "municipal_code"
    assert ExpertProfile.model_validate(profile.model_dump()).jurisdiction_key == "ks:city:topeka"


def test_jurisdiction_filter_never_widens_visibility(monkeypatch):
    visible = _definition()
    hidden_same_key = _definition(
        id="other-tenant-topeka",
        vector_store_bindings=(
            ExpertVectorStoreBindingDefinition(
                vector_store_id="vs_other",
                tenant_id="tenant_other",
                business_instance_id="biz_other",
            ),
        ),
    )
    visible_other_key = _definition(id="kansas-fixture", jurisdiction_key="ks:state:kansas", corpus="court_decisions")
    monkeypatch.setattr(expert_profiles, "EXPERT_PROFILE_REGISTRY", (visible, hidden_same_key, visible_other_key))

    # Unfiltered: only the two in-scope profiles (two store lookups each).
    unfiltered = list_expert_profiles(_Db(_store_results() + _store_results()), _principal())
    assert [profile.id for profile in unfiltered.data] == ["topeka-fixture", "kansas-fixture"]

    # Filter by the hidden expert's key: the cross-scope expert stays hidden and
    # the visible expert with that key is the only row.
    filtered = list_expert_profiles(
        _Db(_store_results() + _store_results()), _principal(), jurisdiction_key="ks:city:topeka",
    )
    assert [profile.id for profile in filtered.data] == ["topeka-fixture"]
    assert all(profile.jurisdiction_key == "ks:city:topeka" for profile in filtered.data)

    # A principal who cannot see anything gets nothing, filter or not.
    outsider = _principal(tenant_id="tenant_z", business_instance_id="biz_z")
    assert list_expert_profiles(_Db(), outsider, jurisdiction_key="ks:city:topeka").data == []
    assert list_expert_profiles(_Db(), outsider).data == []

    # Corpus filter narrows the same way; whitespace is normalized.
    by_corpus = list_expert_profiles(
        _Db(_store_results() + _store_results()), _principal(), corpus=" court_decisions ",
    )
    assert [profile.id for profile in by_corpus.data] == ["kansas-fixture"]


def test_list_experts_route_passes_filters_and_rejects_unknown_corpus(monkeypatch):
    seen = {}

    def fake_list(db, principal, *, jurisdiction_key=None, corpus=None):
        seen.update(jurisdiction_key=jurisdiction_key, corpus=corpus)
        return {"object": "expert.profile.list", "data": [], "first_id": None, "last_id": None, "has_more": False}

    monkeypatch.setattr(api_main, "list_expert_profiles", fake_list)
    api_main.list_experts(jurisdiction_key="ks:city:topeka", corpus="municipal_code", principal=_principal(), db=_Db())
    assert seen == {"jurisdiction_key": "ks:city:topeka", "corpus": "municipal_code"}

    monkeypatch.setattr(api_main.settings, "svs_dev_mode", True)
    api_main.app.dependency_overrides[api_main.get_session] = lambda: _Db()
    response = TestClient(api_main.app).get(
        "/v1/experts",
        params={"corpus": "not-a-corpus"},
        headers={"x-svs-tenant-id": "tenant", "x-svs-business-instance-id": "biz"},
    )
    assert response.status_code == 422


# ------------------------------------------------------------- Scope B: admin users


def test_create_user_is_idempotent_on_external_id_and_instance_scoped():
    principal = _principal()
    db = _Db(results=[None, _user_row()])
    created = api_main.create_admin_user(AdminUserCreateRequest(external_id=" ext-1 "), principal=principal, db=db)
    assert AdminUserResponse.model_validate(created).id == "usr_bound"
    assert created["external_id"] == "ext-1"
    lookup_sql, lookup_params = db.calls[0]
    # The conflict pre-check is tenant-wide on purpose (the unique index is per tenant).
    assert "external_id=:external_id" in lookup_sql and "business_instance_id=:biz_id" not in lookup_sql
    assert lookup_params == {"tenant_id": "tenant", "external_id": "ext-1"}
    insert_sql, insert_params = db.calls[1]
    assert "INSERT INTO users" in insert_sql
    assert "ON CONFLICT DO NOTHING" in insert_sql
    assert insert_params["biz_id"] == "biz" and insert_params["external_id"] == "ext-1"
    assert db.committed is True

    again = _Db(results=[_user_row()])
    user, created_flag = create_or_get_user(again, principal, external_id="ext-1")
    assert created_flag is False and user["id"] == "usr_bound"
    assert len(again.calls) == 1  # no INSERT on the idempotent path

    other_instance = _Db(results=[_user_row(business_instance_id="biz_other")])
    with pytest.raises(HTTPException) as exc:
        create_or_get_user(other_instance, principal, external_id="ext-1")
    assert exc.value.status_code == 409


def test_get_user_by_external_id_is_instance_fenced():
    db = _Db(results=[_user_row()])
    user = get_user_by_external_id(db, _principal(), "ext-1")
    assert user["id"] == "usr_bound"
    sql, params = db.calls[0]
    assert "tenant_id=:tenant_id" in sql and "business_instance_id=:biz_id" in sql
    assert params == {"tenant_id": "tenant", "biz_id": "biz", "external_id": "ext-1"}


def test_create_user_rejects_blank_external_id_and_duplicate_email():
    with pytest.raises(ValueError):
        AdminUserCreateRequest(external_id="   ")
    db = _Db(results=[None, {"id": "usr_other"}])
    with pytest.raises(HTTPException) as exc:
        create_or_get_user(db, _principal(), external_id="ext-2", email="dup@example.test")
    assert exc.value.status_code == 409


def test_list_users_filters_by_external_id_inside_instance_scope():
    db = _Db(results=[[_user_row()]])
    data, has_more = list_users(db, _principal(), limit=10, external_id="ext-1", status_filter="active")
    assert has_more is False and data[0]["external_id"] == "ext-1"
    sql, params = db.calls[0]
    assert "business_instance_id=:biz_id" in sql
    assert "AND external_id=:external_id" in sql and "AND status=:status" in sql
    assert params["external_id"] == "ext-1" and params["status"] == "active"

    route = api_main.list_admin_users(limit=5, after=None, external_id="ext-1", status="active", principal=_principal(), db=_Db(results=[[_user_row()]]))
    assert route["object"] == "list" and route["data"][0]["id"] == "usr_bound"


def test_deactivate_user_revokes_keys_audits_and_preserves_history():
    principal = _principal()
    db = _Db(results=[_user_row(status="deactivated", deactivated_at=1710009999), [{"id": "key_1"}, {"id": "key_2"}]])
    response = api_main.deactivate_admin_user("usr_bound", principal=principal, db=db)
    assert response["revoked_api_key_ids"] == ["key_1", "key_2"]
    assert response["data"]["status"] == "deactivated"
    assert response["object"] == "user.deactivated"
    update_sql, update_params = db.calls[0]
    assert "UPDATE users" in update_sql and "status='deactivated'" in update_sql
    assert update_params["biz_id"] == "biz" and update_params["id"] == "usr_bound"
    revoke_sql, revoke_params = db.calls[1]
    assert "UPDATE api_keys" in revoke_sql and "SET status='revoked'" in revoke_sql
    assert "user_id=:user_id" in revoke_sql and revoke_params["user_id"] == "usr_bound"
    audit_sql, audit_params = db.calls[2]
    assert "INSERT INTO audit_events" in audit_sql and "'user.deactivate'" in audit_sql
    assert audit_params["actor_api_key_id"] == "key_admin"
    assert not any(re.search(r"\bDELETE\b", sql) for sql, _ in db.calls)
    assert db.committed is True

    # Idempotent: second deactivation returns no newly revoked keys.
    user, revoked = deactivate_user(_Db(results=[_user_row(status="deactivated"), []]), principal, "usr_bound")
    assert revoked == [] and user["status"] == "deactivated"

    with pytest.raises(HTTPException) as exc:
        api_main.deactivate_admin_user("usr_missing", principal=principal, db=_Db(results=[None]))
    assert exc.value.status_code == 404


def test_user_routes_require_users_or_api_keys_write_scope():
    read_only = _principal(scopes=["retrieval:read"])
    with pytest.raises(HTTPException) as exc:
        api_main.create_admin_user(AdminUserCreateRequest(external_id="ext"), principal=read_only, db=_Db())
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException):
        api_main.list_admin_users(principal=read_only, db=_Db())
    with pytest.raises(HTTPException):
        api_main.deactivate_admin_user("usr_x", principal=read_only, db=_Db())
    # A dedicated users:write scope is sufficient without api_keys:write.
    users_writer = _principal(scopes=["users:write"])
    created = api_main.create_admin_user(AdminUserCreateRequest(external_id="ext"), principal=users_writer, db=_Db(results=[None, _user_row()]))
    assert created["id"] == "usr_bound"


# ---------------------------------------------------------- Scope C: user-bound keys


def test_create_user_bound_key_defaults_scopes_and_binds_user(monkeypatch):
    seen = {}

    def fake_create(db, principal, label, scopes, max_security_level, expires_at, *, user_id=None):
        seen.update(label=label, scopes=scopes, max_security_level=max_security_level, user_id=user_id)
        return {"id": "key_u", "api_key": "svs_live_x", "label": label, "scopes": scopes, "max_security_level": max_security_level, "user_id": user_id}

    monkeypatch.setattr(api_main, "create_api_key", fake_create)
    db = _Db(results=[_user_row()])
    result = api_main.create_instance_api_key(label="bound", user_id="usr_bound", principal=_principal(), db=db)
    assert seen == {"label": "bound", "scopes": ["retrieval:read"], "max_security_level": 3, "user_id": "usr_bound"}
    assert result["user_id"] == "usr_bound"
    lookup_sql, lookup_params = db.calls[0]
    assert "FROM users" in lookup_sql and "business_instance_id=:biz_id" in lookup_sql
    assert lookup_params["id"] == "usr_bound"

    # Without user_id the legacy default scope set is unchanged.
    api_main.create_instance_api_key(label="cell", principal=_principal(), db=_Db())
    assert seen["scopes"] == ["retrieval:read", "documents:write", "vector_stores:write", "vector_stores:read"]
    assert seen["user_id"] is None


def test_create_user_bound_key_enforces_subset_scopes_level_cap_and_user_state(monkeypatch):
    monkeypatch.setattr(api_main, "create_api_key", lambda *a, **k: pytest.fail("must not mint"))
    principal = _principal(scopes=["api_keys:write", "retrieval:read"], max_security_level=2)

    with pytest.raises(HTTPException) as exc:
        api_main.create_instance_api_key(user_id="usr_bound", scopes="retrieval:read,documents:write", principal=principal, db=_Db(results=[_user_row()]))
    assert exc.value.status_code == 403
    assert exc.value.detail["required"] == ["documents:write"]

    with pytest.raises(HTTPException) as exc:
        api_main.create_instance_api_key(user_id="usr_bound", scopes="*", principal=_principal(scopes=["*"]), db=_Db(results=[_user_row()]))
    assert exc.value.status_code == 403

    with pytest.raises(HTTPException) as exc:
        api_main.create_instance_api_key(user_id="usr_bound", max_security_level=5, principal=principal, db=_Db(results=[_user_row()]))
    assert exc.value.status_code == 422

    with pytest.raises(HTTPException) as exc:
        api_main.create_instance_api_key(user_id="usr_gone", principal=principal, db=_Db(results=[None]))
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as exc:
        api_main.create_instance_api_key(user_id="usr_bound", principal=principal, db=_Db(results=[_user_row(status="deactivated")]))
    assert exc.value.status_code == 409


def test_every_key_creation_enforces_subset_scopes_and_level_cap(monkeypatch):
    monkeypatch.setattr(api_main, "create_api_key", lambda *a, **k: pytest.fail("must not mint"))
    creator = _principal(scopes=["api_keys:write", "retrieval:read"], max_security_level=2)

    # An unbound request for scopes the creator does not hold is refused ...
    with pytest.raises(HTTPException) as exc:
        api_main.create_instance_api_key(scopes="*", principal=creator, db=_Db())
    assert exc.value.status_code == 403 and exc.value.detail["required"] == ["*"]
    with pytest.raises(HTTPException) as exc:
        api_main.create_instance_api_key(scopes="retrieval:read,documents:write,admin:read", principal=creator, db=_Db())
    assert exc.value.status_code == 403 and exc.value.detail["required"] == ["documents:write", "admin:read"]
    # ... and so is the legacy default scope set when the creator lacks part of it.
    with pytest.raises(HTTPException) as exc:
        api_main.create_instance_api_key(principal=creator, db=_Db())
    assert exc.value.status_code == 403
    # ... and a level above the creator's, with or without user_id.
    with pytest.raises(HTTPException) as exc:
        api_main.create_instance_api_key(scopes="retrieval:read", max_security_level=5, principal=creator, db=_Db())
    assert exc.value.status_code == 422

    # The auth layer enforces the same rules for any direct caller.
    with pytest.raises(HTTPException) as exc:
        create_api_key(_Db(), creator, "direct", ["vector_stores:write"])
    assert exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        create_api_key(_Db(), creator, "direct", ["retrieval:read"], 3)
    assert exc.value.status_code == 422

    # Wildcards stay mintable only by a principal that actually holds them.
    seen = {}
    monkeypatch.setattr(api_main, "create_api_key", lambda db, p, label, scopes, level, exp, **kw: seen.update(scopes=scopes, level=level) or {"id": "k", "api_key": "s", "label": label, "scopes": scopes, "max_security_level": level})
    api_main.create_instance_api_key(scopes="*", max_security_level=5, principal=_principal(scopes=["*"], max_security_level=5), db=_Db())
    assert seen == {"scopes": ["*"], "level": 5}


def test_user_bound_keys_only_carry_allow_listed_scopes(monkeypatch):
    assert USER_BOUND_ALLOWED_SCOPES == {
        "retrieval:read", "documents:read", "documents:write", "vector_stores:read", "vector_stores:write",
    }
    monkeypatch.setattr(api_main, "create_api_key", lambda *a, **k: pytest.fail("must not mint"))
    owner = _principal(scopes=["*"], max_security_level=5)
    for scopes in (
        "api_keys:write", "users:read", "admin:read", "usage:read", "audit:read", "fleet:read",
        "role:owner", "*", "system", "documents:*", "vector_stores:*", "future:anything",
        "retrieval:read,api_keys:read",
    ):
        with pytest.raises(HTTPException) as exc:
            api_main.create_instance_api_key(user_id="usr_bound", scopes=scopes, principal=owner, db=_Db(results=[_user_row()]))
        assert exc.value.status_code == 403, scopes
        assert exc.value.detail["error"] == "scope_not_delegable_to_user_bound_key", scopes
        assert exc.value.detail["required"] == [s for s in scopes.split(",") if s not in USER_BOUND_ALLOWED_SCOPES], scopes

    # Every allow-listed scope is mintable by a creator that holds it.
    seen = {}
    monkeypatch.setattr(api_main, "create_api_key", lambda db, p, label, scopes, level, exp, **kw: seen.update(scopes=scopes) or {"id": "k", "api_key": "s", "label": label, "scopes": scopes, "max_security_level": level, "user_id": kw.get("user_id")})
    api_main.create_instance_api_key(user_id="usr_bound", scopes=",".join(sorted(USER_BOUND_ALLOWED_SCOPES)), principal=owner, db=_Db(results=[_user_row()]))
    assert set(seen["scopes"]) == USER_BOUND_ALLOWED_SCOPES
    monkeypatch.setattr(api_main, "create_api_key", lambda *a, **k: pytest.fail("must not mint"))
    # The auth layer refuses the same delegation directly.
    with pytest.raises(HTTPException) as exc:
        create_api_key(_Db(), owner, "bound", ["usage:read"], user_id="usr_bound")
    assert exc.value.detail["error"] == "scope_not_delegable_to_user_bound_key"
    # A user-bound key holding api_keys:write (legacy data) still cannot widen itself.
    bound_admin = _principal(user_id="usr_bound", api_key_id="key_u", external_id="ext-1", scopes=["api_keys:write", "retrieval:read"], max_security_level=1)
    with pytest.raises(HTTPException) as exc:
        api_main.create_instance_api_key(scopes="*", max_security_level=5, principal=bound_admin, db=_Db())
    assert exc.value.status_code == 403


def test_create_api_key_persists_bound_user_and_returns_raw_key_once(monkeypatch):
    monkeypatch.setattr(auth_mod, "generate_api_key", lambda: "svs_live_bound_secret")
    db = _Db()
    result = create_api_key(db, _principal(), "bound", ["retrieval:read"], 1, None, user_id="usr_bound")
    sql, params = db.calls[0]
    assert "INSERT INTO api_keys" in sql
    assert params["user_id"] == "usr_bound" and params["scopes"] == ["retrieval:read"]
    assert result["user_id"] == "usr_bound" and result["api_key"] == "svs_live_bound_secret"
    # Unbound creation still inherits the creator's user.
    db2 = _Db()
    create_api_key(db2, _principal(), "cell")
    assert db2.calls[0][1]["user_id"] == "usr_admin"


def test_list_api_keys_filters_by_user_and_exposes_binding():
    db = _Db(results=[[{
        "id": "key_u", "label": "bound", "scopes": ["retrieval:read"], "max_security_level": 1,
        "user_id": "usr_bound", "status": "active", "created_at": 1, "last_used_at": None, "expires_at": None,
    }]])
    data, _ = list_api_keys(db, _principal(), 20, user_id="usr_bound")
    sql, params = db.calls[0]
    assert "AND user_id=:filter_user_id" in sql and params["filter_user_id"] == "usr_bound"
    assert data[0]["user_id"] == "usr_bound"
    assert "key_hash" not in sql


def _admin_client(monkeypatch, api_key_row):
    class _SessionDb:
        def __init__(self):
            self.calls = []

        def execute(self, stmt, params=None):
            sql = str(stmt)
            self.calls.append((sql, params or {}))
            if "FROM api_keys" in sql and "WHERE key_hash=:key_hash" in sql:
                return _Rows(row=api_key_row)
            if "FROM users" in sql and "WHERE id=:user_id" in sql:
                return _Rows(row=_user_row())
            return _Rows()

        def commit(self):
            pass

    monkeypatch.setattr(api_main.settings, "svs_dev_mode", False)
    api_main.app.dependency_overrides[api_main.get_session] = lambda: _SessionDb()
    return TestClient(api_main.app)


def test_user_bound_retrieval_key_gets_403_on_every_admin_route(monkeypatch):
    client = _admin_client(monkeypatch, {
        "id": "key_u", "tenant_id": "tenant", "business_instance_id": "biz",
        "user_id": "usr_bound", "scopes": ["retrieval:read"], "max_security_level": 1,
    })
    bodies = {
        "/api/v1/admin/users": {"external_id": "ext-1"},
        "/v1/organization/admin_api_keys": {"name": "x"},
    }
    checked = []
    for route in api_main.app.routes:
        path = getattr(route, "path", "")
        if not (path.startswith("/api/v1/admin") or path.startswith("/v1/organization")):
            continue
        if path == "/api/v1/admin/session":
            # The admin-UI identity echo deliberately answers any ADMIN_UI_SESSION_SCOPES
            # holder (including retrieval:read) with the caller's own principal only; it
            # exposes nothing beyond the key's own scopes and mutates nothing.
            continue
        for method in sorted(getattr(route, "methods", set()) or set()):
            if method in {"HEAD", "OPTIONS"}:
                continue
            url = re.sub(r"\{[^}]+\}", "x", path)
            response = client.request(
                method,
                url,
                params={"name": "x", "slug": "x"},
                json=bodies.get(path),
                headers={"Authorization": "Bearer svs_live_bound"},
            )
            checked.append((method, path, response.status_code))
            assert response.status_code == 403, (method, path, response.text)
            assert response.json()["detail"]["error"] == "insufficient_scope"
    paths = {path for _, path, _ in checked}
    assert {"/api/v1/admin/users", "/api/v1/admin/users/{user_id}/deactivate", "/api/v1/admin/usage/summary",
            "/api/v1/admin/api-keys", "/api/v1/admin/usage", "/api/v1/admin/audit-events",
            "/api/v1/admin/fleet/versions", "/api/v1/admin/tenants"} <= paths
    assert len(checked) >= 15


def test_user_bound_key_cannot_read_fork_or_list_memory_of_another_users_session(monkeypatch):
    session_row = {
        "id": "exps_a", "session_key": "expsk_a", "expert_id": "topeka-fixture",
        "api_key_id": "key_a", "user_id": "usr_a", "tenant_id": "tenant", "business_instance_id": "biz",
        "external_user_id": "ext-a", "conversation_id": "conv-a", "label": None, "parent_session_id": None,
        "status": "active", "metadata": {}, "created_at": None, "updated_at": None, "last_active_at": None,
    }
    owner = _principal(user_id="usr_a", api_key_id="key_a", scopes=["retrieval:read"], external_id="ext-a")
    intruder = _principal(user_id="usr_b", api_key_id="key_b", scopes=["retrieval:read"], external_id="ext-b")

    assert get_expert_session(_ScopedSessionDb(session_row), owner, "exps_a") is not None
    assert get_expert_session(_ScopedSessionDb(session_row), intruder, "exps_a") is None
    db = _ScopedSessionDb(session_row)
    get_expert_session(db, intruder, "exps_a")
    assert "user_id IS NOT DISTINCT FROM :user_id" in db.calls[0][0]
    assert "api_key_id IS NOT DISTINCT FROM :api_key_id" in db.calls[0][0]
    assert db.calls[0][1]["user_id"] == "usr_b"

    monkeypatch.setattr(api_main, "resolve_expert_profile", lambda db, principal, expert_id: SimpleNamespace(id=expert_id))
    monkeypatch.setattr(api_main, "check_idempotency", lambda *args: None)
    monkeypatch.setattr(api_main, "list_expert_memory_events", lambda *args: pytest.fail("must not list memory"))
    monkeypatch.setattr(api_main, "fork_expert_session", lambda *args, **kwargs: pytest.fail("must not fork"))

    # Even when the intruder guesses the correlation ids, the session is invisible.
    with pytest.raises(HTTPException) as exc:
        api_main.get_expert_memory("topeka-fixture", "exps_a", external_user_id=None, conversation_id="conv-a", principal=intruder, db=_ScopedSessionDb(session_row))
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        api_main.fork_expert_session_route(
            "topeka-fixture", "exps_a", ExpertSessionForkRequest(conversation_id="conv-a"),
            idempotency_key=None, principal=intruder, db=_ScopedSessionDb(session_row),
        )
    assert exc.value.status_code == 404
    # Supplying the other user's external id is rejected before any lookup.
    with pytest.raises(HTTPException) as exc:
        api_main.get_expert_memory("topeka-fixture", "exps_a", external_user_id="ext-a", conversation_id="conv-a", principal=intruder, db=_ScopedSessionDb(session_row))
    assert exc.value.status_code == 403


# ------------------------------------------------------------ Scope D: attribution


def test_session_creation_and_turn_accounting_carry_bound_user_and_key():
    principal = _principal(user_id="usr_bound", api_key_id="key_u", scopes=["retrieval:read"], external_id="ext-1")
    session_row = {
        "id": "exps_new", "session_key": "expsk_new", "expert_id": "topeka-fixture", "api_key_id": "key_u", "user_id": "usr_bound",
        "external_user_id": "ext-1", "conversation_id": "conv-1", "label": None, "parent_session_id": None,
        "status": "active", "metadata": {}, "created_at": None, "updated_at": None, "last_active_at": None,
    }
    db = _Db(results=[session_row, [], [], [], []])
    session = create_or_resume_expert_session(db, principal, "topeka-fixture", external_user_id="ext-1", conversation_id="conv-1")
    assert session.id == "exps_new"
    insert_sql, insert_params = db.calls[0]
    assert "INSERT INTO expert_sessions" in insert_sql
    assert insert_params["user_id"] == "usr_bound" and insert_params["api_key_id"] == "key_u"
    assert insert_params["external_user_id"] == "ext-1"

    accounting = _Db()
    usage_id, audit_id = record_expert_turn_accounting(
        accounting, principal, _message_response("exps_new"), external_user_id="ext-1", conversation_id="conv-1",
    )
    assert usage_id.startswith("use_") and audit_id.startswith("aud_")
    usage_sql, usage_params = accounting.calls[0]
    assert "INSERT INTO usage_events" in usage_sql and "'expert.message'" in usage_sql
    assert usage_params["user_id"] == "usr_bound" and usage_params["api_key_id"] == "key_u"
    assert usage_params["quantity"] == 15 and usage_params["provider"] == "fixture"
    usage_metadata = json.loads(usage_params["metadata"])
    assert usage_metadata["external_user_id"] == "ext-1" and usage_metadata["session_id"] == "exps_new"
    assert usage_metadata["input_tokens"] == 10 and usage_metadata["output_tokens"] == 5
    audit_sql, audit_params = accounting.calls[1]
    assert "INSERT INTO audit_events" in audit_sql and "'expert', 'message'" in audit_sql
    assert audit_params["user_id"] == "usr_bound" and audit_params["api_key_id"] == "key_u"
    assert audit_params["resource_id"] == "exps_new"


def test_message_route_records_attributed_usage_and_audit_after_turn(monkeypatch):
    principal = _principal(user_id="usr_bound", api_key_id="key_u", scopes=["retrieval:read"], external_id="ext-1")

    async def run(db, principal, req):
        return _message_response()

    monkeypatch.setattr(api_main, "run_expert_turn", run)
    monkeypatch.setattr(api_main, "check_idempotency", lambda *args: None)
    monkeypatch.setattr(api_main, "store_idempotency", lambda *args, **kwargs: None)
    db = _Db()
    response = asyncio.run(api_main.post_expert_message(
        "topeka-fixture",
        ExpertMessageRequest(message="Question", external_user_id="ext-1", conversation_id="conv-1"),
        idempotency_key=None,
        principal=principal,
        db=db,
    ))
    assert response.session_id == "exps_1"
    kinds = [("usage" if "INSERT INTO usage_events" in sql else "audit" if "INSERT INTO audit_events" in sql else "other") for sql, _ in db.calls]
    assert kinds == ["usage", "audit"]
    for _, params in db.calls:
        assert params["user_id"] == "usr_bound" and params["api_key_id"] == "key_u"
    assert db.committed is True


def test_message_route_rejects_external_user_id_that_disagrees_with_bound_user(monkeypatch):
    monkeypatch.setattr(api_main, "run_expert_turn", lambda *a, **k: pytest.fail("must not run expert"))
    bound = _principal(user_id="usr_bound", api_key_id="key_u", scopes=["retrieval:read"], external_id="ext-1")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(api_main.post_expert_message(
            "topeka-fixture", ExpertMessageRequest(message="Q", external_user_id="ext-2"),
            idempotency_key=None, principal=bound, db=_Db(),
        ))
    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "external_user_id_mismatch"

    # A cell key (no bound external id) keeps the caller-side correlation id untouched.
    api_main._ensure_external_user_binding(_principal(external_id=None), "anyone")
    api_main._ensure_external_user_binding(bound, "ext-1")
    api_main._ensure_external_user_binding(bound, None)


def test_rate_limit_buckets_and_existing_usage_writers_carry_key_and_user():
    principal = _principal(user_id="usr_bound", api_key_id="key_u", scopes=["retrieval:read"])
    db = _Db(results=[{"count": 1}])
    enforce_rate_limit(db, principal, "experts.messages.create", limit_per_minute=10)
    sql, params = db.calls[0]
    assert "INSERT INTO rate_limit_counters" in sql and "api_key_id, user_id" in sql
    assert params["api_key_id"] == "key_u" and params["user_id"] == "usr_bound"
    assert params["subject_id"] == "key_u"

    retrieval_source = inspect.getsource(retrieval_mod.RetrievalService._audit)
    assert "INSERT INTO usage_events(id, tenant_id, business_instance_id, user_id, api_key_id" in retrieval_source
    ingestion_source = inspect.getsource(ingestion_mod)
    assert "INSERT INTO usage_events(id, tenant_id, business_instance_id, user_id, api_key_id" in ingestion_source


def test_usage_route_filters_and_summary_group_rows():
    principal = _principal(scopes=["usage:read"])
    db = _Db(results=[[{
        "id": "use_1", "event_type": "expert.message", "quantity": 15, "unit": "token", "provider": "fixture", "model": "m",
        "cost_estimate_usd": None, "user_id": "usr_bound", "api_key_id": "key_u", "metadata": {}, "created_at": 1,
    }]])
    listing = api_main.usage(limit=10, user_id="usr_bound", api_key_id="key_u", principal=principal, db=db)
    assert listing["data"][0]["api_key_id"] == "key_u"
    sql, params = db.calls[0]
    assert "AND user_id=:user_id" in sql and "AND api_key_id=:api_key_id" in sql
    assert params["user_id"] == "usr_bound" and params["api_key_id"] == "key_u"

    summary_db = _Db(results=[[
        {"group_id": "usr_bound", "external_id": "ext-1", "event_count": 3, "quantity": 45, "cost_estimate_usd": 0.0012},
        {"group_id": None, "external_id": None, "event_count": 1, "quantity": 1, "cost_estimate_usd": None},
    ]])
    summary = api_main.usage_summary(group_by="user", from_ts=1710000000, to_ts=1710003600, limit=200, principal=principal, db=summary_db)
    assert isinstance(summary, UsageSummaryResponse)
    payload = summary.model_dump(mode="json", by_alias=True)
    assert payload["from"] == 1710000000 and payload["to"] == 1710003600
    assert payload["data"][0] == {
        "object": "usage.summary.row", "group_by": "user", "group_id": "usr_bound", "external_id": "ext-1",
        "event_count": 3, "quantity": 45.0, "cost_estimate_usd": 0.0012,
    }
    sql, params = summary_db.calls[0]
    assert "GROUP BY ue.user_id" in sql and "LEFT JOIN users u" in sql
    assert "ue.created_at >= to_timestamp" in sql and "ue.created_at < to_timestamp" in sql
    assert params["from_ts"] == 1710000000 and params["to_ts"] == 1710003600

    by_key = _Db(results=[[]])
    api_main.usage_summary(group_by="api_key", from_ts=None, to_ts=None, limit=200, principal=principal, db=by_key)
    assert "GROUP BY ue.api_key_id" in by_key.calls[0][0] and "LEFT JOIN users" not in by_key.calls[0][0]

    with pytest.raises(HTTPException) as exc:
        api_main.usage_summary(group_by="user", from_ts=10, to_ts=10, limit=200, principal=principal, db=_Db())
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        api_main.usage_summary(group_by="user", from_ts=None, to_ts=None, limit=200, principal=_principal(scopes=["retrieval:read"]), db=_Db())
    assert exc.value.status_code == 403


def test_user_bound_caller_is_forced_to_its_own_usage():
    bound = _principal(user_id="usr_bound", api_key_id="key_u", external_id="ext-1", scopes=["usage:read"])
    db = _Db(results=[[]])
    api_main.usage(limit=10, user_id=None, api_key_id=None, principal=bound, db=db)
    sql, params = db.calls[0]
    assert "AND user_id=:user_id" in sql and params["user_id"] == "usr_bound"
    with pytest.raises(HTTPException) as exc:
        api_main.usage(limit=10, user_id="usr_other", api_key_id=None, principal=bound, db=_Db())
    assert exc.value.status_code == 403 and exc.value.detail["error"] == "user_bound_usage_scope"

    summary_db = _Db(results=[[]])
    api_main.usage_summary(group_by="api_key", from_ts=None, to_ts=None, limit=10, principal=bound, db=summary_db)
    sql, params = summary_db.calls[0]
    assert "AND ue.user_id=:forced_user_id" in sql and params["forced_user_id"] == "usr_bound"

    # Cell keys (no external_id, even with a user_id) keep the unrestricted view.
    cell = _principal(scopes=["usage:read"])
    open_db = _Db(results=[[]])
    api_main.usage_summary(group_by="user", from_ts=None, to_ts=None, limit=10, principal=cell, db=open_db)
    assert "forced_user_id" not in open_db.calls[0][0]
    assert open_db.calls[0][1]["forced_user_id"] is None


def test_resolve_principal_carries_external_id_and_fails_closed_for_deactivated_user():
    key_row = {
        "id": "key_u", "tenant_id": "tenant", "business_instance_id": "biz", "user_id": "usr_bound",
        "scopes": ["retrieval:read"], "max_security_level": 1,
    }
    set_configs = [{}] * 5
    db = _Db(results=[{}, key_row, *set_configs, {"external_id": "ext-1", "status": "active"}, []])
    principal = resolve_api_key_principal(db, "Bearer svs_live_bound")
    assert principal.user_id == "usr_bound" and principal.api_key_id == "key_u"
    assert principal.external_id == "ext-1"
    user_sql = next(sql for sql, _ in db.calls if "FROM users" in sql)
    assert "tenant_id=:tenant_id" in user_sql

    deactivated = _Db(results=[{}, key_row, *set_configs, {"external_id": "ext-1", "status": "deactivated"}])
    with pytest.raises(HTTPException) as exc:
        resolve_api_key_principal(deactivated, "Bearer svs_live_bound")
    assert exc.value.status_code == 401
    assert not any("UPDATE api_keys SET last_used_at" in sql for sql, _ in deactivated.calls)

    # QC: a bound user that cannot be found (RLS edge, cross-instance) never
    # degrades the key into an unbound cell key.
    missing_user = _Db(results=[{}, key_row, *set_configs, None])
    with pytest.raises(HTTPException) as exc:
        resolve_api_key_principal(missing_user, "Bearer svs_live_bound")
    assert exc.value.status_code == 401
    assert "not available" in exc.value.detail
    assert not any("UPDATE api_keys SET last_used_at" in sql for sql, _ in missing_user.calls)

    # A revoked key (post-deactivation) never resolves: the lookup filters on status='active'.
    with pytest.raises(HTTPException) as exc:
        resolve_api_key_principal(_Db(results=[{}, None]), "Bearer svs_live_revoked")
    assert exc.value.status_code == 401


# ------------------------------------------------------ contract, migration, script


def test_openapi_exposes_wave125_routes_and_fields():
    api_main.app.openapi_schema = None
    spec = api_main.app.openapi()
    paths = spec["paths"]
    assert "post" in paths["/api/v1/admin/users"] and "get" in paths["/api/v1/admin/users"]
    assert "post" in paths["/api/v1/admin/users/{user_id}/deactivate"]
    assert "get" in paths["/api/v1/admin/usage/summary"]
    expert_params = {param["name"] for param in paths["/v1/experts"]["get"]["parameters"]}
    assert {"jurisdiction_key", "corpus"} <= expert_params
    key_params = {param["name"] for param in paths["/api/v1/admin/api-keys"]["post"]["parameters"]}
    assert "user_id" in key_params
    usage_params = {param["name"] for param in paths["/api/v1/admin/usage"]["get"]["parameters"]}
    assert {"user_id", "api_key_id"} <= usage_params
    profile_props = spec["components"]["schemas"]["ExpertProfile"]["properties"]
    assert "jurisdiction_key" in profile_props and "corpus" in profile_props
    request_ref = paths["/api/v1/admin/users"]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    assert request_ref.endswith("/AdminUserCreateRequest")


def test_alembic_revision_adds_caller_identity_columns():
    path = ROOT / "migrations" / "versions" / "004_wave125_caller_identity.py"
    body = path.read_text(encoding="utf-8")
    assert 'revision = "004_wave125_caller_identity"' in body
    assert 'down_revision = "003_expert_conversation_sessions"' in body
    for fragment in (
        "CHECK (business_instance_id IS NULL OR external_id IS NOT NULL)",
        "DROP CONSTRAINT IF EXISTS users_instance_user_has_external_id",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS external_id TEXT",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS business_instance_id TEXT",
        "ALTER TABLE users ALTER COLUMN email DROP NOT NULL",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_tenant_external_id",
        "ON users(tenant_id, external_id)",
        "ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS api_key_id TEXT",
        "ALTER TABLE rate_limit_counters ADD COLUMN IF NOT EXISTS api_key_id TEXT",
        "ALTER TABLE rate_limit_counters ADD COLUMN IF NOT EXISTS user_id TEXT",
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE %I TO %I",
    ):
        assert fragment in body, fragment
    assert "def downgrade" in body
    assert "ALTER TABLE users ALTER COLUMN email SET NOT NULL" in body
    # Legacy db/migrations stay frozen; the drift checker owns that manifest.
    assert not (ROOT / "db" / "migrations" / "009_wave125_caller_identity.sql").exists()


def _load_migration_004():
    path = ROOT / "migrations" / "versions" / "004_wave125_caller_identity.py"
    spec = importlib.util.spec_from_file_location("wave125_migration_004", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["wave125_migration_004"] = module
    spec.loader.exec_module(module)
    return module


def test_upgrade_adds_structural_user_bound_discriminator(monkeypatch):
    module = _load_migration_004()

    class _Conn:
        def __init__(self):
            self.executed = []

        def execute(self, stmt, params=None):
            # _formatted() asks Postgres to render GRANT statements; echo the template.
            return SimpleNamespace(scalar_one=lambda: str(params.get("template", "")) if params else "")

        def exec_driver_sql(self, sql):
            self.executed.append(str(sql))

    conn = _Conn()
    monkeypatch.setattr(module, "op", SimpleNamespace(get_bind=lambda: conn))
    module.upgrade()
    schema_sql = "\n".join(conn.executed)
    assert "ADD CONSTRAINT users_instance_user_has_external_id" in schema_sql
    assert "CHECK (business_instance_id IS NULL OR external_id IS NOT NULL)" in schema_sql
    assert "ADD COLUMN IF NOT EXISTS external_id TEXT" in schema_sql
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE %I TO %I" in schema_sql

    dropped = _Conn()
    monkeypatch.setattr(module, "op", SimpleNamespace(get_bind=lambda: dropped))
    dropped.execute = lambda stmt, params=None: SimpleNamespace(scalar_one=lambda: 0)
    module.downgrade()
    assert any("DROP CONSTRAINT IF EXISTS users_instance_user_has_external_id" in sql for sql in dropped.executed)


def test_downgrade_restores_email_not_null_and_refuses_null_emails(monkeypatch):
    module = _load_migration_004()

    class _Conn:
        def __init__(self, null_emails):
            self.null_emails = null_emails
            self.executed = []

        def execute(self, stmt, params=None):
            self.executed.append(str(stmt))
            return SimpleNamespace(scalar_one=lambda: self.null_emails)

        def exec_driver_sql(self, sql):
            self.executed.append(sql)

    dirty = _Conn(2)
    monkeypatch.setattr(module, "op", SimpleNamespace(get_bind=lambda: dirty))
    with pytest.raises(RuntimeError) as exc:
        module.downgrade()
    assert "2 users row(s) have NULL email" in str(exc.value)
    assert not any("SET NOT NULL" in sql for sql in dirty.executed)

    clean = _Conn(0)
    monkeypatch.setattr(module, "op", SimpleNamespace(get_bind=lambda: clean))
    module.downgrade()
    assert any("ALTER TABLE users ALTER COLUMN email SET NOT NULL" in sql for sql in clean.executed)
    assert any("DROP COLUMN IF EXISTS external_id" in sql for sql in clean.executed)


def _load_cell_access_proof():
    script = ROOT / "scripts" / "release" / "cell-access-proof.py"
    sys.path.insert(0, str(script.parent))
    spec = importlib.util.spec_from_file_location("cell_access_proof_wave125", script)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules["cell_access_proof_wave125"] = module
    spec.loader.exec_module(module)
    return module


def test_cell_access_proof_attribution_path_uses_user_key_for_message_and_admin_key_for_usage(monkeypatch):
    module = _load_cell_access_proof()
    calls = []

    def fake_request(method, url, token, payload=None, *, timeout=60):
        calls.append((method, url, token, payload))
        if url.endswith("/api/v1/admin/users"):
            return 200, {"id": "usr_proof", "external_id": payload["external_id"]}
        if "/api/v1/admin/api-keys?" in url:
            return 200, {"id": "key_proof", "api_key": "svs_live_proof_secret", "scopes": ["retrieval:read"], "user_id": "usr_proof"}
        if "/messages" in url:
            assert token == "svs_live_proof_secret"
            return 200, {"session_id": "exps_proof"}
        if "/api/v1/admin/usage?" in url:
            assert token == "admin_secret"
            return 200, {"data": [{"event_type": "expert.message", "user_id": "usr_proof", "api_key_id": "key_proof"}]}
        if "/api/v1/admin/usage/summary" in url:
            return 200, {"data": [{"group_id": "usr_proof", "quantity": 15}]}
        if method == "DELETE":
            return 200, {"deleted": True}
        raise AssertionError(url)

    monkeypatch.setattr(module, "_json_request", fake_request)
    result = module.attribution_proof("http://localhost:18080/", "admin_secret", external_user_id="ext-proof")
    assert result["user_id"] == "usr_proof" and result["api_key_id"] == "key_proof"
    assert result["usage_rows_attributed"] == 1 and result["summary_user_rows"] == 1
    assert result["key_revoked"] is True
    assert "svs_live_proof_secret" not in str(result)
    methods = [call[0] for call in calls]
    assert methods == ["POST", "POST", "POST", "GET", "GET", "DELETE"]
    lines = module.attribution_lines(result)
    assert "ATTRIBUTION_USER_ID=usr_proof" in lines
    assert "ATTRIBUTION_USAGE_ROWS_ATTRIBUTED=1" in lines
    assert "ATTRIBUTION_USAGE_EVENT_TYPES=expert.message" in lines
