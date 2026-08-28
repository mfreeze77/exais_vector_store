#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

from topeka_pipeline_common import CODIFIED_SEED, read_jsonl, write_json, write_jsonl


BASE_URL = "https://topeka.municipal.codes"
DEFAULT_URL_LIST = CODIFIED_SEED / "raw" / "topeka_municipal_code_urls.csv"
DEFAULT_FETCH_LEVELS = {"section", "subsection"}


def canonicalize_tmc_url(value: str) -> str:
    absolute = urljoin(BASE_URL, value)
    parts = urlsplit(absolute)
    path = parts.path.rstrip("/") or "/"
    if parts.scheme not in {"http", "https"} or parts.netloc.lower() != "topeka.municipal.codes":
        return ""
    if path != "/TMC" and not path.startswith("/TMC/"):
        return ""
    return urlunsplit(("https", "topeka.municipal.codes", path, "", ""))


def expected_urls(source_output: Path, url_list: Path, fetch_levels: set[str]) -> list[dict[str, Any]]:
    expected_path = source_output / "expected-fetch-urls.jsonl"
    if expected_path.exists():
        return read_jsonl(expected_path)
    rows: list[dict[str, Any]] = []
    with url_list.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row_number, row in enumerate(reader, start=2):
            level = str(row.get("level") or "").strip()
            if level.lower() not in fetch_levels:
                continue
            url = canonicalize_tmc_url(str(row.get("url") or ""))
            rows.append({
                "level": level,
                "id": str(row.get("id") or "").strip(),
                "citation": str(row.get("citation") or "").strip(),
                "name": str(row.get("name") or "").strip(),
                "url": url,
                "row_number": row_number,
            })
    return rows


def file_state(source_output: Path) -> dict[str, dict[str, Any]]:
    names = [
        "sections.jsonl",
        "definitions.jsonl",
        "nodes.jsonl",
        "edges.jsonl",
        "citation-url-map.jsonl",
        "manifest.json",
        "crawl_report.json",
        "url-manifest.jsonl",
        "expected-fetch-urls.jsonl",
    ]
    state: dict[str, dict[str, Any]] = {}
    for name in names:
        path = source_output / name
        state[name] = {
            "present": path.exists(),
            "bytes": path.stat().st_size if path.exists() else 0,
            "nonempty": path.exists() and path.stat().st_size > 0,
        }
    return state


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def duplicate_values(values: list[str]) -> list[str]:
    counts = Counter(value for value in values if value)
    return sorted(value for value, count in counts.items() if count > 1)


def build_artifact_diagnostics(source_output: Path, url_list: Path, fetch_levels: set[str]) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    expected = expected_urls(source_output, url_list, fetch_levels)
    sections = read_jsonl(source_output / "sections.jsonl") if (source_output / "sections.jsonl").exists() else []
    citations = read_jsonl(source_output / "citation-url-map.jsonl") if (source_output / "citation-url-map.jsonl").exists() else []
    nodes = read_jsonl(source_output / "nodes.jsonl") if (source_output / "nodes.jsonl").exists() else []
    edges = read_jsonl(source_output / "edges.jsonl") if (source_output / "edges.jsonl").exists() else []
    crawl_report = load_json(source_output / "crawl_report.json")
    manifest = load_json(source_output / "manifest.json")

    expected_by_url = {canonicalize_tmc_url(str(row.get("url") or "")): row for row in expected}
    section_urls = [canonicalize_tmc_url(str(row.get("source_url") or "")) for row in sections]
    section_ids = [str(row.get("id") or "") for row in sections]
    section_url_set = {url for url in section_urls if url}
    sections_by_url = {canonicalize_tmc_url(str(row.get("source_url") or "")): row for row in sections}
    citation_rows_by_id = {str(row.get("id") or ""): row for row in citations if row.get("record_type") == "section"}
    edge_type_counts = Counter(str(row.get("type") or "") for row in edges)

    missing_urls = sorted(url for url in expected_by_url if url and url not in section_url_set)
    unexpected_urls = sorted(url for url in section_url_set if url and url not in expected_by_url)
    missing_text = [str(row.get("id") or row.get("source_url") or "") for row in sections if not str(row.get("text") or "").strip()]
    missing_citation = [
        str(row.get("id") or row.get("source_url") or "")
        for row in sections
        if not citation_rows_by_id.get(str(row.get("id") or "")) or not str(citation_rows_by_id[str(row.get("id") or "")].get("citation_url") or "").strip()
    ]
    missing_source_url = [str(row.get("id") or "") for row in sections if not canonicalize_tmc_url(str(row.get("source_url") or ""))]

    required_files = file_state(source_output)
    required_file_failures = [
        name
        for name, state in required_files.items()
        if name not in {"definitions.jsonl"} and not state["nonempty"]
    ]
    section_coverage = {
        "expected": len(expected_by_url),
        "fetched": len(section_url_set),
        "missing": len(missing_urls),
        "unexpected": len(unexpected_urls),
        "coverage_pct": round((len(section_url_set & set(expected_by_url)) / len(expected_by_url) * 100.0), 3) if expected_by_url else 0.0,
        "sample_missing_urls": missing_urls[:25],
        "sample_unexpected_urls": unexpected_urls[:25],
        "duplicate_section_ids": duplicate_values(section_ids)[:25],
        "duplicate_section_urls": duplicate_values(section_urls)[:25],
    }
    citation_quality = {
        "section_citation_rows": len(citation_rows_by_id),
        "missing_section_citation_rows": len(missing_citation),
        "missing_source_urls": len(missing_source_url),
        "sample_missing_citation_ids": missing_citation[:25],
        "sample_missing_source_url_ids": missing_source_url[:25],
    }
    graph_quality = {
        "nodes": len(nodes),
        "edges": len(edges),
        "edge_types": dict(sorted(edge_type_counts.items())),
        "has_contains_edges": edge_type_counts.get("CONTAINS", 0) > 0,
        "has_history_edges": edge_type_counts.get("HAS_ORDINANCE_HISTORY", 0) > 0,
    }

    failures: list[str] = []
    if required_file_failures:
        failures.append("missing_or_empty_required_artifact_files")
    if section_coverage["missing"]:
        failures.append("missing_required_section_urls")
    if section_coverage["unexpected"]:
        failures.append("unexpected_section_urls")
    if section_coverage["duplicate_section_ids"] or section_coverage["duplicate_section_urls"]:
        failures.append("duplicate_section_identity")
    if missing_text:
        failures.append("sections_missing_text")
    if missing_citation or missing_source_url:
        failures.append("section_citation_quality_failed")
    if not graph_quality["has_contains_edges"]:
        failures.append("missing_contains_graph_edges")
    if crawl_report.get("pages_failed"):
        failures.append("crawl_report_has_failures")
    if manifest.get("status") != "success":
        failures.append("manifest_status_not_success")

    worklists = build_worklists(
        expected_by_url=expected_by_url,
        sections_by_url=sections_by_url,
        missing_urls=missing_urls,
        unexpected_urls=unexpected_urls,
        missing_text=missing_text,
        missing_citation=missing_citation,
        missing_source_url=missing_source_url,
        crawl_failures=crawl_report.get("failures") or [],
    )
    passed = not failures
    report = {
        "schema_version": 1,
        "source_output": str(source_output),
        "url_list": str(url_list),
        "fetch_levels": sorted(fetch_levels),
        "passed": passed,
        "vectorization_allowed": passed,
        "failure_reasons": failures,
        "artifact_files": required_files,
        "crawl_report": {
            "status": manifest.get("status"),
            "pages_seen": crawl_report.get("pages_seen"),
            "pages_fetched": crawl_report.get("pages_fetched"),
            "pages_failed": crawl_report.get("pages_failed"),
            "section_count": crawl_report.get("section_count"),
            "failures_sample": (crawl_report.get("failures") or [])[:25],
        },
        "section_coverage": section_coverage,
        "citation_quality": citation_quality,
        "text_quality": {
            "empty_text_sections": len(missing_text),
            "sample_empty_text_ids": missing_text[:25],
        },
        "graph_quality": graph_quality,
        "worklists": {name: len(rows) for name, rows in worklists.items()},
        "boundary": "Artifact-only quality gate. This script does not call ExAIS API ingestion, model gateways, embedding providers, Qdrant, or vector-store write paths.",
    }
    return report, worklists


def build_quality_report(source_output: Path, url_list: Path, fetch_levels: set[str]) -> dict[str, Any]:
    return build_artifact_diagnostics(source_output, url_list, fetch_levels)[0]


def build_worklists(
    *,
    expected_by_url: dict[str, dict[str, Any]],
    sections_by_url: dict[str, dict[str, Any]],
    missing_urls: list[str],
    unexpected_urls: list[str],
    missing_text: list[str],
    missing_citation: list[str],
    missing_source_url: list[str],
    crawl_failures: list[Any],
) -> dict[str, list[dict[str, Any]]]:
    return {
        "missing-required-urls.jsonl": [
            dict(expected_by_url[url], reason="missing_required_section_url")
            for url in missing_urls
            if url in expected_by_url
        ],
        "failed-crawl-urls.jsonl": [
            {
                "reason": "crawl_failure",
                "url": canonicalize_tmc_url(str(row.get("url") or "")) if isinstance(row, dict) else "",
                "error": str(row.get("error") or "") if isinstance(row, dict) else str(row),
            }
            for row in crawl_failures
        ],
        "unexpected-section-urls.jsonl": [
            {
                "reason": "unexpected_section_url",
                "url": url,
                "id": str(sections_by_url.get(url, {}).get("id") or ""),
                "citation": str(sections_by_url.get(url, {}).get("citation") or ""),
                "title": str(sections_by_url.get(url, {}).get("title") or ""),
            }
            for url in unexpected_urls
        ],
        "section-quality-issues.jsonl": section_quality_issue_rows(
            missing_text=missing_text,
            missing_citation=missing_citation,
            missing_source_url=missing_source_url,
        ),
    }


def section_quality_issue_rows(
    *,
    missing_text: list[str],
    missing_citation: list[str],
    missing_source_url: list[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rows.extend({"reason": "section_missing_text", "id": item} for item in missing_text)
    rows.extend({"reason": "section_missing_citation_url", "id": item} for item in missing_citation)
    rows.extend({"reason": "section_missing_source_url", "id": item} for item in missing_source_url)
    return rows


def write_worklists(output_dir: Path, worklists: dict[str, list[dict[str, Any]]]) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    for filename, rows in worklists.items():
        path = output_dir / filename
        write_jsonl(path, rows)
        files[filename.removesuffix(".jsonl").replace("-", "_")] = str(path)
    return files


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Topeka codified-code JSON artifacts before vectorization.")
    parser.add_argument("--source-output", type=Path, required=True)
    parser.add_argument("--url-list", type=Path, default=DEFAULT_URL_LIST)
    parser.add_argument("--fetch-levels", default="Section,Subsection")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--worklist-dir", type=Path, help="Optional directory for complete missing/failure/quality worklists.")
    parser.add_argument("--allow-fail", action="store_true", help="Write/print the report but return 0 when the quality gate fails.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    fetch_levels = {item.strip().lower() for item in args.fetch_levels.split(",") if item.strip()}
    report, worklists = build_artifact_diagnostics(args.source_output, args.url_list, fetch_levels or DEFAULT_FETCH_LEVELS)
    if args.worklist_dir:
        report["worklist_files"] = write_worklists(args.worklist_dir, worklists)
    if args.output:
        write_json(args.output, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    if not report["passed"] and not args.allow_fail:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
