from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel

from .models import CrawlReport, DefinitionRecord, GraphEdge, GraphNode, ParsedPage


def _write_jsonl(path: Path, records: Iterable[BaseModel]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(record.model_dump_json(exclude_none=True) + "\n")
            count += 1
    return count


def _write_dict_jsonl(path: Path, records: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
            count += 1
    return count


def export_corpus(
    output_dir: Path,
    pages: list[ParsedPage],
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    report: CrawlReport,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    sections = [page.section for page in pages if page.section]
    definitions: list[DefinitionRecord] = [item for page in pages for item in page.definitions]

    _write_jsonl(output_dir / "sections.jsonl", (s for s in sections if s is not None))
    _write_jsonl(output_dir / "definitions.jsonl", definitions)
    _write_jsonl(output_dir / "nodes.jsonl", nodes)
    _write_jsonl(output_dir / "edges.jsonl", edges)
    citation_url_count = _write_dict_jsonl(output_dir / "citation-url-map.jsonl", _citation_url_rows(pages))

    manifest = {
        "schema_version": "1.0",
        "status": _manifest_status(report),
        "jurisdiction": {"id": "ks-topeka", "name": "City of Topeka, Kansas", "state": "KS"},
        "code": "TMC",
        "root_url": report.root_url,
        "files": {
            "sections": "sections.jsonl",
            "definitions": "definitions.jsonl",
            "nodes": "nodes.jsonl",
            "edges": "edges.jsonl",
            "citation_url_map": "citation-url-map.jsonl",
            "report": "crawl_report.json",
        },
        "counts": {
            "sections": report.section_count,
            "definitions": report.definition_count,
            "nodes": report.node_count,
            "edges": report.edge_count,
            "citation_urls": citation_url_count,
        },
        "graph_edge_types": ["CONTAINS", "REFERENCES", "DEFINES", "HAS_ORDINANCE_HISTORY"],
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (output_dir / "crawl_report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")


def _manifest_status(report: CrawlReport) -> str:
    if report.pages_fetched == 0:
        return "failed_no_pages"
    if report.section_count == 0:
        return "failed_no_sections"
    if report.pages_failed:
        return "partial_with_failures"
    return "success"


def _citation_url_rows(pages: list[ParsedPage]) -> Iterable[dict]:
    for page in pages:
        yield {
            "record_type": "page",
            "id": page.id,
            "page_type": page.page_type,
            "citation": page.citation,
            "title": page.title,
            "source_url": page.url,
            "citation_url": page.url,
            "source_html_hash": page.source_html_hash,
        }
        if page.section:
            section = page.section
            yield {
                "record_type": "section",
                "id": section.id,
                "citation": section.citation,
                "title": section.title,
                "source_url": section.source_url,
                "citation_url": section.source_url,
                "content_hash": section.content_hash,
                "source_html_hash": section.source_html_hash,
                "retrieved_at": section.retrieved_at.isoformat(),
            }
        for definition in page.definitions:
            yield {
                "record_type": "definition",
                "id": definition.id,
                "section_id": definition.section_id,
                "section_citation": definition.section_citation,
                "term": definition.term,
                "source_url": definition.source_url,
                "citation_url": definition.source_url,
                "content_hash": definition.content_hash,
            }
