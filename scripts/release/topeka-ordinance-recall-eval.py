#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

from topeka_pipeline_common import DEFAULT_CELL, DEFAULT_VECTOR_STORE_ID, api_json, default_api_base, default_headers, write_json


QUERY_SET: list[dict[str, Any]] = [
    {
        "id": "ordinance-20679-sto",
        "query": "Which Topeka ordinance adopted the 2025 2026 Standard Traffic Ordinance and amended sections 10.15.010 and 10.15.020?",
        "expected_source_collection": "topeka-ordinances",
        "expected_source_uri_contains": "Ordinance20679.pdf",
        "must_include_all": ["20679", "standard traffic", "10.15.010", "10.15.020"],
    },
    {
        "id": "charter-126-hotel-topeka-tax",
        "query": "Which Topeka charter ordinance changed the transient guest tax for Hotel Topeka and what rate applied January 1 2027?",
        "expected_source_collection": "topeka-ordinances",
        "expected_source_uri_contains": "CharterOrdinance126.pdf",
        "must_include_all": ["126", "hotel topeka", "8.5"],
    },
    {
        "id": "ordinance-20340-downtown-design",
        "query": "Which ordinance concerned downtown zoning and design standards and amended Topeka Municipal Code 18.200.010?",
        "expected_source_collection": "topeka-ordinances",
        "expected_source_uri_contains": "Ordinance20340.pdf",
        "must_include_all": ["20340", "downtown", "18.200.010"],
    },
    {
        "id": "ordinance-20408-building-code",
        "query": "Which ordinance adopted the 2021 International Building Code and amended Topeka Municipal Code 14.20.010?",
        "expected_source_collection": "topeka-ordinances",
        "expected_source_uri_contains": "Ordinance20408.pdf",
        "must_include_all": ["20408", "international building code", "14.20.010"],
    },
    {
        "id": "ordinance-20407-fire-code",
        "query": "Which ordinance adopted the 2021 International Fire Code and amended Topeka Municipal Code 14.40.010?",
        "expected_source_collection": "topeka-ordinances",
        "expected_source_uri_contains": "Ordinance20407.pdf",
        "must_include_all": ["20407", "international fire code", "14.40.010"],
    },
]


def public_citation_values(item: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for value in (item.get("source_uri"), item.get("url")):
        if isinstance(value, str):
            values.append(value)
    attrs = item.get("attributes")
    if isinstance(attrs, dict):
        for value in (attrs.get("citation_url"), attrs.get("pdf_url"), attrs.get("source_url")):
            if isinstance(value, str):
                values.append(value)
    citation = item.get("citation")
    if isinstance(citation, dict):
        for value in (citation.get("url"), citation.get("source_uri")):
            if isinstance(value, str):
                values.append(value)
    for content in item.get("content") or []:
        if not isinstance(content, dict):
            continue
        for annotation in content.get("annotations") or []:
            if isinstance(annotation, dict):
                for value in (annotation.get("url"), annotation.get("source_uri")):
                    if isinstance(value, str):
                        values.append(value)
    return [value for value in values if value.startswith(("http://", "https://"))]


def searchable_text(item: dict[str, Any]) -> str:
    parts = [str(item.get("filename") or ""), str(item.get("source_uri") or "")]
    attrs = item.get("attributes")
    if isinstance(attrs, dict):
        parts.extend(str(value or "") for value in attrs.values())
    for content in item.get("content") or []:
        if isinstance(content, dict):
            parts.append(str(content.get("text") or ""))
    return re.sub(r"\s+", " ", " ".join(parts)).lower()


def result_matches_case(case: dict[str, Any], item: dict[str, Any]) -> tuple[bool, list[str]]:
    attrs = item.get("attributes") if isinstance(item.get("attributes"), dict) else {}
    text = searchable_text(item)
    missing_terms = [term for term in case.get("must_include_all", []) if str(term).lower() not in text]
    expected_source_collection = case.get("expected_source_collection")
    if expected_source_collection and attrs.get("source_collection") != expected_source_collection:
        return False, missing_terms
    expected_source_uri_contains = str(case.get("expected_source_uri_contains") or "")
    source_values = [str(item.get("source_uri") or ""), str(attrs.get("pdf_url") or ""), str(attrs.get("citation_url") or "")]
    if expected_source_uri_contains and not any(expected_source_uri_contains in value for value in source_values):
        return False, missing_terms
    return not missing_terms and bool(public_citation_values(item)), missing_terms


def score_case(case: dict[str, Any], page: dict[str, Any]) -> dict[str, Any]:
    rows = page.get("data") if isinstance(page.get("data"), list) else []
    inspected_rows = rows[:5]
    matches = []
    missing_by_row = []
    for index, row in enumerate(inspected_rows, start=1):
        if not isinstance(row, dict):
            continue
        passed, missing_terms = result_matches_case(case, row)
        missing_by_row.append({"rank": index, "missing_terms": missing_terms})
        if passed:
            attrs = row.get("attributes") if isinstance(row.get("attributes"), dict) else {}
            matches.append(
                {
                    "rank": index,
                    "file_id": row.get("file_id"),
                    "filename": row.get("filename"),
                    "source_uri": row.get("source_uri") or attrs.get("pdf_url") or attrs.get("citation_url"),
                    "source_collection": attrs.get("source_collection"),
                    "ordinance_number": attrs.get("ordinance_number"),
                }
            )
    return {
        "result_count": len(rows),
        "top_file_id": rows[0].get("file_id") if rows and isinstance(rows[0], dict) else None,
        "top_filename": rows[0].get("filename") if rows and isinstance(rows[0], dict) else None,
        "matches": matches,
        "missing_terms_by_row": missing_by_row,
        "passed": bool(matches),
    }


def dry_run_eval() -> dict[str, Any]:
    return {
        "dry_run": True,
        "query_count": len(QUERY_SET),
        "queries": QUERY_SET,
        "passed": len(QUERY_SET) == 5,
    }


def live_eval(args: argparse.Namespace) -> dict[str, Any]:
    headers = default_headers(cell=args.cell, auth_token_file=args.auth_token_file)
    api_base = args.api or default_api_base(args.cell)
    cases: list[dict[str, Any]] = []
    latencies: list[float] = []
    for case in QUERY_SET:
        started = time.perf_counter()
        page = api_json(
            "POST",
            api_base,
            f"/v1/vector_stores/{args.vector_store_id}/search",
            {
                "query": case["query"],
                "max_num_results": args.max_num_results,
                "include_metadata": True,
                "include_content": True,
            },
            headers=headers,
            timeout=args.api_timeout_seconds,
            cell=args.cell,
            transport=args.api_transport,
        )
        latencies.append((time.perf_counter() - started) * 1000)
        cases.append({**case, **score_case(case, page)})
    latencies_sorted = sorted(latencies)
    p95 = latencies_sorted[max(0, int(len(latencies_sorted) * 0.95) - 1)] if latencies_sorted else 0
    return {
        "dry_run": False,
        "vector_store_id": args.vector_store_id,
        "query_count": len(QUERY_SET),
        "passed": all(case["passed"] for case in cases),
        "p95_ms": round(p95, 3),
        "cases": cases,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate official Topeka ordinance PDF recall through ExAIS search.")
    parser.add_argument("--cell", default=DEFAULT_CELL)
    parser.add_argument("--api", default=None)
    parser.add_argument("--vector-store-id", default=DEFAULT_VECTOR_STORE_ID)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-num-results", type=int, default=8)
    parser.add_argument("--api-timeout-seconds", type=int, default=90)
    parser.add_argument("--api-transport", default="auto", choices=["auto", "host-curl", "api-container", "docker-network"])
    parser.add_argument("--auth-token-file", type=Path)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    proof = dry_run_eval() if args.dry_run else live_eval(args)
    if args.output:
        write_json(args.output, proof)
    print(json.dumps(proof, indent=2, sort_keys=True))
    if not proof["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
