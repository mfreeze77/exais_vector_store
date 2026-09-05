"""Synthetic-only contract tests; no provider, publisher or canonical DB calls."""

from __future__ import annotations

import asyncio
import copy
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from fastapi import HTTPException
from svs_api import main as api_main
from svs_common.cell_graph import (
    cell_graph_profile_for_store,
    configured_cell_graph_profile,
)
from svs_common.grant_graph import (
    GRANT_CORPUS_KIND,
    GRANT_GRAPH_HANDLER_ID,
    GRANT_RELATIONS,
    expand_grant_graph,
    validate_grant_graph,
)
from svs_common.openai_compat import OpenAICompatError
from svs_common.schemas import (
    ChunkRecord,
    OpenAIVectorStoreSearchRequest,
    Principal,
    SearchResponse,
    VectorStoreGraphLoadRequest,
)
from svs_common.search_lenses import (
    infer_expert_search_lens_id,
    search_lenses_for_vector_store,
)

STORE = "vs_grant_test"
PROFILE_ID = "grant-intelligence.public-evidence.v1"
ATTRS = {"corpus": GRANT_CORPUS_KIND, "graph_profile_id": PROFILE_ID}
PRINCIPAL = Principal(
    tenant_id="public",
    business_instance_id="grant-intelligence",
    max_security_level=0,
    scopes=["retrieval:read"],
)


def profile_payload():
    return {
        "schema_version": "svs.cell-graph.v1",
        "profile_id": PROFILE_ID,
        "handler_id": GRANT_GRAPH_HANDLER_ID,
        "corpus_kind": GRANT_CORPUS_KIND,
        "binding": {
            "tenant_id": "public",
            "business_instance_id": "grant-intelligence",
            "vector_store_ids": [STORE],
        },
        "enabled": True,
        "max_expansions": 3,
        "max_hops": 1,
    }


@pytest.fixture
def bound_profile(tmp_path, monkeypatch):
    path = tmp_path / "graph.yaml"
    path.write_text(yaml.safe_dump(profile_payload()))
    monkeypatch.setenv("SVS_CELL_GRAPH_PROFILE_PATH", str(path))
    return path


def graph_payload():
    generation = str(uuid4())
    nodes = []
    for kind in ("award", "project"):
        document_id = str(uuid4())
        nodes.append(
            {
                "id": f"gip:{STORE}:{generation}:{document_id}",
                "type": kind,
                "attributes": {
                    "gip_generation_id": generation,
                    "gip_search_document_id": document_id,
                    "gip_entity_id": str(uuid4()),
                    "gip_source_version_sha256": "a" * 64,
                    "gip_citation_id": f"gip:{kind}:{document_id}:aaaaaaaaaaaaaaaa",
                    "visibility": "public",
                },
            }
        )
    relationship = str(uuid4())
    return {
        "nodes": nodes,
        "edges": [
            {
                "id": f"gip:{STORE}:{generation}:edge:{relationship}",
                "type": "funds",
                "source": nodes[0]["id"],
                "target": nodes[1]["id"],
                "attributes": {
                    "gip_generation_id": generation,
                    "gip_relationship_id": relationship,
                    "gip_relationship_sha256": "b" * 64,
                    "review_status": "accepted",
                    "visibility": "public",
                    "evidence_citation_ids": [
                        nodes[0]["attributes"]["gip_citation_id"]
                    ],
                },
            }
        ],
        "replace": False,
        "dry_run": True,
    }


def chunk(identifier="seed", **overrides):
    return ChunkRecord(
        **{
            "id": f"chunk_{identifier}",
            "document_id": f"doc_{identifier}",
            "ordinal": 0,
            "text": "Synthetic public evidence",
            "security_level": 0,
            "classification": "public",
            "score": 0.8,
            "citation": {"file_id": f"doc_{identifier}", "type": "file_citation"},
            **overrides,
        }
    )


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class Db:
    def __init__(self, rows=()):
        self.rows, self.calls, self.committed = list(rows), [], False

    def execute(self, statement, parameters):
        self.calls.append((str(statement), parameters))
        return Rows(self.rows)

    def commit(self):
        self.committed = True


def test_profile_unset_means_disabled(monkeypatch):
    monkeypatch.delenv("SVS_CELL_GRAPH_PROFILE_PATH", raising=False)
    assert configured_cell_graph_profile() is None
    assert not api_main._graphrag_enabled_for_vector_store(ATTRS, None)


def test_checked_in_profile_is_explicitly_grant_bound_and_disabled():
    path = (
        Path(__file__).resolve().parents[1]
        / "instances/grant-intelligence/graph/profile.yaml"
    )
    data = yaml.safe_load(path.read_text())
    assert data["binding"]["business_instance_id"] == "grant-intelligence"
    assert data["enabled"] is False
    assert data["max_hops"] == 1


def test_exact_profile_binding(bound_profile):
    profile = cell_graph_profile_for_store(PRINCIPAL, STORE, ATTRS)
    assert profile and profile.enabled
    assert api_main._graphrag_enabled_for_vector_store(
        ATTRS, None, cell_profile=profile
    )


@pytest.mark.parametrize(
    "change", ["tenant", "business", "store", "corpus", "profile", "missing_profile"]
)
def test_another_cell_or_tag_cannot_select_grant_profile(bound_profile, change):
    principal, store, attrs = PRINCIPAL.model_copy(), STORE, dict(ATTRS)
    if change == "tenant":
        principal.tenant_id = "other"
    elif change == "business":
        principal.business_instance_id = "ks-state-civics"
    elif change == "store":
        store = "vs_other"
    elif change == "missing_profile":
        attrs.pop("graph_profile_id")
    else:
        attrs[change if change == "corpus" else "graph_profile_id"] = "other"
    assert cell_graph_profile_for_store(principal, store, attrs) is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("handler_id", "arbitrary.module:execute"),
        ("corpus_kind", "topeka_municipal_code"),
        ("enabled", "true"),
        ("max_expansions", True),
        ("max_expansions", 11),
        ("max_hops", 2),
        ("extra_secret", "never-echo-this"),
    ],
)
def test_invalid_profile_fails_closed_without_echoing_config(
    bound_profile, field, value
):
    payload = profile_payload()
    payload[field] = value
    bound_profile.write_text(yaml.safe_dump(payload))
    with pytest.raises(ValueError, match="invalid or unavailable") as error:
        configured_cell_graph_profile()
    assert str(value) not in str(error.value) or value in (True, 2, 11)
    with pytest.raises(HTTPException) as api_error:
        api_main._cell_graph_profile_or_503(ATTRS, PRINCIPAL, STORE)
    assert api_error.value.status_code == 503
    # An unrelated legacy civics corpus must not read this new manifest.
    assert (
        api_main._cell_graph_profile_or_503(
            {"corpus": "topeka_municipal_code"}, PRINCIPAL, "vs_topeka"
        )
        is None
    )


def test_graph_structural_contract_accepts_bound_synthetic_artifact():
    validate_grant_graph(VectorStoreGraphLoadRequest(**graph_payload()), STORE)


@pytest.mark.parametrize(
    "case",
    [
        "private_node",
        "private_edge",
        "unreviewed_edge",
        "bad_source_hash",
        "bad_edge_hash",
        "wrong_store",
        "mixed_generation",
        "dangling",
        "legal_relation",
        "legal_node",
        "duplicate_node",
        "duplicate_edge",
        "missing_evidence",
        "unbound_evidence",
        "unknown_attribute",
        "uncontrolled_provenance",
        "extra_payload",
    ],
)
def test_graph_load_rejects_unbound_or_unsafe_declarations(case):
    payload = graph_payload()
    node, edge = payload["nodes"][0], payload["edges"][0]
    if case == "private_node":
        node["attributes"]["visibility"] = "private"
    elif case == "private_edge":
        edge["attributes"]["visibility"] = "private"
    elif case == "unreviewed_edge":
        edge["attributes"]["review_status"] = "candidate"
    elif case == "bad_source_hash":
        node["attributes"]["gip_source_version_sha256"] = "bad"
    elif case == "bad_edge_hash":
        edge["attributes"]["gip_relationship_sha256"] = "bad"
    elif case == "wrong_store":
        node["id"] = node["id"].replace(STORE, "vs_other")
    elif case == "mixed_generation":
        replacement = str(uuid4())
        node["id"] = node["id"].replace(
            node["attributes"]["gip_generation_id"], replacement
        )
        node["attributes"]["gip_generation_id"] = replacement
    elif case == "dangling":
        edge["target"] = "absent"
    elif case == "legal_relation":
        edge["type"] = "cited_by"
    elif case == "legal_node":
        node["type"] = "court_opinion"
    elif case == "duplicate_node":
        payload["nodes"].append(copy.deepcopy(node))
    elif case == "duplicate_edge":
        payload["edges"].append(copy.deepcopy(edge))
    elif case == "missing_evidence":
        edge["attributes"]["evidence_citation_ids"] = []
    elif case == "unbound_evidence":
        edge["attributes"]["evidence_citation_ids"] = ["not-loaded"]
    elif case == "unknown_attribute":
        node["attributes"]["secret"] = "not_allowed"
    elif case == "uncontrolled_provenance":
        edge["provenance"] = {"unreviewed": True}
    elif case == "extra_payload":
        node["arbitrary"] = "not_allowed"
    with pytest.raises(ValueError):
        validate_grant_graph(VectorStoreGraphLoadRequest(**payload), STORE)


@pytest.mark.parametrize(
    "filters",
    [
        {},
        {"file_attribute_filters": {"gip_generation_id": "wrong"}},
        {"file_attribute_filter_any": [{"gip_generation_id": str(uuid4())}]},
    ],
)
def test_expansion_requires_one_exact_generation_before_graph_query(filters):
    db = Db()
    with pytest.raises(ValueError):
        expand_grant_graph(
            db,
            PRINCIPAL,
            STORE,
            [chunk()],
            filters=filters,
            relation_types=GRANT_RELATIONS,
            limit=3,
            hydrate=lambda *args, **kw: [],
        )
    assert not db.calls


def test_expansion_reuses_acl_hydration_filters_bounds_and_citations():
    payload = graph_payload()
    edge = payload["edges"][0]
    attrs = edge["attributes"]
    filters = {
        "vector_store_id": "cannot_override",
        "file_attribute_filters": {
            "gip_generation_id": attrs["gip_generation_id"],
            "state_code": "KS",
        },
    }
    rows = [
        {
            "chunk_id": f"chunk_{name}",
            "document_id": f"doc_{name}",
            "edge_id": edge["id"],
            "edge_type": edge["type"],
            "source_node_id": edge["source"],
            "target_node_id": edge["target"],
            "edge_attributes": attrs,
        }
        for name in ("related", "private", "seed", "filtered_out")
    ]
    db, calls = Db(rows), []
    related = chunk("related")
    original_citation = copy.deepcopy(related.citation)

    def hydrate(*args, **kwargs):
        calls.append((args, kwargs))
        return [related, chunk("private", security_level=1), chunk("seed")]

    additions, metadata, summary = expand_grant_graph(
        db,
        PRINCIPAL,
        STORE,
        [chunk()],
        filters=filters,
        relation_types=("funds",),
        limit=3,
        hydrate=hydrate,
    )
    assert [value.id for value in additions] == ["chunk_related"]
    assert related.citation == original_citation
    assert metadata[related.id]["relationship_sha256"] == "b" * 64
    assert (
        metadata[related.id]["evidence_citation_ids"] == attrs["evidence_citation_ids"]
    )
    assert summary["inserted_chunk_count"] == 1
    assert calls[0][1]["filters"] == {**filters, "vector_store_id": STORE}
    sql, params = db.calls[0]
    assert params["candidate_limit"] == 60
    assert (
        params["tenant_id"] == PRINCIPAL.tenant_id
        and params["biz_id"] == PRINCIPAL.business_instance_id
    )
    assert params["generation"] == attrs["gip_generation_id"] and params[
        "relations"
    ] == ["funds"]
    assert "c.document_version_id=d.current_version_id" in sql
    assert "c.security_level=0 AND c.classification='public'" in sql
    assert sql.count("gip_source_version_sha256'") >= 4
    assert sql.count("gip_citation_id'") >= 4


def test_zero_expansion_limit_does_not_query():
    db = Db()
    result = expand_grant_graph(
        db,
        PRINCIPAL,
        STORE,
        [chunk()],
        filters={"file_attribute_filters": {"gip_generation_id": str(uuid4())}},
        relation_types=GRANT_RELATIONS,
        limit=0,
        hydrate=lambda *args, **kw: pytest.fail("hydrate called"),
    )
    assert result[0] == [] and not db.calls


@pytest.mark.parametrize(
    "key", ["document_id", "knowledge_base_id", "classification", "acl_bucket"]
)
def test_chunk_column_filters_are_applied_before_candidate_limit(key):
    db = Db()
    filters = {
        "file_attribute_filters": {"gip_generation_id": str(uuid4())},
        key: "restricted_identity",
    }
    expand_grant_graph(
        db,
        PRINCIPAL,
        STORE,
        [chunk()],
        filters=filters,
        relation_types=GRANT_RELATIONS,
        limit=3,
        hydrate=lambda *args, **kw: [],
    )
    sql, params = db.calls[0]
    assert params[f"filter_{key}"] == "restricted_identity"
    assert f"c.{key}=:filter_{key}" in sql


def test_lens_is_grant_only_explicit_and_reports_empty():
    lenses = search_lenses_for_vector_store(
        ATTRS, query_planner_profile_id=None, graph_enabled=True, graph_coverage={}
    )
    assert [value["id"] for value in lenses] == ["semantic", "grant_evidence"]
    assert lenses[1]["status"] == "empty"
    for corpus in ("kansas_court_decisions", "topeka_municipal_code", "unknown"):
        lenses = search_lenses_for_vector_store(
            {"corpus": corpus}, query_planner_profile_id=None, graph_enabled=True
        )
        assert "grant_evidence" not in [value["id"] for value in lenses]
    assert (
        infer_expert_search_lens_id("follow grant funding evidence", ["grant_evidence"])
        is None
    )


def route_setup(monkeypatch):
    monkeypatch.setattr(
        api_main, "_refresh_vector_store_activity_or_404", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        api_main, "_vector_store_attributes_for_search", lambda *args: ATTRS
    )
    monkeypatch.setattr(
        api_main,
        "_graph_coverage_for_vector_store",
        lambda *args: {"node_count": 2, "edge_count": 1},
    )
    monkeypatch.setattr(
        api_main,
        "_vector_store_file_lookup",
        lambda db, principal, store, ids: {
            identifier: {"file_id": identifier} for identifier in ids
        },
    )

    async def search(db, principal, req):
        return SearchResponse(query=req.query, results=[chunk()])

    monkeypatch.setattr(api_main.retrieval, "search", search)


def test_explicit_grant_route_dispatch_preserves_filters_and_caps(
    bound_profile, monkeypatch
):
    route_setup(monkeypatch)
    generation, calls = str(uuid4()), []

    def expand(*args, **kwargs):
        calls.append(kwargs)
        return [chunk("related")], {}, {"applied": True}

    monkeypatch.setattr(api_main, "expand_grant_graph", expand)
    req = OpenAIVectorStoreSearchRequest(
        query="grant funding",
        lens="grant_evidence",
        filters={"gip_generation_id": generation, "state_code": "KS"},
    ).bind_graph_expansion_limit(9)
    page = asyncio.run(
        api_main._openai_vector_store_search_page(STORE, req, PRINCIPAL, Db())
    )
    assert calls[0]["limit"] == 3
    assert calls[0]["filters"] == {
        "vector_store_id": STORE,
        "file_attribute_filters": {"gip_generation_id": generation, "state_code": "KS"},
    }
    assert calls[0]["hydrate"] == api_main.retrieval._hydrate_and_acl
    assert page["graph_expansion"]["cell_profile_id"] == PROFILE_ID
    assert page["search_lens"]["source"] == "explicit"


def test_semantic_default_never_auto_expands_grant(bound_profile, monkeypatch):
    route_setup(monkeypatch)
    monkeypatch.setattr(
        api_main,
        "expand_grant_graph",
        lambda *args, **kwargs: pytest.fail("implicit Grant graph"),
    )
    page = asyncio.run(
        api_main._openai_vector_store_search_page(
            STORE,
            OpenAIVectorStoreSearchRequest(query="grant funding graph"),
            PRINCIPAL,
            Db(),
        )
    )
    assert "graph_expansion" not in page


def test_grant_route_rejects_missing_generation(bound_profile, monkeypatch):
    route_setup(monkeypatch)
    with pytest.raises(OpenAICompatError, match="UUID"):
        asyncio.run(
            api_main._openai_vector_store_search_page(
                STORE,
                OpenAIVectorStoreSearchRequest(query="grant", lens="grant_evidence"),
                PRINCIPAL,
                Db(),
            )
        )


def test_graph_loader_validates_before_write_and_honors_dry_run(
    bound_profile, monkeypatch
):
    route_setup(monkeypatch)
    monkeypatch.setattr(api_main, "enforce_rate_limit", lambda *args: None)
    operator = PRINCIPAL.model_copy(update={"scopes": ["vector_stores:write"]})
    calls = []
    monkeypatch.setattr(
        api_main,
        "_load_vector_store_graph",
        lambda *args: calls.append(args) or {"status": "dry_run"},
    )
    db = Db()
    api_main.load_vector_store_graph(
        STORE, VectorStoreGraphLoadRequest(**graph_payload()), operator, db
    )
    assert len(calls) == 1 and not db.committed
    payload = graph_payload()
    payload["edges"][0]["attributes"]["review_status"] = "candidate"
    with pytest.raises(HTTPException) as error:
        api_main.load_vector_store_graph(
            STORE, VectorStoreGraphLoadRequest(**payload), operator, db
        )
    assert error.value.status_code == 422 and len(calls) == 1
    with pytest.raises(HTTPException) as error:
        api_main.load_vector_store_graph(
            STORE, VectorStoreGraphLoadRequest(**graph_payload()), PRINCIPAL, db
        )
    assert error.value.status_code == 403 and len(calls) == 1


def test_missing_cell_binding_rejects_graph_load(monkeypatch):
    route_setup(monkeypatch)
    monkeypatch.delenv("SVS_CELL_GRAPH_PROFILE_PATH", raising=False)
    monkeypatch.setattr(api_main, "enforce_rate_limit", lambda *args: None)
    monkeypatch.setattr(
        api_main, "_load_vector_store_graph", lambda *args: pytest.fail("unbound write")
    )
    operator = PRINCIPAL.model_copy(update={"scopes": ["vector_stores:write"]})
    with pytest.raises(HTTPException) as error:
        api_main.load_vector_store_graph(
            STORE, VectorStoreGraphLoadRequest(**graph_payload()), operator, Db()
        )
    assert error.value.status_code == 422
