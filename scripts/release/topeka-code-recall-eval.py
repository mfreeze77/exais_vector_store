#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from topeka_pipeline_common import DEFAULT_CELL, DEFAULT_VECTOR_STORE_ID, api_json, default_api_base, default_headers, write_json


QUERY_SET: list[dict[str, Any]] = [
    {
        "id": "current-zoning-definition",
        "category": "current_code",
        "query": "What does the Topeka Municipal Code define as a structure in zoning?",
        "must_include_any": ["structure", "zoning", "definition"],
    },
    {
        "id": "current-parking-requirements",
        "category": "current_code",
        "query": "Find the current Topeka parking requirements for residential or commercial uses.",
        "must_include_any": ["parking", "off-street", "spaces"],
    },
    {
        "id": "current-fence-or-yard-rule",
        "category": "current_code",
        "query": "What current Topeka code section controls fences, yards, or setbacks?",
        "must_include_any": ["fence", "yard", "setback"],
    },
    {
        "id": "current-business-license",
        "category": "current_code",
        "query": "Find the current Topeka Municipal Code rules for business licenses.",
        "must_include_any": ["license", "business", "permit"],
    },
    {
        "id": "current-nuisance-enforcement",
        "category": "current_code",
        "query": "What current Topeka code provisions discuss nuisances and enforcement?",
        "must_include_any": ["nuisance", "enforcement", "violation"],
    },
    {
        "id": "history-section-ordinance",
        "category": "amendment_history",
        "query": "Which ordinance history is listed for the Topeka code section about zoning definitions?",
        "must_include_any": ["ordinance", "history", "passed"],
    },
    {
        "id": "history-amended-section",
        "category": "amendment_history",
        "query": "Find Topeka ordinances that amended a municipal code section.",
        "must_include_any": ["amended", "ordinance", "section"],
    },
    {
        "id": "history-repealed-section",
        "category": "amendment_history",
        "query": "Find Topeka ordinances or code history entries involving repealed sections.",
        "must_include_any": ["repeal", "ordinance", "section"],
    },
    {
        "id": "history-adopted-code",
        "category": "amendment_history",
        "query": "Find ordinance provenance for adoption of Topeka municipal code provisions.",
        "must_include_any": ["adopt", "ordinance", "code"],
    },
    {
        "id": "history-passed-date",
        "category": "amendment_history",
        "query": "Which Topeka code results include an ordinance passed date or legislative history?",
        "must_include_any": ["passed", "date", "ordinance"],
    },
]


def result_has_public_citation(item: dict[str, Any]) -> bool:
    candidates = [item.get("source_uri"), item.get("url")]
    citation = item.get("citation")
    if isinstance(citation, dict):
        candidates.extend([citation.get("url"), citation.get("source_uri")])
    annotations = item.get("annotations") or []
    for annotation in annotations:
        if isinstance(annotation, dict):
            candidates.extend([annotation.get("url"), annotation.get("source_uri")])
    return any(isinstance(value, str) and value.startswith(("http://", "https://")) for value in candidates)


def score_result_text(query: dict[str, Any], page: dict[str, Any]) -> dict[str, Any]:
    rows = page.get("data") if isinstance(page.get("data"), list) else []
    joined = json.dumps(rows[:3], sort_keys=True).lower()
    terms = [str(term).lower() for term in query.get("must_include_any", [])]
    matched_terms = [term for term in terms if term in joined]
    return {
        "result_count": len(rows),
        "top_file_id": rows[0].get("file_id") if rows and isinstance(rows[0], dict) else None,
        "matched_terms": matched_terms,
        "has_public_citation": any(isinstance(row, dict) and result_has_public_citation(row) for row in rows[:3]),
        "passed": bool(rows and matched_terms and any(isinstance(row, dict) and result_has_public_citation(row) for row in rows[:3])),
    }


def dry_run_eval() -> dict[str, Any]:
    categories = {category: sum(1 for query in QUERY_SET if query["category"] == category) for category in {"current_code", "amendment_history"}}
    return {
        "dry_run": True,
        "query_count": len(QUERY_SET),
        "categories": categories,
        "queries": QUERY_SET,
        "passed": categories == {"current_code": 5, "amendment_history": 5},
    }


def live_eval(args: argparse.Namespace) -> dict[str, Any]:
    headers = default_headers(cell=args.cell, auth_token_file=args.auth_token_file)
    api_base = args.api or default_api_base(args.cell)
    cases: list[dict[str, Any]] = []
    latencies: list[float] = []
    for query in QUERY_SET:
        started = time.perf_counter()
        page = api_json(
            "POST",
            api_base,
            f"/v1/vector_stores/{args.vector_store_id}/search",
            {"query": query["query"], "max_num_results": args.max_num_results, "include_metadata": True, "include_content": args.include_content},
            headers=headers,
            timeout=args.api_timeout_seconds,
            cell=args.cell,
            transport=args.api_transport,
        )
        latencies.append((time.perf_counter() - started) * 1000)
        cases.append({**query, **score_result_text(query, page)})
    category_totals: dict[str, dict[str, int]] = {}
    for case in cases:
        bucket = category_totals.setdefault(case["category"], {"passed": 0, "total": 0})
        bucket["total"] += 1
        bucket["passed"] += 1 if case["passed"] else 0
    latencies_sorted = sorted(latencies)
    p95 = latencies_sorted[max(0, int(len(latencies_sorted) * 0.95) - 1)] if latencies_sorted else 0
    return {
        "dry_run": False,
        "vector_store_id": args.vector_store_id,
        "query_count": len(QUERY_SET),
        "category_totals": category_totals,
        "passed": all(case["passed"] for case in cases),
        "p95_ms": round(p95, 3),
        "cases": cases,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate Topeka current-code and amendment-history recall through ExAIS search.")
    parser.add_argument("--cell", default=DEFAULT_CELL)
    parser.add_argument("--api", default=None)
    parser.add_argument("--vector-store-id", default=DEFAULT_VECTOR_STORE_ID)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-num-results", type=int, default=5)
    parser.add_argument("--include-content", action="store_true")
    parser.add_argument("--api-timeout-seconds", type=int, default=60)
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
