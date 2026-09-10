from __future__ import annotations

import copy
import hashlib
import importlib.util
from uuid import UUID

import pytest

from svs_common.fiscal_graph import FISCAL_RELATIONS
from svs_common.fiscal_graph_artifact import (
    MAX_INPUT_FILE_BYTES,
    FiscalGraphArtifactError,
    build_fiscal_graph_artifact,
    canonical_json,
    sha256_json,
    validate_built_artifact,
)


RUN = "018f1d85-7b2e-7f80-8000-000000000001"


def _uuid(index: int) -> str:
    return str(UUID(int=index + 100))


def _review() -> dict:
    return {"status": "completed", "reviewed_by": "fixture-reviewer", "reviewed_at": "2026-09-10T12:00:00Z"}


def _eligibility(node_type: str) -> dict:
    if node_type in {"budget_account", "agency", "fund"}:
        return {"publication_status": "published", "resolution_status": "resolved", "lifecycle_status": "active"}
    if node_type == "appropriation_action":
        return {"status": "published", "target_account_resolved": True, "review": _review()}
    if node_type == "enacted_provision":
        return {"status": "published", "legal_status": "enacted", "lifecycle_status": "active",
                "effective_period": {"from": "2025-07-01"}, "review": _review()}
    return {"status": "published", "custody_status": "retained", "lifecycle_status": "current", "redistribution": "full"}


def inputs(artifact_class: str = "reviewed_public") -> tuple[dict, list[dict]]:
    node_types = ["enacted_provision", "appropriation_action", "budget_account", "agency", "fund", "fiscal_document"]
    records, chunks = [], []
    for index, node_type in enumerate(node_types):
        span = _uuid(index); revision = _uuid(index + 20); logical = hashlib.sha256(f"doc-{index}".encode()).hexdigest()
        source_hash = hashlib.sha256(f"source-{index}".encode()).hexdigest(); quote = f"Exact cited fiscal statement {index}."
        locator = {"page": index + 1}
        body = {"kind": node_type, "canonical_id": f"canonical-{index}", "revision": 1}
        entity_id = span if node_type == "enacted_provision" else revision if node_type == "fiscal_document" else f"entity-{index}"
        records.append({
            "record_id": f"n{index}", "type": node_type, "entity_id": entity_id, "label": f"Node {index}",
            "canonical_record": body, "canonical_record_sha256": sha256_json(body), "eligibility": _eligibility(node_type),
            "fiscal_year": 2025, "bill_version_id": "ks-sb125-enrolled" if node_type in {"enacted_provision", "appropriation_action"} else None,
            "evidence": {"source_span_id": span, "source_revision_id": revision, "logical_document_id": logical,
                         "source_content_hash_sha256": source_hash, "locator": locator,
                         "locator_hash_sha256": sha256_json(locator), "quoted_text": quote,
                         "quote_sha256": hashlib.sha256(quote.encode()).hexdigest(),
                         "span_content_hash_sha256": hashlib.sha256(quote.encode()).hexdigest()},
        })
        chunks.append({"chunk_id": f"chunk-{index}", "content": f"Context. {quote} More context.", "current": True, "active": True,
                       "page_start": index + 1, "page_end": index + 1,
                       "logical_document_id": logical, "source_revision_id": revision,
                       "source_content_hash_sha256": source_hash})
    specs = [
        ("contains_appropriation", "n0", "n1"), ("targets_account", "n1", "n2"),
        ("account_of_agency", "n2", "n3"), ("account_in_fund", "n2", "n4"),
        ("documented_by", "n1", "n5"),
    ]
    relationships = []
    for index, (kind, source, target) in enumerate(specs):
        body = {"kind": kind, "source": source, "target": target, "assertion_revision": 1}
        relationships.append({"relationship_id": f"relationship-{index}", "type": kind,
                              "source_record_id": source, "target_record_id": target,
                              "fiscal_year": 2025, "canonical_record": body,
                              "canonical_record_sha256": sha256_json(body),
                              "eligibility": {"status": "published", "publication_allowed": True,
                                              "review": _review(), "source_refs": [records[int(source[1:])]["evidence"]["source_span_id"],
                                                                                   records[int(target[1:])]["evidence"]["source_span_id"]]},
                              "evidence_record_ids": [source, target]})
    return ({"schema_version": "statecivics.fiscal-graph-publisher.v1", "artifact_class": artifact_class,
             "derivation_run": {"id": RUN, "status": "completed", "code_commit": "a" * 40,
                                "input_set_hash_sha256": "b" * 64, "output_set_hash_sha256": "c" * 64}, "nodes": records,
             "relationships": relationships}, chunks)


def test_builds_complete_bounded_chain_with_exact_bindings() -> None:
    publisher, chunks = inputs()
    artifact = build_fiscal_graph_artifact(publisher, chunks, "vs_fiscal_test")
    assert artifact["validation"] == {"derivation_run_id": RUN, "artifact_class": "reviewed_public", "nodes": 6, "edges": 5}
    assert {edge["type"] for edge in artifact["load_request"]["edges"]} == set(FISCAL_RELATIONS)
    assert artifact["load_request"]["replace"] is False and artifact["load_request"]["dry_run"] is True
    assert len(artifact["binding_report"]) == 6
    assert validate_built_artifact(artifact) == artifact["validation"]


@pytest.mark.parametrize("mutation,match", [
    (lambda p, c: c[0].update(current=False), "missing exact current"),
    (lambda p, c: c[0].update(source_content_hash_sha256="0" * 64), "missing exact current"),
    (lambda p, c: c[0].update(content="quote absent"), "missing exact current"),
    (lambda p, c: c.append(copy.deepcopy(c[0])), "ambiguous exact current"),
    (lambda p, c: c[0].update(content=c[0]["content"] + " " + p["nodes"][0]["evidence"]["quoted_text"]), "missing exact current"),
])
def test_rejects_missing_stale_wrong_source_and_ambiguous_bindings(mutation, match: str) -> None:
    publisher, chunks = inputs(); mutation(publisher, chunks)
    with pytest.raises(FiscalGraphArtifactError, match=match):
        build_fiscal_graph_artifact(publisher, chunks, "vs_fiscal_test")


def test_rejects_quote_locator_and_canonical_hash_mismatches() -> None:
    for field in ("quote_sha256", "span_content_hash_sha256", "locator_hash_sha256"):
        publisher, chunks = inputs(); publisher["nodes"][0]["evidence"][field] = "0" * 64
        with pytest.raises(FiscalGraphArtifactError, match="hash mismatch"):
            build_fiscal_graph_artifact(publisher, chunks, "vs_fiscal_test")
    publisher, chunks = inputs(); publisher["nodes"][0]["canonical_record"]["revision"] = 2
    with pytest.raises(FiscalGraphArtifactError, match="canonical node record hash mismatch"):
        build_fiscal_graph_artifact(publisher, chunks, "vs_fiscal_test")


@pytest.mark.parametrize("node_index,field,value", [
    (2, "publication_status", "candidate"), (2, "resolution_status", "ambiguous"),
    (1, "target_account_resolved", False), (0, "legal_status", "introduced"),
    (5, "custody_status", "withdrawn"),
])
def test_rejects_type_specific_ineligible_nodes(node_index: int, field: str, value: object) -> None:
    publisher, chunks = inputs(); publisher["nodes"][node_index]["eligibility"][field] = value
    with pytest.raises(FiscalGraphArtifactError):
        build_fiscal_graph_artifact(publisher, chunks, "vs_fiscal_test")


def test_rejects_unreviewed_or_unpublishable_relationship_without_manufacturing_review() -> None:
    publisher, chunks = inputs(); publisher["relationships"][0]["eligibility"]["review"]["status"] = "pending"
    with pytest.raises(FiscalGraphArtifactError, match="completed review"):
        build_fiscal_graph_artifact(publisher, chunks, "vs_fiscal_test")
    publisher, chunks = inputs(); publisher["relationships"][0]["eligibility"]["publication_allowed"] = False
    with pytest.raises(FiscalGraphArtifactError, match="publication-allowed"):
        build_fiscal_graph_artifact(publisher, chunks, "vs_fiscal_test")


def test_relationship_source_refs_must_exactly_match_emitted_citations() -> None:
    publisher, chunks = inputs()
    publisher["relationships"][0]["eligibility"]["source_refs"] = [publisher["nodes"][0]["evidence"]["source_span_id"]]
    with pytest.raises(FiscalGraphArtifactError, match="exactly equal"):
        build_fiscal_graph_artifact(publisher, chunks, "vs_fiscal_test")


def test_rejects_missing_or_out_of_chunk_pdf_page_locator() -> None:
    publisher, chunks = inputs(); publisher["nodes"][0]["evidence"]["locator"] = {"section": "1"}
    publisher["nodes"][0]["evidence"]["locator_hash_sha256"] = sha256_json({"section": "1"})
    with pytest.raises(FiscalGraphArtifactError, match="requires page"):
        build_fiscal_graph_artifact(publisher, chunks, "vs_fiscal_test")
    publisher, chunks = inputs(); chunks[0]["page_start"] = 2; chunks[0]["page_end"] = 2
    with pytest.raises(FiscalGraphArtifactError, match="missing exact current"):
        build_fiscal_graph_artifact(publisher, chunks, "vs_fiscal_test")


@pytest.mark.parametrize("field,value", [
    ("code_commit", "short"), ("input_set_hash_sha256", "0" * 63), ("output_set_hash_sha256", "A" * 64),
])
def test_completed_run_requires_replayable_provenance(field: str, value: str) -> None:
    publisher, chunks = inputs(); publisher["derivation_run"][field] = value
    with pytest.raises(FiscalGraphArtifactError, match="run requires|derivation_run"):
        build_fiscal_graph_artifact(publisher, chunks, "vs_fiscal_test")


def test_pre_scan_bounds_reject_oversized_collections() -> None:
    publisher, chunks = inputs(); publisher["nodes"] = publisher["nodes"] * 167
    with pytest.raises(FiscalGraphArtifactError, match="exceeds 1000"):
        build_fiscal_graph_artifact(publisher, chunks, "vs_fiscal_test")
    publisher, chunks = inputs(); publisher["relationships"] = publisher["relationships"] * 401
    with pytest.raises(FiscalGraphArtifactError, match="2000 relationships"):
        build_fiscal_graph_artifact(publisher, chunks, "vs_fiscal_test")
    publisher, chunks = inputs(); chunks = chunks * 834
    with pytest.raises(FiscalGraphArtifactError, match="exceeds 5000"):
        build_fiscal_graph_artifact(publisher, chunks, "vs_fiscal_test")


def test_fixture_requires_explicit_offline_allowance_and_remains_identified() -> None:
    publisher, chunks = inputs("fixture_only")
    with pytest.raises(FiscalGraphArtifactError, match="offline allowance"):
        build_fiscal_graph_artifact(publisher, chunks, "vs_fiscal_test")
    artifact = build_fiscal_graph_artifact(publisher, chunks, "vs_fiscal_test", allow_fixture=True)
    assert validate_built_artifact(artifact, allow_fixture=True)["artifact_class"] == "fixture_only"
    with pytest.raises(ValueError, match="forbidden in public runtime"):
        validate_built_artifact(artifact)


def test_digest_and_ids_are_deterministic_and_tampering_fails() -> None:
    publisher, chunks = inputs()
    first = build_fiscal_graph_artifact(publisher, chunks, "vs_fiscal_test")
    second = build_fiscal_graph_artifact(publisher, chunks, "vs_fiscal_test")
    assert canonical_json(first) == canonical_json(second)
    tampered = copy.deepcopy(first); tampered["load_request"]["nodes"][0]["label"] = "changed"
    with pytest.raises(FiscalGraphArtifactError, match="digest mismatch"):
        validate_built_artifact(tampered)


def test_operator_cli_restricts_urls_and_finds_explicit_relationship_ids() -> None:
    spec = importlib.util.spec_from_file_location(
        "kansas_fiscal_graphrag_cli", "scripts/release/kansas-fiscal-graphrag.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    assert module._safe_api("http://localhost:8000/") == "http://localhost:8000"
    assert module._safe_api("https://fiscal.example/") == "https://fiscal.example"
    with pytest.raises(ValueError, match="HTTPS"):
        module._safe_api("http://fiscal.example")
    for unsafe in ("https://user:pass@fiscal.example", "https://fiscal.example/path", "https://fiscal.example?q=token", "https://fiscal.example/#secret"):
        with pytest.raises(ValueError):
            module._safe_api(unsafe)
    assert module._relationship_ids({"data": [{"metadata": {"relationships": [
        {"relationship_id": "rel-1"}, {"relationship_id": "rel-2"}
    ]}}]}) == {"rel-1", "rel-2"}


def test_operator_cli_rejects_oversized_input_before_json_decode(tmp_path) -> None:
    spec = importlib.util.spec_from_file_location(
        "kansas_fiscal_graphrag_cli_size", "scripts/release/kansas-fiscal-graphrag.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    oversized = tmp_path / "oversized.json"
    with oversized.open("wb") as stream:
        stream.seek(MAX_INPUT_FILE_BYTES)
        stream.write(b"x")
    with pytest.raises(ValueError, match="exceeds"):
        module._read(oversized)
