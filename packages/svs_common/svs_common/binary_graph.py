"""Security-preserving Graph RAG operations for Ghidra binary-analysis corpora."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal

from sqlalchemy import text

from .binary_records import (
    BINARY_FUNCTION_RELATIONS,
    BINARY_RELATIONS,
    BINARY_GRAPH_HANDLER_ID,
    function_node_id,
)
from .schemas import ChunkRecord, Principal


def _seed_node_ids(vector_store_id: str, chunks: list[ChunkRecord]) -> dict[str, str]:
    result: dict[str, str] = {}
    for chunk in chunks:
        metadata = chunk.metadata or {}
        binary_sha = metadata.get("binary_sha256")
        function_id = metadata.get("binary_function_id")
        if not isinstance(binary_sha, str) or len(binary_sha) != 64:
            continue
        if not isinstance(function_id, str) or not function_id:
            continue
        result[function_node_id(vector_store_id, binary_sha, function_id)] = chunk.id
    return result


def expand_binary_graph(
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
    """Expand semantic function seeds by one bounded function-to-function hop.

    Non-function nodes (strings/imports/globals/types) remain available through
    the explicit neighborhood endpoint; semantic search expansion returns only
    chunks that pass the existing EXAIS hydrator and ACL checks.
    """
    if type(limit) is not int or not 0 <= limit <= 10:
        raise ValueError("Binary graph expansion limit must be 0..10")
    if not relation_types or not set(relation_types).issubset(BINARY_FUNCTION_RELATIONS):
        raise ValueError("Binary semantic graph expansion supports only function relations")
    seed_map = _seed_node_ids(vector_store_id, chunks)
    summary = {
        "enabled": True,
        "profile": BINARY_GRAPH_HANDLER_ID,
        "applied": False,
        "seed_count": len(seed_map),
        "candidate_count": 0,
        "inserted_chunk_count": 0,
        "relation_types": list(relation_types),
    }
    if not seed_map or limit == 0:
        return [], {}, {**summary, "reason": "no_seed_or_zero_limit"}

    rows = db.execute(
        text("""
        WITH seed_nodes AS (
          SELECT id
          FROM graph_nodes
          WHERE tenant_id=:tenant_id
            AND business_instance_id=:biz_id
            AND vector_store_id=:store_id
            AND id=ANY(CAST(:seed_node_ids AS text[]))
            AND node_type='function'
        ), candidates AS (
          SELECT DISTINCT ON (related.id, e.edge_type)
            e.id AS edge_id,
            e.edge_type AS relation_type,
            seed.id AS seed_node_id,
            related.id AS related_node_id,
            related.attributes AS related_attributes,
            e.attributes AS edge_attributes
          FROM seed_nodes seed
          JOIN graph_edges e
            ON e.tenant_id=:tenant_id
           AND e.business_instance_id=:biz_id
           AND e.vector_store_id=:store_id
           AND e.edge_type=ANY(CAST(:relations AS text[]))
           AND (e.source_node_id=seed.id OR e.target_node_id=seed.id)
          JOIN graph_nodes related
            ON related.tenant_id=e.tenant_id
           AND related.business_instance_id=e.business_instance_id
           AND related.vector_store_id=e.vector_store_id
           AND related.node_type='function'
           AND related.id=CASE WHEN e.source_node_id=seed.id THEN e.target_node_id ELSE e.source_node_id END
          WHERE related.id <> seed.id
          ORDER BY related.id, e.edge_type, e.id
          LIMIT :candidate_limit
        )
        SELECT c.edge_id, c.relation_type, c.seed_node_id, c.related_node_id,
               c.edge_attributes, c.related_attributes,
               ch.id AS chunk_id, ch.document_id
        FROM candidates c
        JOIN chunks ch
          ON ch.tenant_id=:tenant_id
         AND ch.business_instance_id=:biz_id
         AND ch.vector_store_id=:store_id
         AND ch.active=true
         AND ch.metadata->>'binary_sha256'=c.related_attributes->>'binary_sha256'
         AND ch.metadata->>'binary_function_id'=c.related_attributes->>'binary_function_id'
        JOIN documents d
          ON d.id=ch.document_id
         AND d.tenant_id=ch.tenant_id
         AND d.business_instance_id=ch.business_instance_id
         AND d.current_version_id=ch.document_version_id
         AND d.status='active'
        ORDER BY c.edge_id, ch.ordinal
        LIMIT :candidate_limit
        """),
        {
            "tenant_id": principal.tenant_id,
            "biz_id": principal.business_instance_id,
            "store_id": vector_store_id,
            "seed_node_ids": list(seed_map),
            "relations": list(relation_types),
            "candidate_limit": max(limit * 20, 20),
        },
    ).mappings().all()

    fused: list[dict[str, Any]] = []
    graph_by_chunk: dict[str, dict[str, Any]] = {}
    seen_chunks: set[str] = set()
    seed_chunk_ids = set(seed_map.values())
    for rank, row in enumerate(rows, start=1):
        chunk_id = str(row["chunk_id"])
        if chunk_id in seen_chunks or chunk_id in seed_chunk_ids:
            continue
        seen_chunks.add(chunk_id)
        fused.append({
            "id": chunk_id,
            "score": max(0.05, 1.0 - ((rank - 1) * 0.01)),
            "payload": {"chunk_id": chunk_id},
        })
        graph_by_chunk[chunk_id] = {
            "profile": BINARY_GRAPH_HANDLER_ID,
            "relation_type": row["relation_type"],
            "edge_id": row["edge_id"],
            "source_node_id": row["seed_node_id"],
            "target_node_id": row["related_node_id"],
            "graph_distance": 1,
            "attributes": dict(row["edge_attributes"] or {}),
            "related": dict(row["related_attributes"] or {}),
            "provenance": {
                "engine": "ghidra",
                "tenant_id": principal.tenant_id,
                "business_instance_id": principal.business_instance_id,
                "vector_store_id": vector_store_id,
            },
        }
        if len(fused) >= max(limit * 4, limit):
            break

    if not fused:
        return [], {}, {**summary, "candidate_count": len(rows), "reason": "no_related_function_chunks"}

    safe_filters = dict(filters or {})
    safe_filters["vector_store_id"] = vector_store_id
    hydrated = hydrate(db, principal, fused, max(limit * 4, limit), filters=safe_filters)
    additions: list[ChunkRecord] = []
    hydrated_meta: dict[str, dict[str, Any]] = {}
    for chunk in hydrated:
        if chunk.id in seed_chunk_ids or chunk.id not in graph_by_chunk:
            continue
        additions.append(chunk)
        hydrated_meta[chunk.id] = graph_by_chunk[chunk.id]
        if len(additions) >= limit:
            break
    return additions, hydrated_meta, {
        **summary,
        "applied": bool(additions),
        "candidate_count": len(fused),
        "inserted_chunk_count": len(additions),
    }


def binary_graph_path(
    db: Any,
    principal: Principal,
    vector_store_id: str,
    *,
    source_binary_sha256: str,
    source_function_id: str,
    target_binary_sha256: str,
    target_function_id: str,
    relation_types: tuple[str, ...] = BINARY_FUNCTION_RELATIONS,
    max_hops: int = 3,
    direction: Literal["outbound", "inbound", "both"] = "both",
) -> dict[str, Any]:
    """Find a shortest bounded function path without making multi-hop normal retrieval."""
    if type(max_hops) is not int or not 1 <= max_hops <= 3:
        raise ValueError("Binary graph path max_hops must be 1..3")
    if direction not in {"outbound", "inbound", "both"}:
        raise ValueError("Binary graph path direction must be outbound, inbound, or both")
    if not relation_types or not set(relation_types).issubset(BINARY_FUNCTION_RELATIONS):
        raise ValueError("Binary graph path relation set is unsupported")

    source_node = function_node_id(vector_store_id, source_binary_sha256, source_function_id)
    target_node = function_node_id(vector_store_id, target_binary_sha256, target_function_id)
    if source_node == target_node:
        return {
            "object": "binary.graph_path",
            "vector_store_id": vector_store_id,
            "found": True,
            "hops": 0,
            "nodes": [source_node],
            "edges": [],
        }

    direction_clause = {
        "outbound": "e.source_node_id=walk.node_id",
        "inbound": "e.target_node_id=walk.node_id",
        "both": "(e.source_node_id=walk.node_id OR e.target_node_id=walk.node_id)",
    }[direction]
    next_node = {
        "outbound": "e.target_node_id",
        "inbound": "e.source_node_id",
        "both": "CASE WHEN e.source_node_id=walk.node_id THEN e.target_node_id ELSE e.source_node_id END",
    }[direction]
    sql = f"""
        WITH RECURSIVE walk AS (
          SELECT CAST(:source_node AS text) AS node_id,
                 ARRAY[CAST(:source_node AS text)]::text[] AS node_path,
                 ARRAY[]::text[] AS edge_path,
                 0 AS depth
          UNION ALL
          SELECT {next_node} AS node_id,
                 walk.node_path || {next_node},
                 walk.edge_path || e.id,
                 walk.depth + 1
          FROM walk
          JOIN graph_edges e
            ON e.tenant_id=:tenant_id
           AND e.business_instance_id=:biz_id
           AND e.vector_store_id=:store_id
           AND e.edge_type=ANY(CAST(:relations AS text[]))
           AND {direction_clause}
          JOIN graph_nodes n
            ON n.tenant_id=e.tenant_id
           AND n.business_instance_id=e.business_instance_id
           AND n.vector_store_id=e.vector_store_id
           AND n.id={next_node}
           AND n.node_type='function'
          WHERE walk.depth < :max_hops
            AND NOT ({next_node}=ANY(walk.node_path))
        )
        SELECT node_path, edge_path, depth
        FROM walk
        WHERE node_id=:target_node
        ORDER BY depth ASC
        LIMIT 1
    """
    row = db.execute(
        text(sql),
        {
            "tenant_id": principal.tenant_id,
            "biz_id": principal.business_instance_id,
            "store_id": vector_store_id,
            "source_node": source_node,
            "target_node": target_node,
            "relations": list(relation_types),
            "max_hops": max_hops,
        },
    ).mappings().first()
    if not row:
        return {
            "object": "binary.graph_path",
            "vector_store_id": vector_store_id,
            "found": False,
            "hops": None,
            "nodes": [],
            "edges": [],
        }

    node_ids = list(row["node_path"] or [])
    edge_ids = list(row["edge_path"] or [])
    node_rows = db.execute(
        text("""
        SELECT id, node_type, label, attributes
        FROM graph_nodes
        WHERE tenant_id=:tenant_id AND business_instance_id=:biz_id
          AND vector_store_id=:store_id AND id=ANY(CAST(:ids AS text[]))
        """),
        {"tenant_id": principal.tenant_id, "biz_id": principal.business_instance_id, "store_id": vector_store_id, "ids": node_ids},
    ).mappings().all()
    edge_rows = db.execute(
        text("""
        SELECT id, edge_type, source_node_id, target_node_id, attributes
        FROM graph_edges
        WHERE tenant_id=:tenant_id AND business_instance_id=:biz_id
          AND vector_store_id=:store_id AND id=ANY(CAST(:ids AS text[]))
        """),
        {"tenant_id": principal.tenant_id, "biz_id": principal.business_instance_id, "store_id": vector_store_id, "ids": edge_ids},
    ).mappings().all()
    nodes_by_id = {row["id"]: dict(row) for row in node_rows}
    edges_by_id = {row["id"]: dict(row) for row in edge_rows}
    return {
        "object": "binary.graph_path",
        "vector_store_id": vector_store_id,
        "found": True,
        "hops": int(row["depth"]),
        "nodes": [nodes_by_id[node_id] for node_id in node_ids if node_id in nodes_by_id],
        "edges": [edges_by_id[edge_id] for edge_id in edge_ids if edge_id in edges_by_id],
    }


def binary_graph_neighborhood(
    db: Any,
    principal: Principal,
    vector_store_id: str,
    *,
    binary_sha256: str,
    function_id: str,
    relation_types: tuple[str, ...] = BINARY_RELATIONS,
    limit: int = 100,
) -> dict[str, Any]:
    """Return a bounded one-hop neighborhood including non-semantic evidence nodes."""
    if type(limit) is not int or not 1 <= limit <= 500:
        raise ValueError("Binary graph neighborhood limit must be 1..500")
    if not relation_types or not set(relation_types).issubset(BINARY_RELATIONS):
        raise ValueError("Binary graph neighborhood relation set is unsupported")
    seed = function_node_id(vector_store_id, binary_sha256, function_id)
    rows = db.execute(
        text("""
        SELECT e.id AS edge_id, e.edge_type, e.source_node_id, e.target_node_id, e.attributes AS edge_attributes,
               n.id AS related_node_id, n.node_type, n.label, n.attributes AS node_attributes
        FROM graph_edges e
        JOIN graph_nodes n
          ON n.tenant_id=e.tenant_id AND n.business_instance_id=e.business_instance_id
         AND n.vector_store_id=e.vector_store_id
         AND n.id=CASE WHEN e.source_node_id=:seed THEN e.target_node_id ELSE e.source_node_id END
        WHERE e.tenant_id=:tenant_id AND e.business_instance_id=:biz_id
          AND e.vector_store_id=:store_id
          AND e.edge_type=ANY(CAST(:relations AS text[]))
          AND (e.source_node_id=:seed OR e.target_node_id=:seed)
        ORDER BY e.edge_type, e.id
        LIMIT :limit
        """),
        {
            "tenant_id": principal.tenant_id,
            "biz_id": principal.business_instance_id,
            "store_id": vector_store_id,
            "seed": seed,
            "relations": list(relation_types),
            "limit": limit,
        },
    ).mappings().all()
    return {
        "object": "binary.graph_neighborhood",
        "vector_store_id": vector_store_id,
        "seed": seed,
        "data": [dict(row) for row in rows],
    }
