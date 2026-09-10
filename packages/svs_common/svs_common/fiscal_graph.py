"""Bounded fiscal graph validation and one-hop cited expansion.

StateCivics supplies canonical reviewed/public assertions.  This module checks
their shape and their current ExAIS document bindings; it does not infer fiscal
relationships or independently certify an upstream review decision.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import text

from .schemas import ChunkRecord, Principal, VectorStoreGraphLoadRequest

FISCAL_CORPUS_KIND = "kansas_fiscal_documents"
FISCAL_GRAPH_HANDLER_ID = "kansas_fiscal_law_money_graph_v1"
FISCAL_PROFILE_ID = "ks-state-civics.kansas-fiscal-documents.v1"
FISCAL_SCHEMA_VERSION = "svs.fiscal-law-money.v1"
FISCAL_RELATIONS = (
    "contains_appropriation",
    "targets_account",
    "account_of_agency",
    "account_in_fund",
    "documented_by",
)
FISCAL_NODE_TYPES = frozenset(
    {"enacted_provision", "appropriation_action", "budget_account", "agency", "fund", "fiscal_document"}
)
MAX_GRAPH_NODES = 1000
MAX_GRAPH_EDGES = 2000
MAX_SEEDS = 10
MAX_CANDIDATES = 200
MAX_ADDITIONS = 10

_HASH = re.compile(r"^[0-9a-f]{64}$")
_OPAQUE = re.compile(r"^[^\x00-\x1f\x7f]{1,256}$")
_ENDPOINTS = {
    "contains_appropriation": ({"enacted_provision"}, {"appropriation_action"}),
    "targets_account": ({"appropriation_action"}, {"budget_account"}),
    "account_of_agency": ({"budget_account"}, {"agency"}),
    "account_in_fund": ({"budget_account"}, {"fund"}),
    "documented_by": ({"appropriation_action", "budget_account", "agency", "fund"}, {"fiscal_document"}),
}
_NODE_FIELDS = {
    "fiscal_schema_version", "fiscal_artifact_class", "fiscal_derivation_run_id",
    "fiscal_entity_id", "fiscal_entity_sha256", "fiscal_logical_document_id",
    "fiscal_source_revision_id", "fiscal_source_content_hash_sha256",
    "fiscal_source_span_id", "fiscal_chunk_id", "fiscal_year",
    "fiscal_bill_version_id", "fiscal_publication_status", "visibility",
}
_EDGE_FIELDS = {
    "fiscal_schema_version", "fiscal_artifact_class", "fiscal_derivation_run_id",
    "fiscal_relationship_id", "fiscal_relationship_sha256", "fiscal_review_status",
    "fiscal_publication_allowed", "fiscal_year", "visibility", "evidence_citation_ids",
}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _uuid(value: Any, label: str) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError(f"Fiscal graph requires canonical UUID for {label}")
    return value


def _opaque(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _OPAQUE.fullmatch(value):
        raise ValueError(f"Fiscal graph requires bounded {label}")
    return value


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and bool(_HASH.fullmatch(value))


def fiscal_node_id(vector_store_id: str, node_type: str, attributes: dict) -> str:
    digest = hashlib.sha256(_canonical({"type": node_type, "attributes": attributes}).encode()).hexdigest()
    return f"fiscal:{vector_store_id}:{attributes.get('fiscal_derivation_run_id')}:node:{digest}"


def fiscal_edge_id(vector_store_id: str, edge_type: str, source: str, target: str, attributes: dict) -> str:
    digest = hashlib.sha256(
        _canonical({"type": edge_type, "source": source, "target": target, "attributes": attributes}).encode()
    ).hexdigest()
    return f"fiscal:{vector_store_id}:{attributes.get('fiscal_derivation_run_id')}:edge:{digest}"


def validate_fiscal_graph(
    req: VectorStoreGraphLoadRequest, vector_store_id: str, *, allow_fixture: bool = False
) -> dict[str, Any]:
    if not req.nodes or not req.edges:
        raise ValueError("Fiscal graph artifacts require nodes and edges")
    if len(req.nodes) > MAX_GRAPH_NODES or len(req.edges) > MAX_GRAPH_EDGES:
        raise ValueError("Fiscal graph exceeds the bounded load size")
    nodes: dict[str, Any] = {}
    runs, classes, citations = set(), set(), set()
    for node in req.nodes:
        attrs = node.attributes or {}
        if set(attrs) != _NODE_FIELDS or node.key is not None or node.properties or node.provenance or node.model_extra:
            raise ValueError("Fiscal graph node attributes must match the fiscal projection contract")
        if node.type not in FISCAL_NODE_TYPES or node.id in nodes:
            raise ValueError("Fiscal graph node has duplicate or unsupported identity")
        if node.label is not None and (not isinstance(node.label, str) or len(node.label) > 256):
            raise ValueError("Fiscal graph node label exceeds 256 characters")
        run = _uuid(attrs["fiscal_derivation_run_id"], "derivation run")
        artifact_class = attrs["fiscal_artifact_class"]
        if not isinstance(artifact_class, str) or artifact_class not in {"reviewed_public", "fixture_only"} or (artifact_class == "fixture_only" and not allow_fixture):
            raise ValueError("Fiscal fixture artifacts are forbidden in public runtime")
        _opaque(attrs["fiscal_entity_id"], "entity identity")
        _uuid(attrs["fiscal_source_revision_id"], "source revision")
        citation = _uuid(attrs["fiscal_source_span_id"], "source span")
        _opaque(attrs["fiscal_chunk_id"], "chunk identity")
        if any(not _is_hash(attrs[k]) for k in (
            "fiscal_entity_sha256", "fiscal_logical_document_id", "fiscal_source_content_hash_sha256"
        )):
            raise ValueError("Fiscal graph node requires exact lowercase SHA-256 identities")
        year = attrs["fiscal_year"]
        if type(year) is not int or not 1900 <= year <= 2200:
            raise ValueError("Fiscal graph fiscal_year must be an integer from 1900 through 2200")
        bill_version = attrs["fiscal_bill_version_id"]
        if node.type in {"enacted_provision", "appropriation_action"}:
            _opaque(bill_version, "bill-version identity")
        elif bill_version is not None:
            raise ValueError("Fiscal graph bill-version identity is only allowed on legal/action nodes")
        if (attrs["fiscal_schema_version"] != FISCAL_SCHEMA_VERSION or
                attrs["fiscal_publication_status"] != "published" or attrs["visibility"] != "public"):
            raise ValueError("Fiscal graph nodes require the public fiscal v1 schema")
        if node.id != fiscal_node_id(vector_store_id, node.type, attrs):
            raise ValueError("Fiscal graph node identity does not match its type and attributes")
        if node.type == "enacted_provision" and attrs["fiscal_entity_id"] != citation:
            raise ValueError("Fiscal enacted provision identity must equal its source span UUID")
        if node.type == "fiscal_document" and attrs["fiscal_entity_id"] != attrs["fiscal_source_revision_id"]:
            raise ValueError("Fiscal document identity must equal its source revision UUID")
        nodes[node.id] = node
        runs.add(run); classes.add(artifact_class); citations.add(citation)
    if len(runs) > 1 or len(classes) > 1:
        raise ValueError("Fiscal graph load cannot mix export runs or artifact classes")
    span_bindings: dict[str, tuple[Any, ...]] = {}
    for node in nodes.values():
        attrs = node.attributes
        binding = (attrs["fiscal_source_revision_id"], attrs["fiscal_logical_document_id"],
                   attrs["fiscal_source_content_hash_sha256"], attrs["fiscal_chunk_id"])
        prior = span_bindings.setdefault(attrs["fiscal_source_span_id"], binding)
        if prior != binding:
            raise ValueError("Repeated fiscal source spans require one consistent document/chunk binding")
    seen_edges = set()
    for edge in req.edges:
        attrs = edge.attributes or {}
        if set(attrs) != _EDGE_FIELDS or edge.properties or edge.provenance or edge.model_extra:
            raise ValueError("Fiscal graph edge attributes must match the reviewed relationship contract")
        if edge.type not in FISCAL_RELATIONS or edge.id in seen_edges:
            raise ValueError("Fiscal graph edge has duplicate or unsupported identity")
        if edge.source not in nodes or edge.target not in nodes:
            raise ValueError("Fiscal graph edge is dangling")
        source, target = nodes[edge.source], nodes[edge.target]
        allowed_source, allowed_target = _ENDPOINTS[edge.type]
        if source.type not in allowed_source or target.type not in allowed_target:
            raise ValueError("Fiscal graph edge has reversed or unsupported endpoint types")
        run = _uuid(attrs["fiscal_derivation_run_id"], "derivation run")
        _opaque(attrs["fiscal_relationship_id"], "relationship identity")
        evidence = attrs["evidence_citation_ids"]
        if (run not in runs or not isinstance(attrs["fiscal_artifact_class"], str) or attrs["fiscal_artifact_class"] not in classes or
                attrs["fiscal_schema_version"] != FISCAL_SCHEMA_VERSION or
                attrs["fiscal_review_status"] != "accepted" or
                attrs["fiscal_publication_allowed"] is not True or attrs["visibility"] != "public"):
            raise ValueError("Fiscal graph edge requires an accepted publication-allowed assertion")
        if type(attrs["fiscal_year"]) is not int or not 1900 <= attrs["fiscal_year"] <= 2200:
            raise ValueError("Fiscal graph edge fiscal_year must be an integer from 1900 through 2200")
        if attrs["fiscal_year"] != source.attributes["fiscal_year"] or attrs["fiscal_year"] != target.attributes["fiscal_year"]:
            raise ValueError("Fiscal graph edge fiscal year must match both endpoints")
        if not _is_hash(attrs["fiscal_relationship_sha256"]):
            raise ValueError("Fiscal graph edge requires an exact relationship hash")
        if (not isinstance(evidence, list) or not 1 <= len(evidence) <= 20 or
                any(not isinstance(v, str) for v in evidence) or
                len(set(evidence)) != len(evidence) or any(v not in citations for v in evidence)):
            raise ValueError("Fiscal graph edge evidence must bind distinct loaded source spans")
        if edge.id != fiscal_edge_id(vector_store_id, edge.type, edge.source, edge.target, attrs):
            raise ValueError("Fiscal graph edge identity does not match its directed assertion")
        seen_edges.add(edge.id)
    return {"derivation_run_id": next(iter(runs), None), "artifact_class": next(iter(classes), None),
            "nodes": len(nodes), "edges": len(seen_edges)}


def fiscal_search_run_id(inputs: dict | None, store_attributes: dict) -> str:
    if not isinstance(inputs, dict) or not isinstance(store_attributes, dict):
        raise ValueError("Fiscal graph inputs and store attributes must be objects")
    if set(inputs) - {"derivation_run_id", "relationship"}:
        raise ValueError("Fiscal graph inputs contain unsupported keys")
    relationship = inputs.get("relationship", "all")
    if not isinstance(relationship, str) or relationship not in {"all", *FISCAL_RELATIONS}:
        raise ValueError("Unsupported fiscal graph relationship focus")
    requested = _uuid((inputs or {}).get("derivation_run_id"), "requested derivation run")
    served = _uuid((store_attributes or {}).get("fiscal_graph_derivation_run_id"), "served derivation run")
    if requested != served:
        raise ValueError("Requested fiscal graph run is not the currently served run")
    return requested


def validate_fiscal_graph_bindings(db: Any, principal: Principal, vector_store_id: str,
                                   req: VectorStoreGraphLoadRequest, *, hydrate: Callable[..., list[ChunkRecord]]) -> None:
    """Require every evidence node to bind its exact current file and chunk."""
    if not req.nodes:
        return
    bindings = [{
        "binding_key": f"{index}:{node.id}",
        "chunk_id": node.attributes["fiscal_chunk_id"],
        "logical_id": node.attributes["fiscal_logical_document_id"],
        "revision_id": node.attributes["fiscal_source_revision_id"],
        "source_hash": node.attributes["fiscal_source_content_hash_sha256"],
    } for index, node in enumerate(req.nodes)]
    rows = db.execute(text("""
        SELECT n.binding_key, n.chunk_id
        FROM jsonb_to_recordset(CAST(:nodes AS jsonb)) AS n(
          binding_key text, chunk_id text, logical_id text, revision_id text, source_hash text)
        JOIN chunks c ON c.id=n.chunk_id AND c.tenant_id=:tenant_id
          AND c.business_instance_id=:biz_id AND c.vector_store_id=:store_id AND c.active=true
          AND c.security_level=0 AND c.classification='public'
        JOIN documents d ON d.id=c.document_id AND d.current_version_id=c.document_version_id
          AND d.tenant_id=c.tenant_id AND d.business_instance_id=c.business_instance_id AND d.status='active'
          AND d.security_level=0 AND d.classification='public'
        JOIN vector_store_files f ON f.document_id=d.id AND f.tenant_id=d.tenant_id
          AND f.business_instance_id=d.business_instance_id AND f.vector_store_id=:store_id AND f.status='completed'
          AND f.attributes->>'source_collection'='statecivics-kansas-fiscal-documents'
          AND f.attributes->>'logical_document_id'=n.logical_id
          AND f.attributes->>'source_revision_id'=n.revision_id
          AND f.attributes->>'source_content_hash_sha256'=n.source_hash
    """), {"tenant_id": principal.tenant_id, "biz_id": principal.business_instance_id,
             "store_id": vector_store_id, "nodes": json.dumps(bindings)}).mappings().all()
    matched_keys = {row["binding_key"] for row in rows}
    expected_keys = {binding["binding_key"] for binding in bindings}
    expected_chunks = {binding["chunk_id"] for binding in bindings}
    hydrated = hydrate(db, principal, [{"id": i, "payload": {"chunk_id": i}, "score": 0.5} for i in expected_chunks],
                       limit=len(expected_chunks), filters={"vector_store_id": vector_store_id})
    accessible = {chunk.id for chunk in hydrated}
    if matched_keys != expected_keys or accessible != expected_chunks:
        raise ValueError("Fiscal graph nodes require exact current accessible document/chunk bindings")


def guard_fiscal_graph_generation(db: Any, principal: Principal, vector_store_id: str,
                                  req: VectorStoreGraphLoadRequest) -> None:
    summary = validate_fiscal_graph(req, vector_store_id, allow_fixture=True)
    run = summary["derivation_run_id"]
    if run is None:
        return
    existing_nodes = db.execute(text("""SELECT id,node_type,label,attributes FROM graph_nodes
      WHERE tenant_id=:tenant AND business_instance_id=:biz AND vector_store_id=:store
        AND attributes->>'fiscal_derivation_run_id'=:run ORDER BY id"""),
        {"tenant": principal.tenant_id, "biz": principal.business_instance_id, "store": vector_store_id, "run": run}).mappings().all()
    existing_edges = db.execute(text("""SELECT id,edge_type,source_node_id,target_node_id,attributes FROM graph_edges
      WHERE tenant_id=:tenant AND business_instance_id=:biz AND vector_store_id=:store
        AND attributes->>'fiscal_derivation_run_id'=:run ORDER BY id"""),
        {"tenant": principal.tenant_id, "biz": principal.business_instance_id, "store": vector_store_id, "run": run}).mappings().all()
    if not existing_nodes and not existing_edges:
        return
    wanted_nodes = sorted((n.id, n.type, n.label, n.attributes) for n in req.nodes)
    found_nodes = sorted((r["id"], r["node_type"], r["label"], r["attributes"]) for r in existing_nodes)
    wanted_edges = sorted((e.id, e.type, e.source, e.target, e.attributes) for e in req.edges)
    found_edges = sorted((r["id"], r["edge_type"], r["source_node_id"], r["target_node_id"], r["attributes"]) for r in existing_edges)
    if wanted_nodes != found_nodes or wanted_edges != found_edges:
        raise ValueError("Fiscal graph export run already exists with different content")


def expand_fiscal_graph(db: Any, principal: Principal, vector_store_id: str, chunks: list[ChunkRecord], *,
                        derivation_run_id: str, filters: dict, relation_types: tuple[str, ...], limit: int,
                        hydrate: Callable[..., list[ChunkRecord]]) -> tuple[list[ChunkRecord], dict[str, dict], dict]:
    run = _uuid(derivation_run_id, "derivation run")
    if not relation_types or not set(relation_types).issubset(FISCAL_RELATIONS):
        raise ValueError("Unsupported fiscal graph relationship focus")
    if type(limit) is not int or not 0 <= limit <= MAX_ADDITIONS:
        raise ValueError("Fiscal graph expansion limit must be 0..10")
    summary = {"enabled": True, "profile": FISCAL_GRAPH_HANDLER_ID, "derivation_run_id": run,
               "applied": False, "inserted_chunk_count": 0}
    if not chunks or limit == 0:
        return [], {}, {**summary, "reason": "no_seed_or_zero_limit"}
    column_filters = {}
    for key in ("document_id", "knowledge_base_id", "classification", "acl_bucket"):
        value = filters.get(key)
        if value is not None and not isinstance(value, str):
            raise ValueError("Fiscal graph chunk filters require string identities")
        column_filters[f"filter_{key}"] = value
    supplied_by_id = {chunk.id: chunk for chunk in chunks}
    requested_seed_ids = list(dict.fromkeys(supplied_by_id))[:MAX_SEEDS]
    authorized_seeds = hydrate(
        db, principal,
        [{"id": cid, "payload": {"chunk_id": cid}, "score": 0.5} for cid in requested_seed_ids],
        limit=MAX_SEEDS, filters={**filters, "vector_store_id": vector_store_id},
    )
    seed_chunks = [chunk.id for chunk in authorized_seeds if chunk.id in supplied_by_id]
    if not seed_chunks:
        return [], {}, {**summary, "reason": "no_authorized_seed"}
    rows = db.execute(text("""
      WITH seeds AS (
        SELECT n.id, n.attributes->>'fiscal_chunk_id' AS seed_chunk_id,
          array_position(CAST(:seed_ids AS text[]), n.attributes->>'fiscal_chunk_id') AS seed_rank
        FROM graph_nodes n JOIN chunks sc ON sc.id=n.attributes->>'fiscal_chunk_id'
          AND sc.tenant_id=n.tenant_id AND sc.business_instance_id=n.business_instance_id
          AND sc.vector_store_id=n.vector_store_id AND sc.active=true
          AND sc.security_level=0 AND sc.classification='public'
        JOIN documents sd ON sd.id=sc.document_id AND sd.current_version_id=sc.document_version_id AND sd.status='active'
          AND sd.security_level=0 AND sd.classification='public'
        JOIN vector_store_files sf ON sf.document_id=sd.id AND sf.vector_store_id=n.vector_store_id
          AND sf.tenant_id=n.tenant_id AND sf.business_instance_id=n.business_instance_id AND sf.status='completed'
          AND sf.attributes->>'source_collection'='statecivics-kansas-fiscal-documents'
          AND sf.attributes->>'logical_document_id'=n.attributes->>'fiscal_logical_document_id'
          AND sf.attributes->>'source_revision_id'=n.attributes->>'fiscal_source_revision_id'
          AND sf.attributes->>'source_content_hash_sha256'=n.attributes->>'fiscal_source_content_hash_sha256'
        WHERE n.tenant_id=:tenant AND n.business_instance_id=:biz AND n.vector_store_id=:store
          AND n.attributes->>'fiscal_derivation_run_id'=:run AND n.attributes->>'visibility'='public'
          AND n.attributes->>'fiscal_artifact_class'='reviewed_public'
          AND n.attributes->>'fiscal_chunk_id'=ANY(CAST(:seed_ids AS text[]))
          AND (CAST(:filter_document_id AS text) IS NULL OR sc.document_id=:filter_document_id)
          AND (CAST(:filter_knowledge_base_id AS text) IS NULL OR sc.knowledge_base_id=:filter_knowledge_base_id)
          AND (CAST(:filter_classification AS text) IS NULL OR sc.classification=:filter_classification)
          AND (CAST(:filter_acl_bucket AS text) IS NULL OR sc.acl_bucket=:filter_acl_bucket)
      )
      SELECT e.id edge_id,e.edge_type,e.source_node_id,e.target_node_id,e.attributes edge_attributes,
        n.attributes node_attributes,c.id chunk_id,c.document_id,s.seed_chunk_id,s.seed_rank
      FROM seeds s JOIN graph_edges e ON (e.source_node_id=s.id OR e.target_node_id=s.id)
        AND e.tenant_id=:tenant AND e.business_instance_id=:biz AND e.vector_store_id=:store
      JOIN graph_nodes n ON n.id=CASE WHEN e.source_node_id=s.id THEN e.target_node_id ELSE e.source_node_id END
        AND n.tenant_id=e.tenant_id AND n.business_instance_id=e.business_instance_id AND n.vector_store_id=e.vector_store_id
      JOIN chunks c ON c.id=n.attributes->>'fiscal_chunk_id' AND c.tenant_id=n.tenant_id
        AND c.business_instance_id=n.business_instance_id AND c.vector_store_id=n.vector_store_id AND c.active=true
        AND c.security_level=0 AND c.classification='public'
      JOIN documents d ON d.id=c.document_id AND d.current_version_id=c.document_version_id AND d.status='active'
        AND d.security_level=0 AND d.classification='public'
      JOIN vector_store_files f ON f.document_id=d.id AND f.vector_store_id=n.vector_store_id
        AND f.tenant_id=n.tenant_id AND f.business_instance_id=n.business_instance_id AND f.status='completed'
        AND f.attributes->>'source_collection'='statecivics-kansas-fiscal-documents'
        AND f.attributes->>'logical_document_id'=n.attributes->>'fiscal_logical_document_id'
        AND f.attributes->>'source_revision_id'=n.attributes->>'fiscal_source_revision_id'
        AND f.attributes->>'source_content_hash_sha256'=n.attributes->>'fiscal_source_content_hash_sha256'
      WHERE n.attributes->>'fiscal_derivation_run_id'=:run AND n.attributes->>'visibility'='public'
        AND n.attributes->>'fiscal_artifact_class'='reviewed_public'
        AND e.attributes->>'fiscal_derivation_run_id'=:run
        AND e.attributes->>'fiscal_artifact_class'='reviewed_public'
        AND e.attributes->>'fiscal_review_status'='accepted'
        AND e.attributes->>'fiscal_publication_allowed'='true' AND e.attributes->>'visibility'='public'
        AND e.edge_type=ANY(CAST(:relations AS text[]))
        AND (CAST(:filter_document_id AS text) IS NULL OR c.document_id=:filter_document_id)
        AND (CAST(:filter_knowledge_base_id AS text) IS NULL OR c.knowledge_base_id=:filter_knowledge_base_id)
        AND (CAST(:filter_classification AS text) IS NULL OR c.classification=:filter_classification)
        AND (CAST(:filter_acl_bucket AS text) IS NULL OR c.acl_bucket=:filter_acl_bucket)
        AND NOT EXISTS (SELECT 1 FROM jsonb_array_elements_text(e.attributes->'evidence_citation_ids') ev(span_id)
          WHERE NOT EXISTS (SELECT 1 FROM graph_nodes en JOIN chunks ec ON ec.id=en.attributes->>'fiscal_chunk_id'
            AND ec.tenant_id=en.tenant_id AND ec.business_instance_id=en.business_instance_id
            AND ec.vector_store_id=en.vector_store_id AND ec.active=true AND ec.security_level=0
            AND ec.classification='public' AND (cardinality(ec.allowed_groups)=0 OR ec.allowed_groups && CAST(:groups AS text[]))
            AND (cardinality(ec.allowed_roles)=0 OR ec.allowed_roles && CAST(:roles AS text[]))
            JOIN documents ed ON ed.id=ec.document_id AND ed.current_version_id=ec.document_version_id AND ed.status='active'
              AND ed.security_level=0 AND ed.classification='public'
            JOIN vector_store_files ef ON ef.document_id=ed.id AND ef.vector_store_id=en.vector_store_id
              AND ef.tenant_id=en.tenant_id AND ef.business_instance_id=en.business_instance_id AND ef.status='completed'
              AND ef.attributes->>'source_collection'='statecivics-kansas-fiscal-documents'
              AND ef.attributes->>'logical_document_id'=en.attributes->>'fiscal_logical_document_id'
              AND ef.attributes->>'source_revision_id'=en.attributes->>'fiscal_source_revision_id'
              AND ef.attributes->>'source_content_hash_sha256'=en.attributes->>'fiscal_source_content_hash_sha256'
            WHERE en.tenant_id=:tenant AND en.business_instance_id=:biz AND en.vector_store_id=:store
              AND en.attributes->>'fiscal_derivation_run_id'=:run
              AND en.attributes->>'fiscal_artifact_class'='reviewed_public'
              AND en.attributes->>'fiscal_publication_status'='published'
              AND en.attributes->>'visibility'='public'
              AND en.attributes->>'fiscal_source_span_id'=ev.span_id))
      ORDER BY s.seed_rank,e.id,c.ordinal,c.id LIMIT :candidate_limit
    """), {"tenant": principal.tenant_id, "biz": principal.business_instance_id, "store": vector_store_id,
             "run": run, "seed_ids": seed_chunks, "relations": list(relation_types),
             "candidate_limit": MAX_CANDIDATES, "groups": principal.groups, "roles": principal.roles,
             **column_filters}).mappings().all()
    by_chunk: dict[str, Any] = {}
    for row in rows:
        attrs = row["edge_attributes"]
        if not isinstance(attrs, dict) or not _is_hash(attrs.get("fiscal_relationship_sha256")):
            continue
        by_chunk.setdefault(row["chunk_id"], row)
    candidates = [{"id": cid, "payload": {"chunk_id": cid}, "score": 0.5} for cid in by_chunk]
    hydrated = hydrate(db, principal, candidates, limit=MAX_CANDIDATES,
                       filters={**filters, "vector_store_id": vector_store_id})
    hydrated_by_id = {chunk.id: chunk for chunk in hydrated if chunk.id in by_chunk}
    authorized_seed_ids = {chunk.id for chunk in authorized_seeds}
    relationships: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row["seed_chunk_id"] not in authorized_seed_ids or row["chunk_id"] not in hydrated_by_id:
            continue
        attrs = row["edge_attributes"]
        if not isinstance(attrs, dict) or not _is_hash(attrs.get("fiscal_relationship_sha256")):
            continue
        relation = {"relationship_id": attrs.get("fiscal_relationship_id"),
                    "relationship_sha256": attrs.get("fiscal_relationship_sha256"),
                    "relation_type": row["edge_type"], "source_node_id": row["source_node_id"],
                    "target_node_id": row["target_node_id"],
                    "evidence_citation_ids": attrs.get("evidence_citation_ids", []),
                    "fiscal_year": attrs.get("fiscal_year")}
        for cid in {row["seed_chunk_id"], row["chunk_id"]}:
            relationships.setdefault(cid, [])
            if relation not in relationships[cid] and len(relationships[cid]) < MAX_CANDIDATES:
                relationships[cid].append(relation)
    existing_chunks = {c.id for c in chunks}
    additions, metadata = [], {}
    for seed in authorized_seeds:
        if seed.id in relationships:
            metadata[seed.id] = {"profile": FISCAL_GRAPH_HANDLER_ID, "derivation_run_id": run,
                                 "source_span_ids": sorted({s for r in relationships[seed.id] for s in r["evidence_citation_ids"]}),
                                 "relationships": relationships[seed.id]}
    for chunk in hydrated_by_id.values():
        if chunk.id not in relationships or chunk.id in existing_chunks or chunk.security_level != 0 or chunk.classification != "public":
            continue
        chunk.source = "fiscal_canonical_graph_expansion"
        metadata[chunk.id] = {"profile": FISCAL_GRAPH_HANDLER_ID, "derivation_run_id": run,
                              "source_span_ids": sorted({s for r in relationships.get(chunk.id, []) for s in r["evidence_citation_ids"]}),
                              "relationships": relationships.get(chunk.id, [])}
        additions.append(chunk); existing_chunks.add(chunk.id)
        if len(additions) >= limit:
            break
    return additions, metadata, {**summary, "applied": bool(additions or metadata),
                                  "candidate_count": len(hydrated_by_id), "inserted_chunk_count": len(additions)}
