from __future__ import annotations

from copy import deepcopy
from uuid import uuid4

import pytest

from fiscal_graph_test_support import chunk_for_node, graph_payload


from svs_common.fiscal_graph import (
    FISCAL_RELATIONS,
    expand_fiscal_graph,
    fiscal_edge_id,
    fiscal_node_id,
    fiscal_search_run_id,
    validate_fiscal_graph,
    validate_fiscal_graph_bindings,
)
from svs_common.schemas import Principal, VectorStoreGraphLoadRequest


STORE = "vs_fiscal_test"


@pytest.mark.parametrize('kind', ['nodes', 'edges'])
def test_nonstring_artifact_class_refused_cleanly(kind):
    payload = graph_payload()
    payload[kind][0]['attributes']['fiscal_artifact_class'] = {}
    with pytest.raises(ValueError):
        validate_fiscal_graph(VectorStoreGraphLoadRequest(**payload), STORE)


def request(payload=None):
    return VectorStoreGraphLoadRequest(**(payload or graph_payload()))


def reidentify_node(payload, index):
    node = payload["nodes"][index]
    old = node["id"]
    node["id"] = fiscal_node_id(STORE, node["type"], node["attributes"])
    for edge in payload["edges"]:
        if edge["source"] == old:
            edge["source"] = node["id"]
        if edge["target"] == old:
            edge["target"] = node["id"]


def reidentify_edges(payload):
    for edge in payload["edges"]:
        edge["id"] = fiscal_edge_id(STORE, edge["type"], edge["source"], edge["target"], edge["attributes"])


def test_complete_six_node_five_relation_fixture_validates():
    result = validate_fiscal_graph(request(), STORE)
    assert result == {"derivation_run_id": graph_payload()["nodes"][0]["attributes"]["fiscal_derivation_run_id"],
                      "artifact_class": "reviewed_public", "nodes": 6, "edges": 5}
    assert {edge["type"] for edge in graph_payload()["edges"]} == set(FISCAL_RELATIONS)


def test_empty_artifacts_are_rejected():
    with pytest.raises(ValueError, match="require nodes and edges"):
        validate_fiscal_graph(VectorStoreGraphLoadRequest(nodes=[], edges=[]), STORE)


def test_deterministic_ids_cover_type_direction_and_all_attributes():
    payload = graph_payload()
    node = payload["nodes"][0]
    changed = deepcopy(node["attributes"]); changed["fiscal_year"] = 2027
    assert fiscal_node_id(STORE, node["type"], changed) != node["id"]
    edge = payload["edges"][0]
    assert fiscal_edge_id(STORE, edge["type"], edge["target"], edge["source"], edge["attributes"]) != edge["id"]


@pytest.mark.parametrize("mutation,match", [
    (lambda p: p["nodes"][0]["attributes"].update(extra=True), "attributes"),
    (lambda p: p["nodes"][0].update(key="forbidden"), "attributes"),
    (lambda p: p["nodes"][0]["attributes"].update(fiscal_source_span_id=None), "UUID"),
    (lambda p: p["nodes"][0]["attributes"].update(fiscal_source_content_hash_sha256="A" * 64), "SHA-256"),
    (lambda p: p["nodes"][0]["attributes"].update(fiscal_source_content_hash_sha256=1), "SHA-256"),
    (lambda p: p["nodes"][0]["attributes"].update(fiscal_year=True), "fiscal_year"),
    (lambda p: p["edges"][0]["attributes"].update(fiscal_publication_allowed=False), "publication-allowed"),
    (lambda p: p["edges"][0]["attributes"].update(fiscal_review_status="candidate"), "publication-allowed"),
    (lambda p: p["edges"][0]["attributes"].update(evidence_citation_ids=[]), "evidence"),
    (lambda p: p["edges"][0]["attributes"].update(evidence_citation_ids=[{}]), "evidence"),
])
def test_malformed_or_unpublished_assertions_fail_closed(mutation, match):
    payload = graph_payload(); mutation(payload)
    with pytest.raises(ValueError, match=match):
        validate_fiscal_graph(request(payload), STORE)


def test_wrong_direction_and_mixed_year_fail_closed():
    payload = graph_payload(); edge = payload["edges"][0]
    edge["source"], edge["target"] = edge["target"], edge["source"]
    reidentify_edges(payload)
    with pytest.raises(ValueError, match="endpoint"):
        validate_fiscal_graph(request(payload), STORE)


def test_edge_year_requires_strict_integer():
    payload = graph_payload(); payload["edges"][0]["attributes"]["fiscal_year"] = 2026.0
    reidentify_edges(payload)
    with pytest.raises(ValueError, match="integer"):
        validate_fiscal_graph(request(payload), STORE)


def test_type_specific_entity_identities_and_span_binding_are_strict():
    payload = graph_payload(); payload["nodes"][0]["attributes"]["fiscal_entity_id"] = str(uuid4())
    reidentify_node(payload, 0); reidentify_edges(payload)
    with pytest.raises(ValueError, match="provision identity"):
        validate_fiscal_graph(request(payload), STORE)
    payload = graph_payload(); payload["nodes"][5]["attributes"]["fiscal_entity_id"] = str(uuid4())
    reidentify_node(payload, 5); reidentify_edges(payload)
    with pytest.raises(ValueError, match="document identity"):
        validate_fiscal_graph(request(payload), STORE)
    payload = graph_payload()
    payload["nodes"][1]["attributes"]["fiscal_source_span_id"] = payload["nodes"][0]["attributes"]["fiscal_source_span_id"]
    reidentify_node(payload, 1); reidentify_edges(payload)
    with pytest.raises(ValueError, match="consistent"):
        validate_fiscal_graph(request(payload), STORE)
    payload = graph_payload(); payload["nodes"][1]["attributes"]["fiscal_year"] = 2027
    reidentify_node(payload, 1); reidentify_edges(payload)
    with pytest.raises(ValueError, match="fiscal year"):
        validate_fiscal_graph(request(payload), STORE)


def test_runtime_rejects_fixture_but_isolated_validation_can_accept_it():
    payload = graph_payload(artifact_class="fixture_only")
    with pytest.raises(ValueError, match="fixture"):
        validate_fiscal_graph(request(payload), STORE)
    assert validate_fiscal_graph(request(payload), STORE, allow_fixture=True)["artifact_class"] == "fixture_only"


def test_search_run_must_be_explicit_canonical_and_current():
    run = str(uuid4())
    assert fiscal_search_run_id({"derivation_run_id": run}, {"fiscal_graph_derivation_run_id": run}) == run
    with pytest.raises(ValueError, match="currently served"):
        fiscal_search_run_id({"derivation_run_id": str(uuid4())}, {"fiscal_graph_derivation_run_id": run})
    with pytest.raises(ValueError, match="UUID"):
        fiscal_search_run_id({}, {"fiscal_graph_derivation_run_id": run})
    with pytest.raises(ValueError, match="objects"):
        fiscal_search_run_id([], {"fiscal_graph_derivation_run_id": run})
    with pytest.raises(ValueError, match="unsupported keys"):
        fiscal_search_run_id({"derivation_run_id": run, "extra": True}, {"fiscal_graph_derivation_run_id": run})
    with pytest.raises(ValueError, match="relationship"):
        fiscal_search_run_id({"derivation_run_id": run, "relationship": 3}, {"fiscal_graph_derivation_run_id": run})


def test_bounds_are_domain_specific_and_do_not_silently_truncate():
    payload = graph_payload(); payload["nodes"] = payload["nodes"] * 167
    with pytest.raises(ValueError, match="bounded"):
        validate_fiscal_graph(request(payload), STORE)


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class Db:
    def __init__(self, rows):
        self.rows = rows
        self.params = None

    def execute(self, statement, params):
        self.statement = str(statement)
        self.params = params
        return Rows(self.rows)


def test_one_hop_retains_seed_same_chunk_relationship_metadata():
    payload = graph_payload(); seed_node, target_node = payload["nodes"][:2]
    edge = payload["edges"][0]; seed = chunk_for_node(seed_node); target = chunk_for_node(target_node)
    row = {"edge_id": edge["id"], "edge_type": edge["type"], "source_node_id": edge["source"],
           "target_node_id": edge["target"], "edge_attributes": edge["attributes"],
           "node_attributes": target_node["attributes"], "chunk_id": target.id,
           "document_id": target.document_id, "seed_chunk_id": seed.id, "seed_rank": 1}
    principal = Principal(tenant_id="ten", business_instance_id="biz", groups=["public"], roles=["reader"])
    hydration_calls = 0
    def hydrate(db, principal, candidates, **kwargs):
        nonlocal hydration_calls
        hydration_calls += 1
        return [seed] if hydration_calls == 1 else [target]
    additions, metadata, summary = expand_fiscal_graph(
        Db([row]), principal, STORE, [seed],
        derivation_run_id=seed_node["attributes"]["fiscal_derivation_run_id"], filters={},
        relation_types=("contains_appropriation",), limit=3,
        hydrate=hydrate,
    )
    assert [chunk.id for chunk in additions] == [target.id]
    assert metadata[seed.id]["relationships"][0]["relation_type"] == "contains_appropriation"
    assert set(metadata[target.id]["source_span_ids"]) == set(edge["attributes"]["evidence_citation_ids"])
    assert summary["applied"] is True and summary["inserted_chunk_count"] == 1


def test_expansion_preserves_filters_and_caps_candidates_at_200():
    payload = graph_payload(); seed = chunk_for_node(payload["nodes"][0])
    db = Db([])
    hydration = []
    principal = Principal(tenant_id="ten", business_instance_id="biz")
    expand_fiscal_graph(db, principal, STORE, [seed],
        derivation_run_id=payload["nodes"][0]["attributes"]["fiscal_derivation_run_id"],
        filters={"classification": "public", "file_attribute_filters": {"state_code": "KS"}},
        relation_types=FISCAL_RELATIONS, limit=3,
        hydrate=lambda *args, **kwargs: hydration.append(kwargs) or ([seed] if len(hydration) == 1 else []))
    assert db.params["candidate_limit"] == 200
    assert db.params["filter_classification"] == "public"
    assert "sc.document_id=:filter_document_id" in db.statement
    assert "sd.security_level=0" in db.statement and "d.security_level=0" in db.statement
    assert hydration[0]["filters"] == {"classification": "public", "file_attribute_filters": {"state_code": "KS"}, "vector_store_id": STORE}


def test_binding_validation_tracks_each_node_not_only_shared_chunk():
    payload = graph_payload(); payload["nodes"][1]["attributes"]["fiscal_chunk_id"] = payload["nodes"][0]["attributes"]["fiscal_chunk_id"]
    reidentify_node(payload, 1); reidentify_edges(payload)
    req = request(payload)
    # Simulate SQL matching only the first of two distinct bindings sharing a chunk.
    db = Db([{"binding_key": f"0:{req.nodes[0].id}", "chunk_id": req.nodes[0].attributes["fiscal_chunk_id"]}])
    with pytest.raises(ValueError, match="exact current"):
        validate_fiscal_graph_bindings(db, Principal(tenant_id="ten", business_instance_id="biz"), STORE, req,
            hydrate=lambda *args, **kwargs: [chunk_for_node(payload["nodes"][0])])


def test_denied_target_does_not_leak_relationship_metadata_to_seed():
    payload = graph_payload(); seed_node, target_node = payload["nodes"][:2]
    edge = payload["edges"][0]; seed = chunk_for_node(seed_node); target = chunk_for_node(target_node)
    row = {"edge_id": edge["id"], "edge_type": edge["type"], "source_node_id": edge["source"],
           "target_node_id": edge["target"], "edge_attributes": edge["attributes"],
           "node_attributes": target_node["attributes"], "chunk_id": target.id,
           "document_id": target.document_id, "seed_chunk_id": seed.id, "seed_rank": 1}
    calls = 0
    def hydrate(*args, **kwargs):
        nonlocal calls
        calls += 1
        return [seed] if calls == 1 else []
    additions, metadata, summary = expand_fiscal_graph(Db([row]), Principal(tenant_id="ten", business_instance_id="biz"),
        STORE, [seed], derivation_run_id=seed_node["attributes"]["fiscal_derivation_run_id"], filters={},
        relation_types=("contains_appropriation",), limit=3, hydrate=hydrate)
    assert additions == [] and metadata == {} and summary["applied"] is False
    assert summary['candidate_count'] == 0


def test_same_chunk_relation_is_retained_on_authorized_seed_without_addition():
    payload = graph_payload(); seed_node, target_node = payload["nodes"][:2]
    edge = payload["edges"][0]; seed = chunk_for_node(seed_node)
    row = {"edge_id": edge["id"], "edge_type": edge["type"], "source_node_id": edge["source"],
           "target_node_id": edge["target"], "edge_attributes": edge["attributes"],
           "node_attributes": target_node["attributes"], "chunk_id": seed.id,
           "document_id": seed.document_id, "seed_chunk_id": seed.id, "seed_rank": 1}
    additions, metadata, summary = expand_fiscal_graph(
        Db([row]), Principal(tenant_id="ten", business_instance_id="biz"), STORE, [seed],
        derivation_run_id=seed_node["attributes"]["fiscal_derivation_run_id"], filters={},
        relation_types=("contains_appropriation",), limit=3,
        hydrate=lambda *args, **kwargs: [seed],
    )
    assert additions == []
    assert metadata[seed.id]["relationships"][0]["relationship_id"] == edge["attributes"]["fiscal_relationship_id"]
    assert summary["applied"] is True


def test_distinct_target_chunk_in_same_document_is_not_deduplicated():
    payload = graph_payload(); seed_node, target_node = payload["nodes"][:2]
    edge = payload["edges"][0]; seed = chunk_for_node(seed_node); target = chunk_for_node(target_node)
    target.document_id = seed.document_id
    row = {"edge_id": edge["id"], "edge_type": edge["type"], "source_node_id": edge["source"],
           "target_node_id": edge["target"], "edge_attributes": edge["attributes"],
           "node_attributes": target_node["attributes"], "chunk_id": target.id,
           "document_id": target.document_id, "seed_chunk_id": seed.id, "seed_rank": 1}
    calls = 0
    def hydrate(*args, **kwargs):
        nonlocal calls
        calls += 1
        return [seed] if calls == 1 else [target]
    additions, _, _ = expand_fiscal_graph(
        Db([row]), Principal(tenant_id="ten", business_instance_id="biz"), STORE, [seed],
        derivation_run_id=seed_node["attributes"]["fiscal_derivation_run_id"], filters={},
        relation_types=("contains_appropriation",), limit=3, hydrate=hydrate,
    )
    assert [chunk.id for chunk in additions] == [target.id]
