#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "svs_common"))

from svs_common.kscourts_graphrag import KSCourtsChunkRecord, build_graph  # noqa: E402


DEFAULT_VECTOR_STORE_ID = "vs_a0d3ac76893e4f6f83bf2992"
DEFAULT_TENANT_ID = "ten_ks_state_civics"
DEFAULT_BUSINESS_INSTANCE_ID = "biz_ks_state_civics"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract a deterministic Kansas court-decision GraphRAG artifact.")
    parser.add_argument("--vector-store-id", default=os.getenv("SVS_KSCOURTS_VECTOR_STORE_ID", DEFAULT_VECTOR_STORE_ID))
    parser.add_argument("--tenant-id", default=os.getenv("SVS_TENANT_ID", DEFAULT_TENANT_ID))
    parser.add_argument("--business-instance-id", default=os.getenv("SVS_BUSINESS_INSTANCE_ID", DEFAULT_BUSINESS_INSTANCE_ID))
    parser.add_argument("--max-security-level", default="9")
    parser.add_argument("--document-limit", type=int, default=50)
    parser.add_argument("--max-chunks-per-document", type=int, default=8)
    parser.add_argument("--include-docket", action="append", default=[])
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def normalize_conninfo() -> str:
    conninfo = os.environ.get("DATABASE_URL")
    if not conninfo:
        conninfo = "postgresql://svs_app:svs_app_dev_password@postgres:5432/svs"
    return conninfo.replace("postgresql+psycopg://", "postgresql://")


def _selected_document_sql(include_dockets: list[str]) -> tuple[str, dict[str, Any]]:
    params: dict[str, Any] = {"include_dockets": include_dockets}
    required_where = "false"
    if include_dockets:
        required_where = "attributes->>'docket_number' = ANY(%(include_dockets)s)"
    return (
        f"""
        WITH sampled_documents AS (
            SELECT document_id
            FROM vector_store_files
            WHERE vector_store_id = %(vector_store_id)s
              AND tenant_id = %(tenant_id)s
              AND business_instance_id = %(business_instance_id)s
              AND status = 'completed'
            ORDER BY md5(document_id)
            LIMIT %(document_limit)s
        ),
        required_documents AS (
            SELECT document_id
            FROM vector_store_files
            WHERE vector_store_id = %(vector_store_id)s
              AND tenant_id = %(tenant_id)s
              AND business_instance_id = %(business_instance_id)s
              AND status = 'completed'
              AND {required_where}
        ),
        selected_documents AS (
            SELECT document_id FROM sampled_documents
            UNION
            SELECT document_id FROM required_documents
        ),
        ranked_chunks AS (
            SELECT c.id AS chunk_id,
                   c.vector_store_id,
                   c.document_id,
                   c.ordinal AS chunk_ordinal,
                   c.text,
                   vsf.attributes,
                   row_number() OVER (PARTITION BY c.document_id ORDER BY c.ordinal) AS chunk_rank
            FROM chunks c
            JOIN selected_documents sd ON sd.document_id = c.document_id
            JOIN vector_store_files vsf
              ON vsf.document_id = c.document_id
             AND vsf.vector_store_id = c.vector_store_id
             AND vsf.tenant_id = c.tenant_id
             AND vsf.business_instance_id = c.business_instance_id
            WHERE c.vector_store_id = %(vector_store_id)s
              AND c.tenant_id = %(tenant_id)s
              AND c.business_instance_id = %(business_instance_id)s
              AND c.active = true
        )
        SELECT chunk_id, vector_store_id, document_id, chunk_ordinal, text, attributes
        FROM ranked_chunks
        WHERE (%(max_chunks_per_document)s <= 0 OR chunk_rank <= %(max_chunks_per_document)s)
        ORDER BY md5(document_id), chunk_ordinal
        """,
        params,
    )


def fetch_records(args: argparse.Namespace) -> list[KSCourtsChunkRecord]:
    sql, extra_params = _selected_document_sql([docket for docket in args.include_docket if docket])
    params = {
        "vector_store_id": args.vector_store_id,
        "tenant_id": args.tenant_id,
        "business_instance_id": args.business_instance_id,
        "document_limit": args.document_limit,
        "max_chunks_per_document": args.max_chunks_per_document,
        **extra_params,
    }
    with psycopg.connect(normalize_conninfo(), row_factory=dict_row) as conn:
        conn.execute("select set_config('svs.tenant_id', %s, true)", (args.tenant_id,))
        conn.execute("select set_config('svs.business_instance_id', %s, true)", (args.business_instance_id,))
        conn.execute("select set_config('svs.max_security_level', %s, true)", (str(args.max_security_level),))
        rows = conn.execute(sql, params).fetchall()
    return [
        KSCourtsChunkRecord(
            vector_store_id=str(row["vector_store_id"]),
            document_id=str(row["document_id"]),
            chunk_id=str(row["chunk_id"]),
            chunk_ordinal=int(row["chunk_ordinal"]),
            text=str(row["text"] or ""),
            attributes=dict(row["attributes"] or {}),
        )
        for row in rows
    ]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def write_artifact(output_dir: Path, graph: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_dir / "nodes.jsonl", graph["nodes"])
    write_jsonl(output_dir / "edges.jsonl", graph["edges"])
    (output_dir / "summary.json").write_text(json.dumps(graph["summary"], indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    records = fetch_records(args)
    if not records:
        raise SystemExit("No indexed Kansas chunks matched the extraction sample.")
    graph = build_graph(records)
    if args.output_dir and not args.dry_run:
        write_artifact(args.output_dir, graph)
    print(json.dumps(graph["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
