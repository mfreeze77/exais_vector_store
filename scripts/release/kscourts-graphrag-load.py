#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


DEFAULT_VECTOR_STORE_ID = "vs_a0d3ac76893e4f6f83bf2992"
DEFAULT_TENANT_ID = "ten_ks_state_civics"
DEFAULT_BUSINESS_INSTANCE_ID = "biz_ks_state_civics"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load Kansas court-decision GraphRAG JSONL artifacts into Postgres.")
    parser.add_argument("--graph-artifact", type=Path, required=True, help="Directory containing nodes.jsonl and edges.jsonl.")
    parser.add_argument("--vector-store-id", default=os.getenv("SVS_KSCOURTS_VECTOR_STORE_ID", DEFAULT_VECTOR_STORE_ID))
    parser.add_argument("--tenant-id", default=os.getenv("SVS_TENANT_ID", DEFAULT_TENANT_ID))
    parser.add_argument("--business-instance-id", default=os.getenv("SVS_BUSINESS_INSTANCE_ID", DEFAULT_BUSINESS_INSTANCE_ID))
    parser.add_argument("--max-security-level", default="9")
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--no-replace", action="store_true", help="Upsert rows without deleting the existing graph first.")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def normalize_conninfo() -> str:
    conninfo = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_URL_SYNC")
    if not conninfo:
        conninfo = "postgresql://svs_app:svs_app_dev_password@postgres:5432/svs"
    return conninfo.replace("postgresql+psycopg://", "postgresql://")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_number}: invalid JSONL row: {exc}") from exc
            if not isinstance(row, dict):
                raise SystemExit(f"{path}:{line_number}: expected object row")
            rows.append(row)
    return rows


def batched(rows: list[dict[str, Any]], batch_size: int) -> list[list[dict[str, Any]]]:
    size = max(1, batch_size)
    return [rows[index:index + size] for index in range(0, len(rows), size)]


def node_params(rows: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    params: list[dict[str, Any]] = []
    for row in rows:
        params.append({
            "id": str(row["id"]),
            "tenant_id": args.tenant_id,
            "business_instance_id": args.business_instance_id,
            "vector_store_id": args.vector_store_id,
            "node_type": str(row["type"]),
            "node_key": str(row["key"]),
            "label": str(row["label"]),
            "attributes": Jsonb(dict(row.get("attributes") or {})),
            "provenance": Jsonb(list(row.get("provenance") or [])),
        })
    return params


def edge_params(rows: list[dict[str, Any]], node_ids: set[str], args: argparse.Namespace) -> tuple[list[dict[str, Any]], int]:
    params: list[dict[str, Any]] = []
    skipped = 0
    for row in rows:
        source = str(row["source"])
        target = str(row["target"])
        if source not in node_ids or target not in node_ids:
            skipped += 1
            continue
        params.append({
            "id": str(row["id"]),
            "tenant_id": args.tenant_id,
            "business_instance_id": args.business_instance_id,
            "vector_store_id": args.vector_store_id,
            "edge_type": str(row["type"]),
            "source_node_id": source,
            "target_node_id": target,
            "attributes": Jsonb(dict(row.get("attributes") or {})),
            "provenance": Jsonb(dict(row.get("provenance") or {})),
        })
    return params, skipped


def _set_context(conn: psycopg.Connection, args: argparse.Namespace) -> None:
    conn.execute("select set_config('svs.tenant_id', %s, true)", (args.tenant_id,))
    conn.execute("select set_config('svs.business_instance_id', %s, true)", (args.business_instance_id,))
    conn.execute("select set_config('svs.max_security_level', %s, true)", (str(args.max_security_level),))


def load_graph(args: argparse.Namespace, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    node_rows = node_params(nodes, args)
    edge_rows, skipped_edges = edge_params(edges, {row["id"] for row in node_rows}, args)
    if args.dry_run:
        return {
            "dry_run": True,
            "nodes": len(node_rows),
            "edges": len(edge_rows),
            "skipped_edges": skipped_edges,
            "replaced": not args.no_replace,
        }

    node_sql = """
        INSERT INTO graph_nodes (
          id, tenant_id, business_instance_id, vector_store_id,
          node_type, node_key, label, attributes, provenance
        )
        VALUES (
          %(id)s, %(tenant_id)s, %(business_instance_id)s, %(vector_store_id)s,
          %(node_type)s, %(node_key)s, %(label)s, %(attributes)s, %(provenance)s
        )
        ON CONFLICT (tenant_id, business_instance_id, vector_store_id, id) DO UPDATE
        SET node_type=excluded.node_type,
            node_key=excluded.node_key,
            label=excluded.label,
            attributes=excluded.attributes,
            provenance=excluded.provenance,
            updated_at=now()
    """
    edge_sql = """
        INSERT INTO graph_edges (
          id, tenant_id, business_instance_id, vector_store_id,
          edge_type, source_node_id, target_node_id, attributes, provenance
        )
        VALUES (
          %(id)s, %(tenant_id)s, %(business_instance_id)s, %(vector_store_id)s,
          %(edge_type)s, %(source_node_id)s, %(target_node_id)s, %(attributes)s, %(provenance)s
        )
        ON CONFLICT (tenant_id, business_instance_id, vector_store_id, id) DO UPDATE
        SET edge_type=excluded.edge_type,
            source_node_id=excluded.source_node_id,
            target_node_id=excluded.target_node_id,
            attributes=excluded.attributes,
            provenance=excluded.provenance,
            updated_at=now()
    """
    with psycopg.connect(normalize_conninfo(), row_factory=dict_row) as conn:
        _set_context(conn, args)
        if not args.no_replace:
            conn.execute(
                """
                DELETE FROM graph_edges
                WHERE tenant_id=%s AND business_instance_id=%s AND vector_store_id=%s
                """,
                (args.tenant_id, args.business_instance_id, args.vector_store_id),
            )
            conn.execute(
                """
                DELETE FROM graph_nodes
                WHERE tenant_id=%s AND business_instance_id=%s AND vector_store_id=%s
                """,
                (args.tenant_id, args.business_instance_id, args.vector_store_id),
            )
        with conn.cursor() as cur:
            for batch in batched(node_rows, args.batch_size):
                cur.executemany(node_sql, batch)
            for batch in batched(edge_rows, args.batch_size):
                cur.executemany(edge_sql, batch)
        counts = conn.execute(
            """
            SELECT
              (SELECT count(*) FROM graph_nodes WHERE vector_store_id=%s) AS nodes,
              (SELECT count(*) FROM graph_edges WHERE vector_store_id=%s) AS edges
            """,
            (args.vector_store_id, args.vector_store_id),
        ).fetchone()
        conn.commit()
    return {
        "dry_run": False,
        "nodes": int(counts["nodes"]),
        "edges": int(counts["edges"]),
        "loaded_nodes": len(node_rows),
        "loaded_edges": len(edge_rows),
        "skipped_edges": skipped_edges,
        "replaced": not args.no_replace,
    }


def main() -> None:
    args = parse_args()
    nodes = read_jsonl(args.graph_artifact / "nodes.jsonl")
    edges = read_jsonl(args.graph_artifact / "edges.jsonl")
    result = load_graph(args, nodes, edges)
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["skipped_edges"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
