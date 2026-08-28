#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from topeka_pipeline_common import read_jsonl, sha256_bytes, sha256_text, write_json, write_jsonl


REQUIRED_FILES = (
    "sections.jsonl",
    "definitions.jsonl",
    "nodes.jsonl",
    "edges.jsonl",
    "citation-url-map.jsonl",
    "url-manifest.jsonl",
    "expected-fetch-urls.jsonl",
    "manifest.json",
    "crawl_report.json",
    "quality-report.json",
)


class CombineError(RuntimeError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise CombineError(f"expected JSON object: {path}")
    return loaded


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def batch_sort_key(path: Path) -> tuple[int, str]:
    suffix = path.name.removeprefix("batch-")
    try:
        return int(suffix), path.name
    except ValueError:
        return 10_000_000, path.name


def discover_batch_dirs(batch_root: Path) -> list[Path]:
    batches = sorted(
        [path for path in batch_root.iterdir() if path.is_dir() and path.name.startswith("batch-")],
        key=batch_sort_key,
    )
    if not batches:
        raise CombineError(f"no batch-* directories found under {batch_root}")
    return batches


def require_batch_files(batch_dir: Path) -> None:
    missing = [name for name in REQUIRED_FILES if not (batch_dir / name).is_file()]
    if missing:
        raise CombineError(f"{batch_dir}: missing required files: {', '.join(missing)}")


def require_quality_passed(batch_dir: Path) -> dict[str, Any]:
    report = load_json(batch_dir / "quality-report.json")
    if report.get("passed") is not True:
        raise CombineError(f"{batch_dir}: quality-report.json did not pass")
    if report.get("section_coverage", {}).get("missing"):
        raise CombineError(f"{batch_dir}: quality report has missing URLs")
    if report.get("crawl_report", {}).get("pages_failed"):
        raise CombineError(f"{batch_dir}: quality report has failed pages")
    return report


def row_key(row: dict[str, Any], *fields: str) -> tuple[str, ...]:
    return tuple(str(row.get(field) or "") for field in fields)


def merge_sections(target: OrderedDict[str, dict[str, Any]], rows: list[dict[str, Any]], batch_dir: Path) -> None:
    for row in rows:
        key = str(row.get("id") or "")
        if not key:
            raise CombineError(f"{batch_dir}: section row missing id")
        existing = target.get(key)
        if existing:
            existing_hash = str(existing.get("content_hash") or "")
            row_hash = str(row.get("content_hash") or "")
            if existing_hash and row_hash and existing_hash != row_hash:
                raise CombineError(f"{batch_dir}: duplicate section id with different content_hash: {key}")
            continue
        target[key] = row


def merge_by_id(target: OrderedDict[str, dict[str, Any]], rows: list[dict[str, Any]], batch_dir: Path, label: str) -> None:
    for index, row in enumerate(rows):
        key = str(row.get("id") or "")
        if not key:
            key = f"missing-id:{batch_dir.name}:{label}:{index}:{sha256_text(canonical_json(row))}"
        existing = target.get(key)
        if existing and canonical_json(existing) != canonical_json(row):
            existing_hash = str(existing.get("content_hash") or "")
            row_hash = str(row.get("content_hash") or "")
            if existing_hash and row_hash and existing_hash != row_hash:
                raise CombineError(f"{batch_dir}: duplicate {label} id with different content_hash: {key}")
        target.setdefault(key, row)


def merge_nodes(target: OrderedDict[str, dict[str, Any]], rows: list[dict[str, Any]], batch_dir: Path) -> None:
    for row in rows:
        key = str(row.get("id") or "")
        if not key:
            raise CombineError(f"{batch_dir}: graph node missing id")
        existing = target.get(key)
        if not existing:
            target[key] = row
            continue
        existing_props = existing.get("properties") if isinstance(existing.get("properties"), dict) else {}
        row_props = row.get("properties") if isinstance(row.get("properties"), dict) else {}
        merged = {**existing, **row}
        merged["properties"] = {**existing_props, **row_props}
        if existing.get("type") == "section" and row.get("type") != "section":
            merged["type"] = "section"
        target[key] = merged


def edge_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    edge_type = str(row.get("type") or "")
    extra = "" if edge_type == "CONTAINS" else canonical_json(row.get("properties") or {})
    return str(row.get("source") or ""), str(row.get("target") or ""), edge_type, extra


def merge_edges(target: OrderedDict[tuple[str, str, str, str], dict[str, Any]], rows: list[dict[str, Any]], batch_dir: Path) -> None:
    for row in rows:
        key = edge_key(row)
        if not key[0] or not key[1] or not key[2]:
            raise CombineError(f"{batch_dir}: graph edge missing source, target, or type")
        target.setdefault(key, row)


def citation_key(row: dict[str, Any], batch_dir: Path, index: int) -> tuple[str, str, str, str]:
    record_type = str(row.get("record_type") or "")
    row_id = str(row.get("id") or "")
    source_url = str(row.get("source_url") or "")
    term = str(row.get("term") or "")
    if not record_type or not row_id:
        row_id = f"missing-id:{batch_dir.name}:citation:{index}:{sha256_text(canonical_json(row))}"
    return record_type, row_id, source_url, term


def merge_citations(target: OrderedDict[tuple[str, str, str, str], dict[str, Any]], rows: list[dict[str, Any]], batch_dir: Path) -> None:
    for index, row in enumerate(rows):
        target.setdefault(citation_key(row, batch_dir, index), row)


def merge_url_manifest(
    target: OrderedDict[str, dict[str, Any]],
    rows: list[dict[str, Any]],
    expected_urls: set[str],
    batch_dir: Path,
) -> None:
    for index, row in enumerate(rows):
        key = str(row.get("node_id") or row.get("url") or "")
        if not key:
            raise CombineError(f"{batch_dir}: url manifest row missing node_id/url at index {index}")
        merged = dict(row)
        if str(merged.get("url") or "") in expected_urls:
            merged["fetch_required"] = True
        existing = target.get(key)
        if existing:
            existing["fetch_required"] = bool(existing.get("fetch_required")) or bool(merged.get("fetch_required"))
            continue
        target[key] = merged


def copy_evidence(batch_dirs: list[Path], output_dir: Path, subdir: str) -> int:
    destination_dir = output_dir / subdir
    destination_dir.mkdir(parents=True, exist_ok=True)
    for batch_dir in batch_dirs:
        source_dir = batch_dir / subdir
        if not source_dir.is_dir():
            raise CombineError(f"{batch_dir}: missing {subdir}/ evidence directory")
        for source in sorted(source_dir.iterdir()):
            if not source.is_file():
                continue
            destination = destination_dir / source.name
            if destination.exists():
                if sha256_bytes(destination.read_bytes()) != sha256_bytes(source.read_bytes()):
                    raise CombineError(f"{batch_dir}: conflicting evidence file: {subdir}/{source.name}")
            else:
                shutil.copy2(source, destination)
    return len([path for path in destination_dir.iterdir() if path.is_file()])


def build_crawl_report(batch_dirs: list[Path], sections: list[dict[str, Any]], definitions: list[dict[str, Any]], nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
    reports = [load_json(batch_dir / "crawl_report.json") for batch_dir in batch_dirs]
    started_values = [str(report.get("started_at") or "") for report in reports if report.get("started_at")]
    finished_values = [str(report.get("finished_at") or "") for report in reports if report.get("finished_at")]
    failures = [failure for report in reports for failure in (report.get("failures") or [])]
    return {
        "started_at": min(started_values) if started_values else None,
        "finished_at": max(finished_values) if finished_values else datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "root_url": reports[0].get("root_url") if reports else "https://topeka.municipal.codes/TMC",
        "pages_seen": sum(int(report.get("pages_seen") or 0) for report in reports),
        "pages_fetched": sum(int(report.get("pages_fetched") or 0) for report in reports),
        "pages_failed": sum(int(report.get("pages_failed") or 0) for report in reports),
        "section_count": len(sections),
        "definition_count": len(definitions),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "failures": failures,
        "fetcher": "decodo-batch-combined",
    }


def build_manifest(
    *,
    sections: list[dict[str, Any]],
    definitions: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    citations: list[dict[str, Any]],
    url_manifest: list[dict[str, Any]],
    expected_fetch_urls: list[dict[str, Any]],
    crawl_report: dict[str, Any],
    raw_count: int,
    network_count: int,
) -> dict[str, Any]:
    edge_types = sorted({str(row.get("type") or "") for row in edges if row.get("type")})
    status = "success"
    if crawl_report["pages_fetched"] == 0:
        status = "failed_no_pages"
    elif crawl_report["section_count"] == 0:
        status = "failed_no_sections"
    elif crawl_report["pages_failed"]:
        status = "partial_with_failures"
    return {
        "schema_version": "1.0",
        "status": status,
        "jurisdiction": {"id": "ks-topeka", "name": "City of Topeka, Kansas", "state": "KS"},
        "code": "TMC",
        "root_url": crawl_report.get("root_url") or "https://topeka.municipal.codes/TMC",
        "files": {
            "sections": "sections.jsonl",
            "definitions": "definitions.jsonl",
            "nodes": "nodes.jsonl",
            "edges": "edges.jsonl",
            "citation_url_map": "citation-url-map.jsonl",
            "url_manifest": "url-manifest.jsonl",
            "expected_fetch_urls": "expected-fetch-urls.jsonl",
            "report": "crawl_report.json",
        },
        "counts": {
            "sections": len(sections),
            "definitions": len(definitions),
            "nodes": len(nodes),
            "edges": len(edges),
            "citation_urls": len(citations),
            "url_manifest_rows": len(url_manifest),
            "expected_fetch_urls": len(expected_fetch_urls),
            "raw_html_files": raw_count,
            "network_files": network_count,
        },
        "graph_edge_types": edge_types,
        "source_batches": {
            "count": len(crawl_report.get("source_batch_names") or []),
            "names": crawl_report.get("source_batch_names") or [],
        },
        "boundary": "Artifact-only batch consolidation. This script does not call ExAIS ingestion, embedding providers, Qdrant, Postgres, MinIO, OpenSearch, or graph write paths.",
    }


def combine_batches(batch_root: Path, output_dir: Path) -> dict[str, Any]:
    batch_dirs = discover_batch_dirs(batch_root)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise CombineError(f"output directory already exists and is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    sections_by_id: OrderedDict[str, dict[str, Any]] = OrderedDict()
    definitions_by_id: OrderedDict[str, dict[str, Any]] = OrderedDict()
    nodes_by_id: OrderedDict[str, dict[str, Any]] = OrderedDict()
    edges_by_key: OrderedDict[tuple[str, str, str, str], dict[str, Any]] = OrderedDict()
    citations_by_key: OrderedDict[tuple[str, str, str, str], dict[str, Any]] = OrderedDict()
    expected_by_url: OrderedDict[str, dict[str, Any]] = OrderedDict()
    manifest_by_key: OrderedDict[str, dict[str, Any]] = OrderedDict()

    for batch_dir in batch_dirs:
        require_batch_files(batch_dir)
        require_quality_passed(batch_dir)
        expected_rows = read_jsonl(batch_dir / "expected-fetch-urls.jsonl")
        for row in expected_rows:
            url = str(row.get("url") or "")
            if not url:
                raise CombineError(f"{batch_dir}: expected-fetch row missing url")
            merged = dict(row)
            merged["fetch_required"] = True
            expected_by_url.setdefault(url, merged)
        merge_url_manifest(manifest_by_key, read_jsonl(batch_dir / "url-manifest.jsonl"), set(expected_by_url), batch_dir)
        merge_sections(sections_by_id, read_jsonl(batch_dir / "sections.jsonl"), batch_dir)
        merge_by_id(definitions_by_id, read_jsonl(batch_dir / "definitions.jsonl"), batch_dir, "definition")
        merge_nodes(nodes_by_id, read_jsonl(batch_dir / "nodes.jsonl"), batch_dir)
        merge_edges(edges_by_key, read_jsonl(batch_dir / "edges.jsonl"), batch_dir)
        merge_citations(citations_by_key, read_jsonl(batch_dir / "citation-url-map.jsonl"), batch_dir)

    expected_urls = set(expected_by_url)
    for row in manifest_by_key.values():
        if str(row.get("url") or "") in expected_urls:
            row["fetch_required"] = True

    sections = list(sections_by_id.values())
    definitions = list(definitions_by_id.values())
    nodes = list(nodes_by_id.values())
    edges = list(edges_by_key.values())
    citations = list(citations_by_key.values())
    url_manifest = sorted(manifest_by_key.values(), key=lambda row: int(row.get("row_number") or 0))
    expected_fetch_urls = list(expected_by_url.values())

    raw_count = copy_evidence(batch_dirs, output_dir, "raw")
    network_count = copy_evidence(batch_dirs, output_dir, "network")

    crawl_report = build_crawl_report(batch_dirs, sections, definitions, nodes, edges)
    crawl_report["source_batch_names"] = [batch_dir.name for batch_dir in batch_dirs]
    manifest = build_manifest(
        sections=sections,
        definitions=definitions,
        nodes=nodes,
        edges=edges,
        citations=citations,
        url_manifest=url_manifest,
        expected_fetch_urls=expected_fetch_urls,
        crawl_report=crawl_report,
        raw_count=raw_count,
        network_count=network_count,
    )

    write_jsonl(output_dir / "sections.jsonl", sections)
    write_jsonl(output_dir / "definitions.jsonl", definitions)
    write_jsonl(output_dir / "nodes.jsonl", nodes)
    write_jsonl(output_dir / "edges.jsonl", edges)
    write_jsonl(output_dir / "citation-url-map.jsonl", citations)
    write_jsonl(output_dir / "url-manifest.jsonl", url_manifest)
    write_jsonl(output_dir / "expected-fetch-urls.jsonl", expected_fetch_urls)
    write_json(output_dir / "crawl_report.json", crawl_report)
    write_json(output_dir / "manifest.json", manifest)

    return {
        "batch_root": str(batch_root),
        "output_dir": str(output_dir),
        "batch_count": len(batch_dirs),
        "counts": manifest["counts"],
        "crawl_report": {
            "pages_seen": crawl_report["pages_seen"],
            "pages_fetched": crawl_report["pages_fetched"],
            "pages_failed": crawl_report["pages_failed"],
            "section_count": crawl_report["section_count"],
            "definition_count": crawl_report["definition_count"],
            "node_count": crawl_report["node_count"],
            "edge_count": crawl_report["edge_count"],
            "fetcher": crawl_report["fetcher"],
        },
        "boundary": manifest["boundary"],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Combine Topeka codified-code batch outputs into one artifact-only source-output folder.")
    parser.add_argument("--batch-root", type=Path, required=True, help="Directory containing batch-* output folders.")
    parser.add_argument("--output-dir", type=Path, required=True, help="Empty destination directory for combined artifacts.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = combine_batches(args.batch_root, args.output_dir)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
