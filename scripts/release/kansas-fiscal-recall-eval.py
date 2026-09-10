#!/usr/bin/env python3
"""Evaluate Kansas fiscal-document recall, citations, and ledger provenance."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from topeka_pipeline_common import (
    DEFAULT_CELL,
    DEFAULT_KNOWLEDGE_BASE_ID,
    api_json,
    default_api_base,
    default_headers,
    write_json,
)


QUERY_SET: tuple[dict[str, Any], ...] = (
    {
        "id": "state-general-fund-budget",
        "query": "Kansas State General Fund budget appropriations by fiscal year",
        "must_include_any": ["state general fund", "appropriation", "fiscal year"],
    },
    {
        "id": "agency-budget-narrative",
        "query": "Kansas agency budget request recommendation and approved expenditure",
        "must_include_any": ["agency", "budget", "expenditure"],
    },
    {
        "id": "fiscal-note-impact",
        "query": "Kansas fiscal note estimated revenue expenditure and implementation impact",
        "must_include_any": ["fiscal note", "revenue", "expenditure"],
    },
    {
        "id": "acfr-fund-balance",
        "query": "Kansas annual comprehensive financial report governmental fund balance",
        "must_include_any": ["financial report", "fund balance", "governmental"],
    },
    {
        "id": "budget-comparison",
        "query": "Kansas budget comparison actual estimated and approved amounts",
        "must_include_any": ["actual", "estimated", "approved"],
    },
)


def _walk(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key, child
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def result_has_public_citation(item: dict[str, Any]) -> bool:
    return any(
        key in {"source_uri", "url", "citation_url"}
        and isinstance(value, str)
        and value.startswith(("http://", "https://"))
        for key, value in _walk(item)
    )


def result_has_ledger_provenance(item: dict[str, Any]) -> bool:
    present = {
        key
        for key, value in _walk(item)
        if key in {"source_identity", "logical_document_id", "source_revision_id"}
        and isinstance(value, str)
        and value.strip()
    }
    return {"source_revision_id"}.issubset(present) and bool(
        present & {"source_identity", "logical_document_id"}
    )


def score_result(query: dict[str, Any], page: dict[str, Any]) -> dict[str, Any]:
    rows = page.get("data") if isinstance(page.get("data"), list) else []
    top = [row for row in rows[:5] if isinstance(row, dict)]
    rendered = json.dumps(top, sort_keys=True).lower()
    terms = [str(term).lower() for term in query["must_include_any"]]
    matched_terms = [term for term in terms if term in rendered]
    has_citation = any(result_has_public_citation(row) for row in top)
    has_provenance = any(result_has_ledger_provenance(row) for row in top)
    return {
        "result_count": len(rows),
        "matched_terms": matched_terms,
        "has_public_citation": has_citation,
        "has_ledger_provenance": has_provenance,
        "passed": bool(rows and matched_terms and has_citation and has_provenance),
    }


def dry_run_eval() -> dict[str, Any]:
    return {
        "dry_run": True,
        "query_count": len(QUERY_SET),
        "requirements": [
            "at least one expected fiscal term in the top five results",
            "an official HTTP(S) citation in the top five results",
            "source revision and logical-document provenance in the top five results",
        ],
        "queries": list(QUERY_SET),
        "passed": True,
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
            {
                "query": query["query"],
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
        cases.append({**query, **score_result(query, page)})
    ordered = sorted(latencies)
    p95 = ordered[max(0, int(len(ordered) * 0.95) - 1)] if ordered else 0.0
    return {
        "dry_run": False,
        "vector_store_id": args.vector_store_id,
        "knowledge_base_id": args.knowledge_base_id,
        "query_count": len(cases),
        "passed": all(case["passed"] for case in cases),
        "p95_ms": round(p95, 3),
        "cases": cases,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cell", default=DEFAULT_CELL)
    parser.add_argument("--api")
    parser.add_argument("--vector-store-id", required=True)
    parser.add_argument("--knowledge-base-id", default=DEFAULT_KNOWLEDGE_BASE_ID)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-num-results", type=int, default=5)
    parser.add_argument("--api-timeout-seconds", type=int, default=60)
    parser.add_argument(
        "--api-transport",
        default="auto",
        choices=["auto", "host-curl", "api-container", "docker-network"],
    )
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
