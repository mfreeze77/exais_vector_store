"""Build a bounded fiscal graph request from a reviewed publisher envelope.

The publisher owns canonical identities and review decisions.  This adapter
checks the declared record hashes, eligibility fields, and exact unique
quote-to-current-chunk bindings.  It never infers relationships from text.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from uuid import UUID

from .fiscal_graph import (
    FISCAL_RELATIONS,
    FISCAL_SCHEMA_VERSION,
    fiscal_edge_id,
    fiscal_node_id,
    validate_fiscal_graph,
)
from .schemas import VectorStoreGraphLoadRequest

PUBLISHER_SCHEMA_VERSION = "statecivics.fiscal-graph-publisher.v1"
ARTIFACT_MANIFEST_VERSION = "exais.fiscal-graph-artifact.v1"
MAX_PUBLISHER_NODES = 1000
MAX_PUBLISHER_EDGES = 2000
MAX_CHUNK_INVENTORY = 5000
MAX_INPUT_FILE_BYTES = 16 * 1024 * 1024
_HEX = re.compile(r"^[0-9a-f]{64}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_STORE = re.compile(r"^vs_[A-Za-z0-9_-]{1,124}$")
_LEGAL_TYPES = {"enacted_provision", "appropriation_action"}
_ONTOLOGY_TYPES = {"budget_account", "agency", "fund"}
_DOCUMENT_TYPE = "fiscal_document"


class FiscalGraphArtifactError(ValueError):
    """Publisher input cannot safely become an ExAIS graph artifact."""


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _sha(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        raise FiscalGraphArtifactError(f"{field} must be a lowercase SHA-256")
    return value


def _uuid(value: Any, field: str) -> str:
    try:
        normalized = str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise FiscalGraphArtifactError(f"{field} must be a canonical UUID") from exc
    if value != normalized:
        raise FiscalGraphArtifactError(f"{field} must be a canonical UUID")
    return normalized


def _completed_review(value: Any, field: str) -> None:
    if not isinstance(value, dict) or value.get("status") != "completed":
        raise FiscalGraphArtifactError(f"{field} requires completed review evidence")
    if not value.get("reviewed_by") or not value.get("reviewed_at"):
        raise FiscalGraphArtifactError(f"{field} requires reviewer identity and time")


def validate_vector_store_id(value: Any) -> str:
    if not isinstance(value, str) or not _STORE.fullmatch(value):
        raise FiscalGraphArtifactError("vector_store_id must be a bounded vs_ identity")
    return value


def _eligible(node_type: str, eligibility: Any) -> None:
    if not isinstance(eligibility, dict):
        raise FiscalGraphArtifactError(f"{node_type} requires publisher eligibility assertions")
    if node_type in _ONTOLOGY_TYPES:
        expected = ("published", "resolved", "active")
        actual = tuple(eligibility.get(k) for k in ("publication_status", "resolution_status", "lifecycle_status"))
        if actual != expected:
            raise FiscalGraphArtifactError(f"{node_type} is not published, resolved, and active")
    elif node_type == "appropriation_action":
        if eligibility.get("status") != "published" or eligibility.get("target_account_resolved") is not True:
            raise FiscalGraphArtifactError("appropriation_action is not published with a resolved target account")
        _completed_review(eligibility.get("review"), "appropriation_action")
    elif node_type == "enacted_provision":
        if (eligibility.get("status") != "published" or eligibility.get("legal_status") != "enacted"
                or eligibility.get("lifecycle_status") != "active" or not eligibility.get("effective_period")):
            raise FiscalGraphArtifactError("enacted_provision lacks published enacted current legal evidence")
        _completed_review(eligibility.get("review"), "enacted_provision")
    elif node_type == _DOCUMENT_TYPE:
        if (eligibility.get("status") != "published" or eligibility.get("custody_status") != "retained"
                or eligibility.get("lifecycle_status") != "current" or eligibility.get("redistribution") != "full"):
            raise FiscalGraphArtifactError("fiscal_document is not current, retained, and fully redistributable")
    else:
        raise FiscalGraphArtifactError(f"unsupported fiscal node type: {node_type}")


def _bind_evidence(evidence: Any, chunks: list[dict[str, Any]]) -> dict[str, Any]:
    if not isinstance(evidence, dict):
        raise FiscalGraphArtifactError("node requires evidence")
    span_id = _uuid(evidence.get("source_span_id"), "source_span_id")
    revision_id = _uuid(evidence.get("source_revision_id"), "source_revision_id")
    logical_id = _sha(evidence.get("logical_document_id"), "logical_document_id")
    source_hash = _sha(evidence.get("source_content_hash_sha256"), "source_content_hash_sha256")
    locator = evidence.get("locator")
    if not isinstance(locator, dict) or not locator:
        raise FiscalGraphArtifactError("source span requires a non-empty canonical locator")
    if _sha(evidence.get("locator_hash_sha256"), "locator_hash_sha256") != sha256_json(locator):
        raise FiscalGraphArtifactError("source span locator hash mismatch")
    quote = evidence.get("quoted_text")
    if not isinstance(quote, str) or not quote:
        raise FiscalGraphArtifactError("source span requires quoted_text")
    quote_hash = hashlib.sha256(quote.encode("utf-8")).hexdigest()
    if _sha(evidence.get("quote_sha256"), "quote_sha256") != quote_hash:
        raise FiscalGraphArtifactError("source span quote hash mismatch")
    if _sha(evidence.get("span_content_hash_sha256"), "span_content_hash_sha256") != quote_hash:
        raise FiscalGraphArtifactError("source span content hash mismatch")
    if set(locator) == {"page"} and type(locator["page"]) is int:
        span_page_start = span_page_end = locator["page"]
    elif set(locator) == {"page_start", "page_end"} and all(type(locator[k]) is int for k in locator):
        span_page_start, span_page_end = locator["page_start"], locator["page_end"]
    else:
        raise FiscalGraphArtifactError("initial PDF source locator requires page or page_start/page_end")
    if span_page_start < 1 or span_page_end < span_page_start:
        raise FiscalGraphArtifactError("source locator page bounds are invalid")
    matches = []
    for chunk in chunks:
        if (chunk.get("current") is True and chunk.get("active") is True
                and chunk.get("logical_document_id") == logical_id
                and chunk.get("source_revision_id") == revision_id
                and chunk.get("source_content_hash_sha256") == source_hash
                and type(chunk.get("page_start")) is int and type(chunk.get("page_end")) is int
                and chunk["page_start"] <= span_page_start <= span_page_end <= chunk["page_end"]
                and isinstance(chunk.get("content"), str) and chunk["content"].count(quote) == 1):
            matches.append(chunk)
    if len(matches) != 1:
        reason = "missing" if not matches else "ambiguous"
        raise FiscalGraphArtifactError(f"source span has {reason} exact current quote-to-chunk binding: {span_id}")
    chunk_id = matches[0].get("chunk_id")
    if not isinstance(chunk_id, str) or not chunk_id:
        raise FiscalGraphArtifactError("bound chunk requires chunk_id")
    return {"span_id": span_id, "revision_id": revision_id, "logical_id": logical_id,
            "source_hash": source_hash, "chunk_id": chunk_id, "quote_sha256": quote_hash,
            "locator_hash_sha256": evidence["locator_hash_sha256"]}


def build_fiscal_graph_artifact(
    publisher: dict[str, Any], chunk_inventory: list[dict[str, Any]], vector_store_id: str,
    *, allow_fixture: bool = False,
) -> dict[str, Any]:
    """Return a validated load request and audit manifest; never performs I/O."""
    validate_vector_store_id(vector_store_id)
    if publisher.get("schema_version") != PUBLISHER_SCHEMA_VERSION:
        raise FiscalGraphArtifactError("unsupported fiscal publisher envelope version")
    artifact_class = publisher.get("artifact_class")
    if artifact_class not in {"reviewed_public", "fixture_only"}:
        raise FiscalGraphArtifactError("unsupported artifact_class")
    if artifact_class == "fixture_only" and not allow_fixture:
        raise FiscalGraphArtifactError("fixture_only input requires explicit offline allowance")
    run = publisher.get("derivation_run")
    if not isinstance(run, dict) or run.get("status") != "completed":
        raise FiscalGraphArtifactError("publisher envelope requires one completed relationship-export run")
    run_id = _uuid(run.get("id"), "derivation_run.id")
    if not _COMMIT.fullmatch(str(run.get("code_commit") or "")):
        raise FiscalGraphArtifactError("completed relationship-export run requires a lowercase 40-character code_commit")
    _sha(run.get("input_set_hash_sha256"), "derivation_run.input_set_hash_sha256")
    _sha(run.get("output_set_hash_sha256"), "derivation_run.output_set_hash_sha256")
    records = publisher.get("nodes")
    relations = publisher.get("relationships")
    if not isinstance(records, list) or not records or not isinstance(relations, list):
        raise FiscalGraphArtifactError("publisher envelope requires non-empty nodes and relationship list")
    if len(records) > MAX_PUBLISHER_NODES or len(relations) > MAX_PUBLISHER_EDGES:
        raise FiscalGraphArtifactError("publisher envelope exceeds 1000 nodes or 2000 relationships")
    if not isinstance(chunk_inventory, list) or len(chunk_inventory) > MAX_CHUNK_INVENTORY:
        raise FiscalGraphArtifactError("chunk inventory exceeds 5000 records")

    graph_nodes, node_by_ref, bindings, span_bindings = [], {}, [], {}
    for record in records:
        if not isinstance(record, dict):
            raise FiscalGraphArtifactError("node record must be an object")
        reference = record.get("record_id")
        if not isinstance(reference, str) or not reference or reference in node_by_ref:
            raise FiscalGraphArtifactError("node record_id must be unique and non-empty")
        node_type = record.get("type")
        _eligible(node_type, record.get("eligibility"))
        body = record.get("canonical_record")
        if not isinstance(body, dict) or _sha(record.get("canonical_record_sha256"), "canonical_record_sha256") != sha256_json(body):
            raise FiscalGraphArtifactError(f"canonical node record hash mismatch: {reference}")
        bound = _bind_evidence(record.get("evidence"), chunk_inventory)
        span_fingerprint = tuple(bound[key] for key in (
            "revision_id", "logical_id", "source_hash", "quote_sha256", "locator_hash_sha256"
        ))
        if bound["span_id"] in span_bindings and span_bindings[bound["span_id"]] != span_fingerprint:
            raise FiscalGraphArtifactError("repeated source span has conflicting revision, locator, or quote binding")
        span_bindings[bound["span_id"]] = span_fingerprint
        year = record.get("fiscal_year")
        if type(year) is not int or not 1900 <= year <= 2200:
            raise FiscalGraphArtifactError("node fiscal_year must be 1900..2200")
        entity_id = record.get("entity_id")
        if node_type == "enacted_provision" and entity_id != bound["span_id"]:
            raise FiscalGraphArtifactError("enacted_provision entity_id must equal its SourceSpan ID")
        if node_type == _DOCUMENT_TYPE and entity_id != bound["revision_id"]:
            raise FiscalGraphArtifactError("fiscal_document entity_id must equal its source revision ID")
        attributes = {
            "fiscal_schema_version": FISCAL_SCHEMA_VERSION, "fiscal_artifact_class": artifact_class,
            "fiscal_derivation_run_id": run_id, "fiscal_entity_id": entity_id,
            "fiscal_entity_sha256": record["canonical_record_sha256"],
            "fiscal_logical_document_id": bound["logical_id"], "fiscal_source_revision_id": bound["revision_id"],
            "fiscal_source_content_hash_sha256": bound["source_hash"], "fiscal_source_span_id": bound["span_id"],
            "fiscal_chunk_id": bound["chunk_id"], "fiscal_year": year,
            "fiscal_bill_version_id": record.get("bill_version_id"),
            "fiscal_publication_status": "published", "visibility": "public",
        }
        node_id = fiscal_node_id(vector_store_id, node_type, attributes)
        graph_nodes.append({"id": node_id, "type": node_type, "label": record.get("label"), "attributes": attributes})
        node_by_ref[reference] = {"id": node_id, "type": node_type, "span_id": bound["span_id"], "year": year}
        bindings.append({"record_id": reference, **bound})

    graph_edges = []
    for relation in relations:
        if not isinstance(relation, dict) or relation.get("type") not in FISCAL_RELATIONS:
            raise FiscalGraphArtifactError("relationship type is unsupported")
        source = node_by_ref.get(relation.get("source_record_id")); target = node_by_ref.get(relation.get("target_record_id"))
        if source is None or target is None:
            raise FiscalGraphArtifactError("relationship references an unknown node record")
        eligibility = relation.get("eligibility")
        if not isinstance(eligibility, dict) or eligibility.get("status") != "published" or eligibility.get("publication_allowed") is not True:
            raise FiscalGraphArtifactError("relationship is not published and publication-allowed")
        _completed_review(eligibility.get("review"), "relationship")
        source_refs = eligibility.get("source_refs")
        if not isinstance(source_refs, list) or not source_refs or len(source_refs) != len(set(source_refs)):
            raise FiscalGraphArtifactError("relationship requires distinct source_refs")
        normalized_refs = {_uuid(value, "relationship source_ref") for value in source_refs}
        body = relation.get("canonical_record")
        if not isinstance(body, dict) or _sha(relation.get("canonical_record_sha256"), "relationship canonical_record_sha256") != sha256_json(body):
            raise FiscalGraphArtifactError("canonical relationship record hash mismatch")
        evidence_refs = relation.get("evidence_record_ids")
        if not isinstance(evidence_refs, list) or not evidence_refs:
            raise FiscalGraphArtifactError("relationship requires evidence_record_ids")
        try:
            citations = list(dict.fromkeys(node_by_ref[value]["span_id"] for value in evidence_refs))
        except (KeyError, TypeError) as exc:
            raise FiscalGraphArtifactError("relationship evidence references an unknown node") from exc
        if normalized_refs != set(citations):
            raise FiscalGraphArtifactError("relationship source_refs must exactly equal emitted evidence citations")
        year = relation.get("fiscal_year")
        attributes = {
            "fiscal_schema_version": FISCAL_SCHEMA_VERSION, "fiscal_artifact_class": artifact_class,
            "fiscal_derivation_run_id": run_id, "fiscal_relationship_id": relation.get("relationship_id"),
            "fiscal_relationship_sha256": relation["canonical_record_sha256"], "fiscal_review_status": "accepted",
            "fiscal_publication_allowed": True, "fiscal_year": year, "visibility": "public",
            "evidence_citation_ids": citations,
        }
        edge_id = fiscal_edge_id(vector_store_id, relation["type"], source["id"], target["id"], attributes)
        graph_edges.append({"id": edge_id, "type": relation["type"], "source": source["id"],
                            "target": target["id"], "attributes": attributes})

    request_data = {"nodes": graph_nodes, "edges": graph_edges, "replace": False, "dry_run": True}
    request = VectorStoreGraphLoadRequest.model_validate(request_data)
    summary = validate_fiscal_graph(request, vector_store_id, allow_fixture=allow_fixture)
    publisher_digest = sha256_json(publisher)
    request_digest = sha256_json(request.model_dump(mode="json", exclude_none=True))
    return {
        "manifest_version": ARTIFACT_MANIFEST_VERSION, "publisher_schema_version": PUBLISHER_SCHEMA_VERSION,
        "vector_store_id": vector_store_id, "artifact_class": artifact_class, "derivation_run_id": run_id,
        "publisher_envelope_sha256": publisher_digest, "load_request_sha256": request_digest,
        "load_request": request.model_dump(mode="json", exclude_none=True), "binding_report": bindings,
        "validation": summary,
    }


def validate_built_artifact(artifact: dict[str, Any], *, allow_fixture: bool = False) -> dict[str, Any]:
    if artifact.get("manifest_version") != ARTIFACT_MANIFEST_VERSION:
        raise FiscalGraphArtifactError("unsupported built artifact version")
    request = VectorStoreGraphLoadRequest.model_validate(artifact.get("load_request"))
    if request.replace is not False:
        raise FiscalGraphArtifactError("fiscal artifacts must stage with replace=false")
    if sha256_json(request.model_dump(mode="json", exclude_none=True)) != artifact.get("load_request_sha256"):
        raise FiscalGraphArtifactError("assembled load-request digest mismatch")
    summary = validate_fiscal_graph(request, artifact.get("vector_store_id"), allow_fixture=allow_fixture)
    if summary["derivation_run_id"] != artifact.get("derivation_run_id") or summary["artifact_class"] != artifact.get("artifact_class"):
        raise FiscalGraphArtifactError("artifact manifest does not match its graph request")
    return summary
