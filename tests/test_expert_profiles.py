from __future__ import annotations

import pytest
from fastapi import HTTPException

from svs_api import main as api_main
import svs_common.expert_profiles as expert_profiles
from svs_common.expert_profiles import (
    ExpertProfileDefinition,
    ExpertProfileNotFoundError,
    ExpertVectorStoreBindingDefinition,
    list_expert_profiles,
    resolve_expert_profile,
)
from svs_common.schemas import (
    ExpertCitationPolicy,
    ExpertModelPolicy,
    ExpertProfileListResponse,
    ExpertToolLimits,
    Principal,
)


class _Rows:
    def __init__(self, row=None):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row


class _Db:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls: list[tuple[str, dict]] = []

    def execute(self, stmt, params=None):
        self.calls.append((str(stmt), dict(params or {})))
        row = self.results.pop(0) if self.results else None
        return _Rows(row)


def _principal(*, tenant_id: str = "tenant_a", business_instance_id: str = "biz_a", scopes=None) -> Principal:
    return Principal(
        tenant_id=tenant_id,
        business_instance_id=business_instance_id,
        user_id="user_a",
        api_key_id="key_a",
        scopes=list(scopes if scopes is not None else ["retrieval:read"]),
    )


def _definition(
    *,
    expert_id: str = "test-court-expert",
    vector_store_id: str = "vs_courts",
    tenant_id: str = "tenant_a",
    business_instance_id: str = "biz_a",
    allowed_graph_lens_ids: tuple[str, ...] = ("court_citator",),
) -> ExpertProfileDefinition:
    return ExpertProfileDefinition(
        id=expert_id,
        label="Test Court Expert",
        description="A fixture-backed court expert.",
        system_prompt="Use retrieved court sources only.",
        vector_store_bindings=(
            ExpertVectorStoreBindingDefinition(
                vector_store_id=vector_store_id,
                tenant_id=tenant_id,
                business_instance_id=business_instance_id,
                allowed_graph_lens_ids=allowed_graph_lens_ids,
            ),
        ),
        citation_policy=ExpertCitationPolicy(),
        caveats=("Fixture caveat.",),
        model_policy=ExpertModelPolicy(policy_id="fixture_expert_v1"),
        tool_limits=ExpertToolLimits(
            max_retrieval_runs=2,
            max_results_per_run=8,
            max_graph_expansions=2,
            max_context_tokens=4000,
        ),
    )


def _active_store_results(
    *,
    vector_store_id: str = "vs_courts",
    name: str = "Court fixture",
    attributes: dict | None = None,
) -> list[dict]:
    return [
        {"id": vector_store_id, "status": "completed", "is_expired": False},
        {
            "id": vector_store_id,
            "name": name,
            "status": "completed",
            "usage_bytes": 0,
            "attributes": attributes or {"corpus": "kansas_court_decisions"},
            "expires_after": None,
            "created_at": 1,
            "expires_at": None,
            "last_active_at": 1,
            "file_counts": {},
        },
    ]


def test_resolve_expert_profile_is_principal_scoped_and_composes_search_lens_registry(monkeypatch):
    monkeypatch.setattr(expert_profiles, "EXPERT_PROFILE_REGISTRY", (_definition(),))
    db = _Db(_active_store_results())

    profile = resolve_expert_profile(db, _principal(), " TEST-COURT-EXPERT ")

    assert profile.id == "test-court-expert"
    assert profile.object == "expert.profile"
    assert [store.vector_store_id for store in profile.vector_stores] == ["vs_courts"]
    assert profile.vector_stores[0].corpus_kind == "kansas_court_decisions"
    assert [lens.id for lens in profile.vector_stores[0].graph_lenses] == ["court_citator"]
    assert profile.vector_stores[0].graph_lenses[0].relation_types == [
        "cited_by",
        "cited_authority",
        "same_docket",
        "related_party",
    ]
    assert profile.graph_lens_policy.allowed_lens_ids == ["court_citator"]
    assert profile.citation_policy.authority == "retrieved_corpus_only"
    assert profile.citation_policy.memory_is_authority is False
    assert profile.model_policy.gateway == "model_gateway"

    assert len(db.calls) == 2
    for sql, params in db.calls:
        compact_sql = " ".join(sql.split())
        assert "tenant_id=:tenant_id" in compact_sql
        assert "business_instance_id=:biz_id" in compact_sql
        assert params["tenant_id"] == "tenant_a"
        assert params["biz_id"] == "biz_a"
        assert params["id"] == "vs_courts"


def test_cross_scope_profile_fails_before_any_store_retrieval_or_model_work(monkeypatch):
    monkeypatch.setattr(
        expert_profiles,
        "EXPERT_PROFILE_REGISTRY",
        (_definition(tenant_id="tenant_other", business_instance_id="biz_other"),),
    )
    db = _Db()

    with pytest.raises(ExpertProfileNotFoundError, match="Expert profile not found"):
        resolve_expert_profile(db, _principal(), "test-court-expert")

    assert db.calls == []


def test_missing_or_expired_store_binding_fails_closed_before_store_hydration(monkeypatch):
    monkeypatch.setattr(expert_profiles, "EXPERT_PROFILE_REGISTRY", (_definition(),))
    db = _Db([None])

    with pytest.raises(ExpertProfileNotFoundError, match="Expert profile not found"):
        resolve_expert_profile(db, _principal(), "test-court-expert")

    assert len(db.calls) == 1
    assert "status != 'deleted'" in db.calls[0][0]


def test_profile_rejects_lenses_not_supported_by_bound_store(monkeypatch):
    monkeypatch.setattr(
        expert_profiles,
        "EXPERT_PROFILE_REGISTRY",
        (_definition(allowed_graph_lens_ids=("municipal_code_history",)),),
    )
    db = _Db(_active_store_results())

    with pytest.raises(expert_profiles.ExpertProfileConfigurationError):
        resolve_expert_profile(db, _principal(), "test-court-expert")


def test_list_expert_profiles_omits_profiles_outside_principal_scope(monkeypatch):
    visible = _definition(expert_id="visible")
    hidden = _definition(expert_id="hidden", tenant_id="tenant_other")
    monkeypatch.setattr(expert_profiles, "EXPERT_PROFILE_REGISTRY", (visible, hidden))
    db = _Db(_active_store_results())

    response = list_expert_profiles(db, _principal())

    assert isinstance(response, ExpertProfileListResponse)
    assert [profile.id for profile in response.data] == ["visible"]
    assert response.first_id == response.last_id == "visible"
    assert response.has_more is False
    assert len(db.calls) == 2


def test_expert_routes_require_retrieval_scope_and_hide_unavailable_profiles(monkeypatch):
    monkeypatch.setattr(api_main, "enforce_rate_limit", lambda *args, **kwargs: None)

    with pytest.raises(HTTPException) as scope_error:
        api_main.list_experts(principal=_principal(scopes=[]), db=object())
    assert scope_error.value.status_code == 403

    monkeypatch.setattr(
        api_main,
        "resolve_expert_profile",
        lambda *args, **kwargs: (_ for _ in ()).throw(ExpertProfileNotFoundError("hidden")),
    )
    with pytest.raises(HTTPException) as missing_error:
        api_main.get_expert_profile("hidden", principal=_principal(), db=object())
    assert missing_error.value.status_code == 404
    assert missing_error.value.detail == "Expert profile not found"


def test_expert_discovery_openapi_uses_named_response_components():
    api_main.app.openapi_schema = None
    spec = api_main.app.openapi()

    list_ref = spec["paths"]["/v1/experts"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    detail_ref = spec["paths"]["/v1/experts/{expert_id}"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert list_ref.endswith("/ExpertProfileListResponse")
    assert detail_ref.endswith("/ExpertProfile")
    assert "ExpertVectorStoreBinding" in spec["components"]["schemas"]
    assert "ExpertGraphLens" in spec["components"]["schemas"]
