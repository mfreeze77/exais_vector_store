"""Grant-only, generation-bound graph expansion over canonical caller evidence.

Reuse the cell graph tables and retrieval hydrator. This does not extract or
approve relationships, and it must not alter court/municipal graph behavior.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy import text

from .schemas import ChunkRecord, Principal, VectorStoreGraphLoadRequest

GRANT_CORPUS_KIND = "reviewed_public_grant_evidence"
GRANT_GRAPH_HANDLER_ID = "grant_canonical_evidence_graph_v1"
GRANT_RELATIONS = (
    "awarded_to",
    "funds",
    "authorizes",
    "uses_procurement",
    "has_contract",
    "paid_to",
    "has_winner",
)
GRANT_NODE_TYPES = frozenset(
    {
        "program",
        "opportunity",
        "award",
        "winner",
        "recipient",
        "project",
        "procurement",
        "contract",
        "vendor",
        "document",
    }
)
MAX_GRAPH_NODES = 10000
MAX_GRAPH_EDGES = 20000
_HASH = re.compile(r"^[0-9a-f]{64}$")
_CITATION = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def _uuid(value: Any) -> str:
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("Grant graph requires canonical UUID identities")
    return value


def validate_grant_graph(
    req: VectorStoreGraphLoadRequest, vector_store_id: str
) -> None:
    """Reject unbound, mixed-generation, private or unreviewed graph declarations.

    The caller must authenticate its real canonical approvals. These structural
    checks never turn an operator's declaration into independent human review.
    """
    if len(req.nodes) > MAX_GRAPH_NODES or len(req.edges) > MAX_GRAPH_EDGES:
        raise ValueError("Grant graph exceeds the bounded load size")
    nodes = {}
    generations = set()
    citations = set()
    node_fields = {
        "gip_generation_id",
        "gip_search_document_id",
        "gip_entity_id",
        "gip_source_version_sha256",
        "gip_citation_id",
        "visibility",
    }
    for node in req.nodes:
        attrs = node.attributes or {}
        if (
            set(attrs) != node_fields
            or node.properties
            or node.model_extra
            or node.provenance
        ):
            raise ValueError(
                "Grant graph node attributes must match the canonical projection contract"
            )
        generation = _uuid(attrs["gip_generation_id"])
        document_id = _uuid(attrs["gip_search_document_id"])
        _uuid(attrs["gip_entity_id"])
        expected_id = f"gip:{vector_store_id}:{generation}:{document_id}"
        if (
            node.id != expected_id
            or node.id in nodes
            or node.type not in GRANT_NODE_TYPES
        ):
            raise ValueError(
                "Grant graph node has duplicate, unsupported or unbound identity"
            )
        if attrs["visibility"] != "public" or not _HASH.fullmatch(
            str(attrs["gip_source_version_sha256"])
        ):
            raise ValueError(
                "Grant graph node requires public visibility and exact source hash"
            )
        if not isinstance(attrs["gip_citation_id"], str) or not _CITATION.fullmatch(
            attrs["gip_citation_id"]
        ):
            raise ValueError("Grant graph node requires a bounded citation identity")
        nodes[node.id] = node
        generations.add(generation)
        citations.add(attrs["gip_citation_id"])
    if len(generations) > 1:
        raise ValueError("Grant graph load cannot mix projection generations")
    seen_edges = set()
    edge_fields = {
        "gip_generation_id",
        "gip_relationship_id",
        "gip_relationship_sha256",
        "review_status",
        "visibility",
        "evidence_citation_ids",
    }
    for edge in req.edges:
        attrs = edge.attributes or {}
        if (
            set(attrs) != edge_fields
            or edge.properties
            or edge.model_extra
            or edge.provenance
        ):
            raise ValueError(
                "Grant graph edge attributes must match the accepted-evidence contract"
            )
        generation = _uuid(attrs["gip_generation_id"])
        relationship_id = _uuid(attrs["gip_relationship_id"])
        expected_id = f"gip:{vector_store_id}:{generation}:edge:{relationship_id}"
        if (
            edge.id != expected_id
            or edge.id in seen_edges
            or edge.type not in GRANT_RELATIONS
        ):
            raise ValueError(
                "Grant graph edge has duplicate, unsupported or unbound identity"
            )
        if (
            edge.source not in nodes
            or edge.target not in nodes
            or generation not in generations
        ):
            raise ValueError(
                "Grant graph edge is dangling or belongs to another generation"
            )
        if attrs["review_status"] != "accepted" or attrs["visibility"] != "public":
            raise ValueError(
                "Grant graph edges require accepted public canonical relationships"
            )
        if not _HASH.fullmatch(str(attrs["gip_relationship_sha256"])):
            raise ValueError(
                "Grant graph edge requires its exact canonical relationship hash"
            )
        evidence = attrs["evidence_citation_ids"]
        if (
            not isinstance(evidence, list)
            or not 1 <= len(evidence) <= 20
            or any(
                not isinstance(value, str) or value not in citations
                for value in evidence
            )
        ):
            raise ValueError(
                "Grant graph edge evidence must bind loaded current citation nodes"
            )
        seen_edges.add(edge.id)


def expand_grant_graph(
    db: Any,
    principal: Principal,
    vector_store_id: str,
    chunks: list[ChunkRecord],
    *,
    filters: dict[str, Any],
    relation_types: tuple[str, ...],
    limit: int,
    hydrate: Callable[..., list[ChunkRecord]],
) -> tuple[list[ChunkRecord], dict[str, dict[str, Any]], dict[str, Any]]:
    """One bounded hop; preserve caller filters and reuse the existing ACL hydrator."""
    generation = _uuid(
        (filters.get("file_attribute_filters") or {}).get("gip_generation_id")
    )
    if not set(relation_types).issubset(GRANT_RELATIONS) or not relation_types:
        raise ValueError("Unsupported Grant graph relationship focus")
    if type(limit) is not int or not 0 <= limit <= 10:
        raise ValueError("Grant graph expansion limit must be 0..10")
    summary = {
        "enabled": True,
        "profile": GRANT_GRAPH_HANDLER_ID,
        "generation_id": generation,
        "applied": False,
        "inserted_chunk_count": 0,
    }
    if limit == 0 or not chunks:
        return [], {}, {**summary, "reason": "no_seed_or_zero_limit"}
    # The shared hydrator rechecks file-attribute filters and principal ACLs.
    # These four public API filters address chunk columns, so bind them in the
    # candidate SQL too (otherwise graph expansion could widen the request).
    column_filters = {}
    for key in ("document_id", "knowledge_base_id", "classification", "acl_bucket"):
        value = filters.get(key)
        if value is not None and not isinstance(value, str):
            raise ValueError("Grant graph chunk filters require string identities")
        column_filters[f"filter_{key}"] = value
    seed_ids = list(dict.fromkeys(chunk.document_id for chunk in chunks))[:10]
    rows = (
        db.execute(
            text("""
        WITH seeds AS (
          SELECT n.id, array_position(CAST(:seed_ids AS text[]), f.document_id) AS seed_rank
          FROM graph_nodes n
          JOIN vector_store_files f
            ON f.tenant_id=n.tenant_id AND f.business_instance_id=n.business_instance_id
           AND f.vector_store_id=n.vector_store_id AND f.status='completed'
           AND f.attributes->>'gip_search_document_id'=n.attributes->>'gip_search_document_id'
           AND f.attributes->>'gip_generation_id'=n.attributes->>'gip_generation_id'
           AND f.attributes->>'gip_source_version_sha256'=n.attributes->>'gip_source_version_sha256'
           AND f.attributes->>'gip_entity_id'=n.attributes->>'gip_entity_id'
           AND f.attributes->>'gip_entity_type'=n.node_type
           AND f.attributes->>'gip_citation_id'=n.attributes->>'gip_citation_id'
          WHERE n.tenant_id=:tenant_id AND n.business_instance_id=:biz_id
            AND n.vector_store_id=:store_id AND n.attributes->>'gip_generation_id'=:generation
            AND n.attributes->>'visibility'='public'
            AND f.document_id=ANY(CAST(:seed_ids AS text[]))
        )
        SELECT e.id AS edge_id, e.edge_type, e.source_node_id, e.target_node_id,
               e.attributes AS edge_attributes, c.id AS chunk_id, c.document_id
        FROM seeds s
        JOIN graph_edges e ON (e.source_node_id=s.id OR e.target_node_id=s.id)
          AND e.tenant_id=:tenant_id AND e.business_instance_id=:biz_id AND e.vector_store_id=:store_id
        JOIN graph_nodes n ON n.id=CASE WHEN e.source_node_id=s.id THEN e.target_node_id ELSE e.source_node_id END
          AND n.tenant_id=e.tenant_id AND n.business_instance_id=e.business_instance_id
          AND n.vector_store_id=e.vector_store_id
        JOIN vector_store_files f ON f.tenant_id=n.tenant_id AND f.business_instance_id=n.business_instance_id
          AND f.vector_store_id=n.vector_store_id AND f.status='completed'
          AND f.attributes->>'gip_search_document_id'=n.attributes->>'gip_search_document_id'
          AND f.attributes->>'gip_generation_id'=n.attributes->>'gip_generation_id'
          AND f.attributes->>'gip_source_version_sha256'=n.attributes->>'gip_source_version_sha256'
          AND f.attributes->>'gip_entity_id'=n.attributes->>'gip_entity_id'
          AND f.attributes->>'gip_entity_type'=n.node_type
          AND f.attributes->>'gip_citation_id'=n.attributes->>'gip_citation_id'
        JOIN documents d ON d.id=f.document_id AND d.tenant_id=f.tenant_id
          AND d.business_instance_id=f.business_instance_id AND d.status='active'
        JOIN chunks c ON c.document_id=d.id AND c.document_version_id=d.current_version_id
          AND c.tenant_id=d.tenant_id AND c.business_instance_id=d.business_instance_id
          AND c.vector_store_id=:store_id AND c.active=true
          AND c.security_level=0 AND c.classification='public'
        WHERE n.attributes->>'gip_generation_id'=:generation AND n.attributes->>'visibility'='public'
          AND e.attributes->>'gip_generation_id'=:generation
          AND e.attributes->>'review_status'='accepted' AND e.attributes->>'visibility'='public'
          AND e.edge_type=ANY(CAST(:relations AS text[]))
          AND (CAST(:filter_document_id AS text) IS NULL OR c.document_id=:filter_document_id)
          AND (CAST(:filter_knowledge_base_id AS text) IS NULL OR c.knowledge_base_id=:filter_knowledge_base_id)
          AND (CAST(:filter_classification AS text) IS NULL OR c.classification=:filter_classification)
          AND (CAST(:filter_acl_bucket AS text) IS NULL OR c.acl_bucket=:filter_acl_bucket)
        ORDER BY s.seed_rank, e.id, c.ordinal, c.id
        LIMIT :candidate_limit
    """),
            {
                "tenant_id": principal.tenant_id,
                "biz_id": principal.business_instance_id,
                "store_id": vector_store_id,
                "generation": generation,
                "seed_ids": seed_ids,
                "relations": list(relation_types),
                "candidate_limit": limit * 20,
                **column_filters,
            },
        )
        .mappings()
        .all()
    )
    by_chunk = {}
    for row in rows:
        by_chunk.setdefault(row["chunk_id"], row)
    candidates = [
        {"id": identifier, "payload": {"chunk_id": identifier}, "score": 0.5}
        for identifier in by_chunk
    ]
    hydrated = hydrate(
        db,
        principal,
        candidates,
        limit=limit * 20,
        filters={**filters, "vector_store_id": vector_store_id},
    )
    existing = {chunk.document_id for chunk in chunks}
    additions = []
    metadata = {}
    for chunk in hydrated:
        if (
            chunk.id not in by_chunk
            or chunk.document_id in existing
            or chunk.security_level != 0
            or chunk.classification != "public"
        ):
            continue
        row = by_chunk[chunk.id]
        attrs = row["edge_attributes"]
        # Fail closed on malformed historical/operator-written rows as well as
        # validating new graph loads; never echo arbitrary graph metadata.
        if not isinstance(attrs, dict):
            continue
        try:
            _uuid(attrs.get("gip_relationship_id"))
        except ValueError:
            continue
        evidence = attrs.get("evidence_citation_ids")
        if (
            attrs.get("gip_generation_id") != generation
            or attrs.get("review_status") != "accepted"
            or attrs.get("visibility") != "public"
            or not _HASH.fullmatch(str(attrs.get("gip_relationship_sha256")))
            or not isinstance(evidence, list)
            or not 1 <= len(evidence) <= 20
            or any(
                not isinstance(value, str) or not _CITATION.fullmatch(value)
                for value in evidence
            )
            or row["edge_type"] not in relation_types
        ):
            continue
        chunk.source = "grant_canonical_graph_expansion"
        metadata[chunk.id] = {
            "profile": GRANT_GRAPH_HANDLER_ID,
            "generation_id": generation,
            "relationship_id": attrs["gip_relationship_id"],
            "relationship_sha256": attrs["gip_relationship_sha256"],
            "relation_type": row["edge_type"],
            "source_node_id": row["source_node_id"],
            "target_node_id": row["target_node_id"],
            "evidence_citation_ids": attrs["evidence_citation_ids"],
        }
        additions.append(chunk)
        existing.add(chunk.document_id)
        if len(additions) >= limit:
            break
    return (
        additions,
        metadata,
        {
            **summary,
            "applied": bool(additions),
            "candidate_count": len(by_chunk),
            "inserted_chunk_count": len(additions),
        },
    )
