#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from topeka_pipeline_common import CODIFIED_SEED, stable_id, read_jsonl, write_json, write_jsonl


ORDINANCE_SECTION_EDGE_TYPES = {"ORDINANCE_AMENDS_SECTION", "ORDINANCE_REPEALS_SECTION", "ORDINANCE_ADOPTS_CODE"}


def graph_node_url(node: dict[str, Any]) -> str:
    props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    return str(props.get("citation_url") or props.get("source_url") or props.get("url") or "")


def graph_edge_url(edge: dict[str, Any]) -> str:
    props = edge.get("properties") if isinstance(edge.get("properties"), dict) else {}
    return str(props.get("citation_url") or props.get("source_url") or "")


def normalize_ordinance_number(value: str | None) -> str:
    if not value:
        return ""
    match = re.search(r"([A-Z]?\d{3,6}[A-Z]?)", value.upper())
    return match.group(1) if match else value.upper().strip()


def ordinance_index(nodes: list[dict[str, Any]]) -> dict[str, str]:
    indexed: dict[str, str] = {}
    for node in nodes:
        if node.get("type") != "ordinance":
            continue
        props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
        number = normalize_ordinance_number(str(props.get("ordinance") or node.get("label") or ""))
        if number:
            indexed[number] = str(node.get("id"))
    return indexed


def classify_relation(row: dict[str, Any], history_edge: dict[str, Any]) -> str:
    props = history_edge.get("properties") if isinstance(history_edge.get("properties"), dict) else {}
    text = " ".join(str(value or "") for value in [row.get("title"), props.get("raw"), props.get("section")]).lower()
    if "repeal" in text:
        return "ORDINANCE_REPEALS_SECTION"
    if "adopt" in text:
        return "ORDINANCE_ADOPTS_CODE"
    return "ORDINANCE_AMENDS_SECTION"


def enrich_graph_with_ordinances(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    ordinance_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    nodes_by_id = {str(node.get("id")): dict(node) for node in nodes if node.get("id")}
    edge_by_id = {str(edge.get("id")): dict(edge) for edge in edges if edge.get("id")}
    ordinance_node_by_number = ordinance_index(list(nodes_by_id.values()))
    ordinance_row_by_number = {
        normalize_ordinance_number(str(row.get("ordinance_number") or "")): row
        for row in ordinance_rows
        if normalize_ordinance_number(str(row.get("ordinance_number") or ""))
    }
    added_pdf_nodes = 0
    added_section_edges = 0
    matched_history_edges = 0

    for row_number, row in ordinance_row_by_number.items():
        pdf_url = str(row.get("pdf_url") or "")
        if not pdf_url:
            continue
        pdf_node_id = stable_id("topeka-ordinance-pdf", row_number, pdf_url)
        if pdf_node_id not in nodes_by_id:
            nodes_by_id[pdf_node_id] = {
                "id": pdf_node_id,
                "type": "ordinance_pdf",
                "label": str(row.get("title") or f"Ordinance {row_number}"),
                "properties": {
                    "ordinance_number": row_number,
                    "category": row.get("category") or "",
                    "year": row.get("year") or "",
                    "pdf_url": pdf_url,
                    "source_url": pdf_url,
                    "citation_url": pdf_url,
                    "sha256": row.get("sha256") or "",
                    "saved_path": row.get("saved_path") or "",
                },
            }
            added_pdf_nodes += 1
        codified_ord_node_id = ordinance_node_by_number.get(row_number)
        if codified_ord_node_id:
            edge_id = stable_id("edge", pdf_node_id, codified_ord_node_id, "SAME_ORDINANCE")
            edge_by_id.setdefault(edge_id, {
                "id": edge_id,
                "source": pdf_node_id,
                "target": codified_ord_node_id,
                "type": "SAME_ORDINANCE",
                "properties": {"ordinance_number": row_number, "source_url": pdf_url, "citation_url": pdf_url},
            })

    for edge in list(edge_by_id.values()):
        if edge.get("type") != "HAS_ORDINANCE_HISTORY":
            continue
        target = str(edge.get("target") or "")
        ord_node = nodes_by_id.get(target, {})
        props = ord_node.get("properties") if isinstance(ord_node.get("properties"), dict) else {}
        row_number = normalize_ordinance_number(str(props.get("ordinance") or ord_node.get("label") or ""))
        row = ordinance_row_by_number.get(row_number)
        if not row:
            continue
        pdf_url = str(row.get("pdf_url") or "")
        pdf_node_id = stable_id("topeka-ordinance-pdf", row_number, pdf_url)
        relation_type = classify_relation(row, edge)
        section_node_id = str(edge.get("source") or "")
        relation_edge_id = stable_id("edge", pdf_node_id, section_node_id, relation_type)
        edge_by_id.setdefault(relation_edge_id, {
            "id": relation_edge_id,
            "source": pdf_node_id,
            "target": section_node_id,
            "type": relation_type,
            "properties": {
                "ordinance_number": row_number,
                "pdf_url": pdf_url,
                "source_url": pdf_url,
                "citation_url": pdf_url,
                "derived_from_edge_id": edge.get("id"),
            },
        })
        matched_history_edges += 1
        added_section_edges += 1

    edge_counts = Counter(str(edge.get("type")) for edge in edge_by_id.values())
    summary = {
        "schema_version": 1,
        "graph_artifact": "topeka_municipal_code",
        "nodes": len(nodes_by_id),
        "edges": len(edge_by_id),
        "edge_types": dict(sorted(edge_counts.items())),
        "ordinance_pdf_nodes_added": added_pdf_nodes,
        "ordinance_section_edges_added": added_section_edges,
        "matched_history_edges": matched_history_edges,
        "url_coverage": {
            "nodes_with_citation_url": sum(1 for node in nodes_by_id.values() if graph_node_url(node)),
            "edges_with_citation_url": sum(1 for edge in edge_by_id.values() if graph_edge_url(edge)),
        },
    }
    return list(nodes_by_id.values()), list(edge_by_id.values()), summary


def extract_graph(source_output: Path, ordinance_manifest: Path | None, output_dir: Path) -> dict[str, Any]:
    nodes = read_jsonl(source_output / "nodes.jsonl")
    edges = read_jsonl(source_output / "edges.jsonl")
    ordinance_rows = read_jsonl(ordinance_manifest) if ordinance_manifest and ordinance_manifest.exists() else []
    enriched_nodes, enriched_edges, summary = enrich_graph_with_ordinances(nodes, edges, ordinance_rows)
    write_jsonl(output_dir / "nodes.jsonl", enriched_nodes)
    write_jsonl(output_dir / "edges.jsonl", enriched_edges)
    write_json(output_dir / "graph-summary.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Topeka Municipal Code GraphRAG artifact from seed JSONL files.")
    parser.add_argument("--source-output", type=Path, default=CODIFIED_SEED)
    parser.add_argument("--ordinance-manifest", type=Path)
    parser.add_argument("--manifest", type=Path, dest="legacy_manifest", help="Alias for --ordinance-manifest kept for source-package compatibility.")
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = extract_graph(args.source_output, args.ordinance_manifest or args.legacy_manifest, args.output_dir)
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
