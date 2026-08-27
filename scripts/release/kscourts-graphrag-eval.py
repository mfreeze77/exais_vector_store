#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate a Kansas court-decision GraphRAG artifact.")
    parser.add_argument("--graph-artifact", type=Path, required=True, help="Directory containing nodes.jsonl and edges.jsonl.")
    parser.add_argument("--output", type=Path, help="Optional JSON proof output path.")
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{line_number}: invalid JSONL row: {exc}") from exc
    return rows


def _first_edge(edges: list[dict[str, Any]], edge_type: str) -> dict[str, Any] | None:
    return next((edge for edge in edges if edge.get("type") == edge_type), None)


def _node_label(nodes_by_id: dict[str, dict[str, Any]], node_id: str | None) -> str | None:
    if not node_id:
        return None
    node = nodes_by_id.get(node_id)
    if not node:
        return None
    return str(node.get("label") or node.get("key") or node_id)


def _edge_provenance(edge: dict[str, Any] | None) -> dict[str, Any]:
    provenance = edge.get("provenance") if edge else None
    return provenance if isinstance(provenance, dict) else {}


def build_eval(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    nodes_by_id = {str(node["id"]): node for node in nodes if "id" in node}

    cites_case = _first_edge(edges, "cites_case")
    related_case = _first_edge(edges, "same_docket") or _first_edge(edges, "related_party")
    filter_edges = [
        edge for edge in edges
        if edge.get("type") in {"same_court", "same_year", "published_status"}
    ]
    filter_nodes = [
        node for node in nodes
        if node.get("type") in {"court", "year", "publication_status"}
    ]

    authority_trail = {
        "name": "authority_trail",
        "passed": bool(cites_case and cites_case.get("source") in nodes_by_id and cites_case.get("target") in nodes_by_id),
        "source_opinion": _node_label(nodes_by_id, cites_case.get("source") if cites_case else None),
        "cited_authority": _node_label(nodes_by_id, cites_case.get("target") if cites_case else None),
        "evidence": _edge_provenance(cites_case).get("evidence"),
        "method": _edge_provenance(cites_case).get("extraction_method"),
        "confidence": _edge_provenance(cites_case).get("confidence"),
    }
    cited_by = {
        "name": "cited_by",
        "passed": authority_trail["passed"],
        "authority": authority_trail["cited_authority"],
        "cited_by_opinion": authority_trail["source_opinion"],
        "edge_type": "cites_case" if cites_case else None,
    }
    related = {
        "name": "related_case",
        "passed": bool(
            related_case
            and related_case.get("source") in nodes_by_id
            and related_case.get("target") in nodes_by_id
        ),
        "edge_type": related_case.get("type") if related_case else None,
        "left": _node_label(nodes_by_id, related_case.get("source") if related_case else None),
        "right": _node_label(nodes_by_id, related_case.get("target") if related_case else None),
        "attributes": related_case.get("attributes", {}) if related_case else {},
    }
    filter_bound = {
        "name": "filter_bound",
        "passed": bool(filter_nodes and filter_edges),
        "filter_node_counts": {
            "court": sum(1 for node in filter_nodes if node.get("type") == "court"),
            "year": sum(1 for node in filter_nodes if node.get("type") == "year"),
            "publication_status": sum(1 for node in filter_nodes if node.get("type") == "publication_status"),
        },
        "filter_edge_counts": {
            "same_court": sum(1 for edge in filter_edges if edge.get("type") == "same_court"),
            "same_year": sum(1 for edge in filter_edges if edge.get("type") == "same_year"),
            "published_status": sum(1 for edge in filter_edges if edge.get("type") == "published_status"),
        },
    }

    cases = [authority_trail, cited_by, related, filter_bound]
    return {
        "schema_version": 1,
        "graph_artifact_eval": "kscourts_graphrag_readiness",
        "nodes": len(nodes),
        "edges": len(edges),
        "passed": all(case["passed"] for case in cases),
        "cases": cases,
        "notes": (
            "Artifact-level GraphRAG readiness eval only. This proves deterministic graph expansion "
            "signals exist before wiring them into the retrieval API."
        ),
    }


def main() -> None:
    args = parse_args()
    artifact_dir = args.graph_artifact
    nodes = read_jsonl(artifact_dir / "nodes.jsonl")
    edges = read_jsonl(artifact_dir / "edges.jsonl")
    proof = build_eval(nodes, edges)
    payload = json.dumps(proof, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload)
    if not proof["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
