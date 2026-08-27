#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from topeka_pipeline_common import DEFAULT_CELL, read_jsonl, write_json


REQUIRED_EDGE_TYPES = {"CONTAINS", "REFERENCES", "DEFINES", "HAS_ORDINANCE_HISTORY"}
ORDINANCE_SECTION_EDGE_TYPES = {"ORDINANCE_AMENDS_SECTION", "ORDINANCE_REPEALS_SECTION", "ORDINANCE_ADOPTS_CODE"}


def _props(row: dict[str, Any]) -> dict[str, Any]:
    return row.get("properties") if isinstance(row.get("properties"), dict) else {}


def has_citation_url(row: dict[str, Any]) -> bool:
    props = _props(row)
    return bool(props.get("citation_url") or props.get("source_url") or props.get("url"))


def build_eval(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    node_ids = {str(node.get("id")) for node in nodes if node.get("id")}
    edge_counts = Counter(str(edge.get("type")) for edge in edges)
    dangling_edges = [
        str(edge.get("id") or "")
        for edge in edges
        if str(edge.get("source") or "") not in node_ids or str(edge.get("target") or "") not in node_ids
    ]
    missing_required = sorted(REQUIRED_EDGE_TYPES - set(edge_counts))
    ordinance_pdf_nodes = [node for node in nodes if node.get("type") == "ordinance_pdf"]
    ordinance_section_edges = [edge for edge in edges if edge.get("type") in ORDINANCE_SECTION_EDGE_TYPES]
    cases = [
        {"name": "required_codified_edge_types", "passed": not missing_required, "missing": missing_required},
        {"name": "no_dangling_edges", "passed": not dangling_edges, "dangling_edge_ids": dangling_edges[:20]},
        {
            "name": "node_citation_urls",
            "passed": any(has_citation_url(node) for node in nodes if node.get("type") in {"section", "definition", "ordinance_pdf"}),
            "nodes_with_url": sum(1 for node in nodes if has_citation_url(node)),
        },
        {
            "name": "edge_citation_urls",
            "passed": any(has_citation_url(edge) for edge in edges if edge.get("type") in REQUIRED_EDGE_TYPES | ORDINANCE_SECTION_EDGE_TYPES),
            "edges_with_url": sum(1 for edge in edges if has_citation_url(edge)),
        },
        {
            "name": "ordinance_to_section_edges_when_supported",
            "passed": bool(ordinance_section_edges) if ordinance_pdf_nodes else True,
            "ordinance_pdf_nodes": len(ordinance_pdf_nodes),
            "ordinance_section_edges": len(ordinance_section_edges),
        },
    ]
    return {
        "schema_version": 1,
        "graph_artifact_eval": "topeka_municipal_code_graphrag",
        "nodes": len(nodes),
        "edges": len(edges),
        "edge_types": dict(sorted(edge_counts.items())),
        "passed": all(case["passed"] for case in cases),
        "cases": cases,
        "notes": "Artifact-level GraphRAG readiness eval. Loading still depends on an ExAIS graph load API path.",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate a Topeka Municipal Code GraphRAG artifact.")
    parser.add_argument("--cell", default=DEFAULT_CELL)
    parser.add_argument("--vector-store-id", default="vs_topeka_municipal_code_pending")
    parser.add_argument("--graph-artifact", type=Path, default=Path(".release/cells/ks-state-civics/graphrag/topeka-code"))
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    proof = build_eval(read_jsonl(args.graph_artifact / "nodes.jsonl"), read_jsonl(args.graph_artifact / "edges.jsonl"))
    proof["cell"] = args.cell
    proof["vector_store_id"] = args.vector_store_id
    if args.output:
        write_json(args.output, proof)
    print(json.dumps(proof, indent=2, sort_keys=True))
    if not proof["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
