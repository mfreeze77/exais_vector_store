#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from topeka_pipeline_common import (
    DEFAULT_CELL,
    DEFAULT_VECTOR_STORE_ID,
    api_json,
    default_api_base,
    default_headers,
    read_jsonl,
    write_json,
)


def validate_graph(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    node_ids = {str(node.get("id")) for node in nodes if node.get("id")}
    dangling = [
        str(edge.get("id") or "")
        for edge in edges
        if str(edge.get("source") or "") not in node_ids or str(edge.get("target") or "") not in node_ids
    ]
    return {
        "nodes": len(nodes),
        "edges": len(edges),
        "dangling_edges": len(dangling),
        "dangling_edge_ids": dangling[:20],
    }


def load_graph(
    *,
    api_base: str,
    graph_api_path: str | None,
    headers: dict[str, str],
    vector_store_id: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    dry_run: bool,
    timeout: int,
    cell: str = DEFAULT_CELL,
    transport: str = "auto",
) -> dict[str, Any]:
    validation = validate_graph(nodes, edges)
    if validation["dangling_edges"]:
        return {"status": "failed_validation", "dry_run": dry_run, **validation}
    if dry_run:
        return {"status": "dry_run", "dry_run": True, "vector_store_id": vector_store_id, **validation}
    if not graph_api_path:
        graph_api_path = f"/v1/vector_stores/{vector_store_id}/graph"
    payload = {"nodes": nodes, "edges": edges, "replace": True}
    response = api_json(
        "POST",
        api_base,
        graph_api_path,
        payload,
        headers=headers,
        timeout=timeout,
        cell=cell,
        transport=transport,
    )
    return {"status": "submitted", "dry_run": False, "vector_store_id": vector_store_id, **validation, "response": response}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load Topeka GraphRAG artifacts through an ExAIS graph API endpoint.")
    parser.add_argument("--cell", default=DEFAULT_CELL)
    parser.add_argument("--api", default=None)
    parser.add_argument("--graph-artifact", type=Path, required=True)
    parser.add_argument("--graph-api-path", default=os.getenv("EXAIS_GRAPH_LOAD_PATH"))
    parser.add_argument("--vector-store-id", default=os.getenv("SVS_TOPEKA_VECTOR_STORE_ID", DEFAULT_VECTOR_STORE_ID))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--api-timeout-seconds", type=int, default=180)
    parser.add_argument("--auth-token-file", type=Path)
    parser.add_argument("--api-transport", default="auto", choices=["auto", "host-curl", "api-container", "docker-network"])
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    nodes = read_jsonl(args.graph_artifact / "nodes.jsonl")
    edges = read_jsonl(args.graph_artifact / "edges.jsonl")
    try:
        result = load_graph(
            api_base=args.api or default_api_base(args.cell),
            graph_api_path=args.graph_api_path,
            headers=default_headers(cell=args.cell, auth_token_file=args.auth_token_file),
            vector_store_id=args.vector_store_id,
            nodes=nodes,
            edges=edges,
            dry_run=args.dry_run,
            timeout=args.api_timeout_seconds,
            cell=args.cell,
            transport=args.api_transport,
        )
    except RuntimeError as exc:
        result = {
            "status": "failed_api_load",
            "dry_run": False,
            "vector_store_id": args.vector_store_id,
            "error": str(exc),
            **validate_graph(nodes, edges),
        }
        if args.output:
            write_json(args.output, result)
        print(json.dumps(result, indent=2, sort_keys=True))
        raise SystemExit(4) from exc
    if args.output:
        write_json(args.output, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    if result.get("status") == "failed_validation":
        raise SystemExit(2)


if __name__ == "__main__":
    main()
