#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any
from urllib import request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "svs_common"))


class _Rows:
    def mappings(self):
        return self

    def first(self):
        return None

    def all(self):
        return []


class _FixtureDb:
    def __init__(self):
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params or {}))
        return _Rows()


def parse_profiles(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def fixture_queries(profiles: list[str]) -> list[dict[str, Any]]:
    first = profiles[0]
    second = profiles[1] if len(profiles) > 1 else profiles[0]
    return [
        {
            "id": "fixture_policy_rotation",
            "query": "How do I rotate project API keys?",
            "expected_chunk_ids": ["chk_policy_rotation"],
            "live_results_by_model_profile_id": {
                first: ["chk_policy_rotation", "chk_policy_overview"],
                second: ["chk_policy_overview", "chk_policy_rotation"],
            },
            "latency_ms_by_model_profile_id": {
                first: 8,
                second: 21,
            },
        },
        {
            "id": "fixture_backup_restore",
            "query": "Where is the restore preflight documented?",
            "expected_document_ids": ["doc_restore_runbook"],
            "live_results_by_model_profile_id": {
                first: [{"chunk_id": "chk_restore_steps", "document_id": "doc_restore_runbook"}],
                second: [{"chunk_id": "chk_restore_notes", "document_id": "doc_restore_runbook"}],
            },
            "latency_ms_by_model_profile_id": {
                first: 9,
                second: 24,
            },
        },
    ]


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    profiles = parse_profiles(args.profiles)
    payload = {
        "name": args.name,
        "mode": args.mode,
        "execution_mode": "live",
        "model_profile_ids": profiles,
        "queries": fixture_queries(profiles),
        "top_k": args.top_k,
        "golden_set_id": args.golden_set_id,
        "vector_store_id": args.vector_store_id,
        "knowledge_base_id": args.knowledge_base_id,
        "retrieval_profile_id": args.retrieval_profile_id,
        "metrics": [
            "recall_at_k",
            "precision_at_k",
            "mrr",
            "ndcg_at_k",
            "latency_ms_p95",
            "estimated_cost_usd",
        ],
        "selection_policy": {
            "min_score": args.min_score,
            "max_latency_ms": args.max_latency_ms,
            "max_estimated_cost_usd": args.max_estimated_cost_usd,
        },
    }
    return {k: v for k, v in payload.items() if v is not None}


def api_headers(args: argparse.Namespace) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if args.api_token:
        headers["Authorization"] = f"Bearer {args.api_token}"
    else:
        headers["X-SVS-Tenant-Id"] = args.tenant_id
        headers["X-SVS-Business-Instance-Id"] = args.business_instance_id
        headers["X-SVS-User-Id"] = args.user_id
    return headers


def redacted_header_summary(headers: dict[str, str]) -> dict[str, str]:
    redacted = dict(headers)
    if "Authorization" in redacted:
        redacted["Authorization"] = "Bearer <redacted>"
    return redacted


def post_api_bakeoff(args: argparse.Namespace, payload: dict[str, Any]) -> dict[str, Any]:
    url = args.api_base.rstrip("/") + "/api/v1/bakeoffs"
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=body, headers=api_headers(args), method="POST")
    with request.urlopen(req, timeout=args.timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def run_local_fixture(payload: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    from svs_common.bakeoff import BakeoffService
    from svs_common.schemas import BakeoffRunRequest, Principal

    service = BakeoffService()
    principal = Principal(
        tenant_id=args.tenant_id,
        business_instance_id=args.business_instance_id,
        user_id=args.user_id,
        scopes=["evals:write", "evals:read"],
    )
    result = service.create_run(_FixtureDb(), principal, BakeoffRunRequest.model_validate(payload))
    return result.model_dump(mode="python")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a deterministic or API-backed live bakeoff fan-out.")
    parser.add_argument("--name", default="live-bakeoff-fixture")
    parser.add_argument("--mode", default="markdown_docs_v1")
    parser.add_argument("--profiles", default="hash_mock_1536,openai_text_embedding_3_small_1536")
    parser.add_argument("--top-k", type=int, default=2)
    parser.add_argument("--golden-set-id")
    parser.add_argument("--vector-store-id")
    parser.add_argument("--knowledge-base-id")
    parser.add_argument("--retrieval-profile-id")
    parser.add_argument("--min-score", type=float, default=0.0)
    parser.add_argument("--max-latency-ms", type=float)
    parser.add_argument("--max-estimated-cost-usd", type=float)
    parser.add_argument("--api-base", help="When set, POST the bakeoff request to this API base URL.")
    parser.add_argument("--api-token", help="Bearer token for live API usage. The token is never printed.")
    parser.add_argument("--tenant-id", default="tenant_fixture")
    parser.add_argument("--business-instance-id", default="biz_fixture")
    parser.add_argument("--user-id", default="user_fixture")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument(
        "--print-request",
        action="store_true",
        help="Print the request body with no secrets. Useful for operator review before using --api-base.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    payload = build_payload(args)
    if args.print_request:
        print(json.dumps({"request": payload}, indent=2, sort_keys=True))
        return 0
    if args.api_base:
        result = post_api_bakeoff(args, payload)
        output = {
            "mode": "api",
            "api_base": args.api_base.rstrip("/"),
            "headers": redacted_header_summary(api_headers(args)),
            "result": result,
        }
    else:
        output = {
            "mode": "fixture",
            "result": run_local_fixture(payload, args),
        }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
