#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
import statistics
import sys
import time
from typing import Any, Callable
from urllib import error, request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_common import DEFAULT_CELL, api_base  # noqa: E402


DEFAULT_GOLDEN_SET = ROOT / "evals" / "expertaiservices-tickets" / "golden.json"
RequestJson = Callable[[str, str, dict[str, Any] | None], tuple[dict[str, Any], float]]


class QualityEvalError(RuntimeError):
    pass


class ApiRequestError(QualityEvalError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def load_golden_set(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    validate_golden_set(data)
    return data


def validate_golden_set(data: dict[str, Any]) -> None:
    if data.get("schema_version") != 1:
        raise QualityEvalError("golden set schema_version must be 1")
    if not isinstance(data.get("id"), str) or not data["id"].strip():
        raise QualityEvalError("golden set id is required")
    cases = data.get("cases")
    candidates = data.get("candidates")
    if not isinstance(cases, list) or not cases:
        raise QualityEvalError("golden set cases must be a non-empty list")
    if not isinstance(candidates, list) or not candidates:
        raise QualityEvalError("golden set candidates must be a non-empty list")
    _require_unique_ids(cases, "case")
    _require_unique_ids(candidates, "candidate")
    for case in cases:
        if not isinstance(case.get("query"), str) or not case["query"].strip():
            raise QualityEvalError(f"case {case.get('id')} requires a query")
        expected = case.get("expected_filenames")
        if not isinstance(expected, list) or not expected or not all(isinstance(item, str) and item for item in expected):
            raise QualityEvalError(f"case {case.get('id')} requires expected_filenames")
        support_terms = case.get("support_terms", [])
        if not isinstance(support_terms, list) or not all(isinstance(item, str) and item for item in support_terms):
            raise QualityEvalError(f"case {case.get('id')} support_terms must be strings")
    candidate_ids = {candidate["id"] for candidate in candidates}
    if data.get("required_candidate_id") not in candidate_ids:
        raise QualityEvalError("required_candidate_id must name a configured candidate")
    promotion_delta = data.get("promotion_min_score_delta", 0.0)
    if not isinstance(promotion_delta, (int, float)) or float(promotion_delta) < 0:
        raise QualityEvalError("promotion_min_score_delta must be non-negative")
    metric_k = int(data.get("metric_k") or 0)
    request_top_k = int(data.get("request_top_k") or 0)
    if metric_k < 1 or request_top_k < metric_k or request_top_k > 50:
        raise QualityEvalError("request_top_k must be between metric_k and 50")
    if not isinstance(data.get("thresholds"), dict) or not data["thresholds"]:
        raise QualityEvalError("golden set thresholds are required")


def _require_unique_ids(items: list[dict[str, Any]], label: str) -> None:
    ids = [item.get("id") for item in items]
    if any(not isinstance(item, str) or not item for item in ids):
        raise QualityEvalError(f"every {label} requires an id")
    if len(ids) != len(set(ids)):
        raise QualityEvalError(f"{label} ids must be unique")


def normalize_evidence(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def evidence_contains(normalized_evidence: str, term: str) -> bool:
    normalized_term = normalize_evidence(term)
    if not normalized_term:
        return False
    return f" {normalized_term} " in f" {normalized_evidence} "


def score_query(
    case: dict[str, Any],
    response: dict[str, Any],
    *,
    metric_k: int,
    request_top_k: int,
    latency_ms: float,
) -> dict[str, Any]:
    items = response.get("data")
    data = items if isinstance(items, list) else []
    ranked_data = data[:request_top_k]
    unique_filenames: list[str] = []
    top_files: list[dict[str, Any]] = []
    for result_rank, item in enumerate(ranked_data, start=1):
        if not isinstance(item, dict):
            continue
        filename = item.get("filename")
        if not isinstance(filename, str) or not filename:
            continue
        if filename not in unique_filenames:
            unique_filenames.append(filename)
            citation = item.get("citation") if isinstance(item.get("citation"), dict) else {}
            top_files.append({
                "document_rank": len(unique_filenames),
                "result_rank": result_rank,
                "chunk_id": citation.get("chunk_id"),
                "filename": filename,
                "file_id": item.get("file_id"),
                "score": item.get("score"),
            })

    expected = set(case["expected_filenames"])
    matched_at_k = expected.intersection(unique_filenames[:metric_k])
    relevant_at_k = sum(1 for filename in unique_filenames[:metric_k] if filename in expected)
    first_rank = next(
        (rank for rank, filename in enumerate(unique_filenames, start=1) if filename in expected),
        None,
    )
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, filename in enumerate(unique_filenames[:metric_k], start=1)
        if filename in expected
    )
    ideal_count = min(len(expected), metric_k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))

    evidence_parts: list[str] = []
    for item in ranked_data:
        if not isinstance(item, dict) or item.get("filename") not in expected:
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                evidence_parts.append(content["text"])
    normalized_evidence_parts = [normalize_evidence(part) for part in evidence_parts]
    missing_support_terms = [
        term
        for term in case.get("support_terms", [])
        if not any(evidence_contains(part, term) for part in normalized_evidence_parts)
    ]
    citation_complete = bool(ranked_data) and all(_citation_complete(item) for item in ranked_data)
    result_count = len(ranked_data)
    unique_count = len({
        item.get("filename")
        for item in ranked_data
        if isinstance(item, dict) and isinstance(item.get("filename"), str) and item.get("filename")
    })
    duplicate_rate = 1.0 - (unique_count / result_count) if result_count else 0.0

    return {
        "id": case["id"],
        "query": case["query"],
        "expected_filenames": list(case["expected_filenames"]),
        "ranking_unit": "unique_filename_first_occurrence",
        "first_relevant_rank": first_rank,
        "hit_at_k": bool(matched_at_k),
        "top1_hit": first_rank == 1,
        "recall_at_k": round(len(matched_at_k) / len(expected), 6),
        "precision_at_k": round(relevant_at_k / metric_k, 6),
        "reciprocal_rank": round((1.0 / first_rank) if first_rank else 0.0, 6),
        "ndcg_at_k": round((dcg / idcg) if idcg else 0.0, 6),
        "support_complete": not missing_support_terms and bool(evidence_parts),
        "missing_support_terms": missing_support_terms,
        "citation_complete": citation_complete,
        "result_count": result_count,
        "unique_file_count": unique_count,
        "duplicate_rate": round(duplicate_rate, 6),
        "latency_ms": round(latency_ms, 3),
        "search_query": response.get("search_query"),
        "top_files": top_files[:metric_k],
        "error": None,
    }


def _citation_complete(item: Any) -> bool:
    if not isinstance(item, dict) or not item.get("file_id") or not item.get("filename"):
        return False
    file_id = item["file_id"]
    filename = item["filename"]
    content = item.get("content")
    if not isinstance(content, list) or not any(
        isinstance(part, dict)
        and isinstance(part.get("text"), str)
        and part["text"]
        and any(_annotation_matches(annotation, file_id, filename) for annotation in part.get("annotations") or [])
        for part in content
    ):
        return False
    if not any(_annotation_matches(annotation, file_id, filename) for annotation in item.get("annotations") or []):
        return False
    citation = item.get("citation")
    if not isinstance(citation, dict):
        return False
    start_index = citation.get("start_index")
    end_index = citation.get("end_index")
    return (
        citation.get("file_id") == file_id
        and citation.get("filename") == filename
        and isinstance(citation.get("chunk_id"), str)
        and bool(citation["chunk_id"])
        and isinstance(start_index, int)
        and isinstance(end_index, int)
        and end_index > start_index
        and _annotation_matches(citation.get("annotation"), file_id, filename)
    )


def _annotation_matches(annotation: Any, file_id: str, filename: str) -> bool:
    return (
        isinstance(annotation, dict)
        and annotation.get("type") == "file_citation"
        and annotation.get("file_id") == file_id
        and annotation.get("filename") == filename
        and isinstance(annotation.get("index"), int)
        and int(annotation["index"]) >= 0
    )


def failed_query(case: dict[str, Any], error_name: str) -> dict[str, Any]:
    return {
        "id": case["id"],
        "query": case["query"],
        "expected_filenames": list(case["expected_filenames"]),
        "ranking_unit": "unique_filename_first_occurrence",
        "first_relevant_rank": None,
        "hit_at_k": False,
        "top1_hit": False,
        "recall_at_k": 0.0,
        "precision_at_k": 0.0,
        "reciprocal_rank": 0.0,
        "ndcg_at_k": 0.0,
        "support_complete": False,
        "missing_support_terms": list(case.get("support_terms", [])),
        "citation_complete": False,
        "result_count": 0,
        "unique_file_count": 0,
        "duplicate_rate": 0.0,
        "latency_ms": None,
        "search_query": None,
        "top_files": [],
        "error": error_name,
    }


def aggregate_candidate(rows: list[dict[str, Any]], *, metric_k: int, request_top_k: int) -> dict[str, Any]:
    count = max(1, len(rows))
    latencies = [float(row["latency_ms"]) for row in rows if row.get("latency_ms") is not None]

    def average(key: str) -> float:
        return round(sum(float(row[key]) for row in rows) / count, 6)

    return {
        "query_count": len(rows),
        "judged_query_count": sum(row.get("error") is None for row in rows),
        "ranking_unit": "unique_filename_first_occurrence",
        "error_rate": round(sum(row.get("error") is not None for row in rows) / count, 6),
        "recall_at_k": average("recall_at_k"),
        "precision_at_k": average("precision_at_k"),
        f"hit_at_{metric_k}": round(sum(bool(row["hit_at_k"]) for row in rows) / count, 6),
        "top1_accuracy": round(sum(bool(row["top1_hit"]) for row in rows) / count, 6),
        "mrr": average("reciprocal_rank"),
        f"ndcg_at_{metric_k}": average("ndcg_at_k"),
        f"support_at_{request_top_k}": round(sum(bool(row["support_complete"]) for row in rows) / count, 6),
        "citation_complete_rate": round(sum(bool(row["citation_complete"]) for row in rows) / count, 6),
        f"mean_unique_files_at_{request_top_k}": round(
            sum(int(row["unique_file_count"]) for row in rows) / count,
            6,
        ),
        "mean_duplicate_rate": average("duplicate_rate"),
        "latency_ms_avg": round(statistics.mean(latencies), 3) if latencies else None,
        "latency_ms_p95": percentile(latencies, 0.95),
    }


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    rank = (len(ordered) - 1) * fraction
    lower = math.floor(rank)
    upper = math.ceil(rank)
    value = ordered[lower] if lower == upper else ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)
    return round(value, 3)


def threshold_failures(metrics: dict[str, Any], thresholds: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    for rule, expected in sorted(thresholds.items()):
        if rule.startswith("min_"):
            metric_name = rule[4:]
            actual = metrics.get(metric_name)
            if not isinstance(actual, (int, float)) or float(actual) < float(expected):
                failures.append(rule)
        elif rule.startswith("max_"):
            metric_name = rule[4:]
            actual = metrics.get(metric_name)
            if not isinstance(actual, (int, float)) or float(actual) > float(expected):
                failures.append(rule)
        else:
            raise QualityEvalError(f"unsupported threshold rule: {rule}")
    return failures


def selection_score(metrics: dict[str, Any], *, metric_k: int, request_top_k: int) -> float:
    score = (
        float(metrics.get(f"hit_at_{metric_k}") or 0.0) * 0.25
        + float(metrics.get("top1_accuracy") or 0.0) * 0.15
        + float(metrics.get("mrr") or 0.0) * 0.2
        + float(metrics.get(f"ndcg_at_{metric_k}") or 0.0) * 0.15
        + float(metrics.get(f"support_at_{request_top_k}") or 0.0) * 0.15
        + float(metrics.get("citation_complete_rate") or 0.0) * 0.1
        - float(metrics.get("mean_duplicate_rate") or 0.0) * 0.05
    )
    return round(max(0.0, min(1.0, score)), 6)


def build_search_payload(case: dict[str, Any], candidate: dict[str, Any], request_top_k: int) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": case["query"],
        "rewrite_query": bool(candidate.get("rewrite_query", False)),
        "max_num_results": request_top_k,
        "ranking_options": dict(candidate.get("ranking_options") or {"ranker": "auto"}),
        "include_content": True,
        "include_metadata": True,
    }
    if candidate.get("retrieval_profile_id"):
        payload["retrieval_profile_id"] = candidate["retrieval_profile_id"]
    return payload


def run_quality_eval(
    golden: dict[str, Any],
    *,
    vector_store_id: str,
    request_json: RequestJson,
    selected_candidates: set[str] | None = None,
    warmup: bool = True,
    pace_seconds: float = 0.0,
) -> dict[str, Any]:
    validate_golden_set(golden)
    metric_k = int(golden["metric_k"])
    request_top_k = int(golden["request_top_k"])
    candidates = [
        candidate
        for candidate in golden["candidates"]
        if selected_candidates is None or candidate["id"] in selected_candidates
    ]
    if not candidates:
        raise QualityEvalError("no configured candidates selected")
    required_candidate_id = golden["required_candidate_id"]
    if required_candidate_id not in {candidate["id"] for candidate in candidates}:
        raise QualityEvalError("selected candidates must include required_candidate_id")

    store, _ = request_json("GET", f"/v1/vector_stores/{vector_store_id}", None)
    store_failures = validate_store(store, golden)
    if warmup:
        warmup_candidate = {
            "id": "warmup",
            "rewrite_query": False,
            "ranking_options": {"ranker": "none", "score_threshold": 0.0},
        }
        for case in golden["cases"]:
            payload = build_search_payload(case, warmup_candidate, 1)
            request_json("POST", f"/v1/vector_stores/{vector_store_id}/search", payload)
            if pace_seconds:
                time.sleep(pace_seconds)

    candidate_results: list[dict[str, Any]] = []
    for candidate in candidates:
        rows: list[dict[str, Any]] = []
        for case in golden["cases"]:
            try:
                response, latency_ms = request_json(
                    "POST",
                    f"/v1/vector_stores/{vector_store_id}/search",
                    build_search_payload(case, candidate, request_top_k),
                )
                rows.append(score_query(
                    case,
                    response,
                    metric_k=metric_k,
                    request_top_k=request_top_k,
                    latency_ms=latency_ms,
                ))
            except Exception as exc:
                error_name = exc.code if isinstance(exc, ApiRequestError) else type(exc).__name__
                rows.append(failed_query(case, error_name))
            if pace_seconds:
                time.sleep(pace_seconds)
        metrics = aggregate_candidate(rows, metric_k=metric_k, request_top_k=request_top_k)
        failures = threshold_failures(metrics, golden["thresholds"])
        candidate_results.append({
            "id": candidate["id"],
            "configuration": candidate,
            "status": "pass" if not failures else "fail",
            "threshold_failures": failures,
            "selection_score": selection_score(metrics, metric_k=metric_k, request_top_k=request_top_k),
            "metrics": metrics,
            "queries": rows,
        })

    passing = [candidate for candidate in candidate_results if candidate["status"] == "pass"]
    pool = passing or candidate_results
    best = max(
        pool,
        key=lambda candidate: (
            float(candidate["selection_score"]),
            -float(candidate["metrics"].get("latency_ms_p95") or float("inf")),
            candidate["id"],
        ),
    )
    required = next(candidate for candidate in candidate_results if candidate["id"] == required_candidate_id)
    promotion_delta = float(golden.get("promotion_min_score_delta") or 0.0)
    if (
        required["status"] == "pass"
        and best["id"] != required["id"]
        and float(best["selection_score"]) - float(required["selection_score"]) < promotion_delta
    ):
        recommended = required
        recommendation_reason = "required_candidate_within_promotion_margin"
    else:
        recommended = best
        recommendation_reason = "highest_passing_selection_score"
    status = "pass" if not store_failures and required["status"] == "pass" else "fail"
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "golden_set_id": golden["id"],
        "vector_store": {
            "id": store.get("id"),
            "name": store.get("name"),
            "status": store.get("status"),
            "file_counts": store.get("file_counts"),
        },
        "metric_k": metric_k,
        "request_top_k": request_top_k,
        "ranking_unit": "unique_filename_first_occurrence",
        "thresholds": golden["thresholds"],
        "store_failures": store_failures,
        "required_candidate_id": required_candidate_id,
        "promotion_min_score_delta": promotion_delta,
        "recommended_candidate_id": recommended["id"],
        "recommendation_reason": recommendation_reason,
        "candidate_results": candidate_results,
        "claim_boundary": (
            "Live retrieval quality for this judged ticket corpus and query set only; "
            "not a claim for unjudged customer corpora, raw PDF/OCR, or multimodal retrieval."
        ),
    }


def validate_store(store: dict[str, Any], golden: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    if store.get("status") != "completed":
        failures.append("store_not_completed")
    expected_name = golden.get("expected_store_name")
    if expected_name and store.get("name") != expected_name:
        failures.append("store_name_mismatch")
    file_counts = store.get("file_counts") if isinstance(store.get("file_counts"), dict) else {}
    completed = int(file_counts.get("completed") or 0)
    if completed < int(golden.get("minimum_completed_files") or 0):
        failures.append("completed_file_count_below_minimum")
    return failures


class LiveApiClient:
    def __init__(self, api: str, headers: dict[str, str], timeout_seconds: float):
        self.api = api.rstrip("/")
        self.headers = headers
        self.timeout_seconds = timeout_seconds

    def request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None,
    ) -> tuple[dict[str, Any], float]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        req = request.Request(self.api + path, data=body, headers=self.headers, method=method)
        started = time.perf_counter()
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                result = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            raise ApiRequestError(f"HTTP_{exc.code}") from None
        except Exception as exc:
            raise ApiRequestError(type(exc).__name__) from None
        return result, (time.perf_counter() - started) * 1000


def api_headers(args: argparse.Namespace) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if args.api_token:
        headers["Authorization"] = f"Bearer {args.api_token}"
    else:
        headers.update({
            "X-SVS-Tenant-Id": args.tenant_id,
            "X-SVS-Business-Instance-Id": args.business_instance_id,
            "X-SVS-User-Id": args.user_id,
            "X-SVS-Groups": args.groups,
            "X-SVS-Roles": args.roles,
            "X-SVS-Max-Security-Level": str(args.max_security_level),
        })
    return headers


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a judged live retrieval quality gate against an existing corpus.")
    parser.add_argument("--cell", default=DEFAULT_CELL)
    parser.add_argument("--api", default=None)
    parser.add_argument("--vector-store-id", required=True)
    parser.add_argument("--golden-set", type=Path, default=DEFAULT_GOLDEN_SET)
    parser.add_argument("--candidate", action="append", dest="candidates")
    parser.add_argument("--api-token", default=os.getenv("SVS_API_TOKEN"))
    parser.add_argument("--tenant-id", default="ten_dev")
    parser.add_argument("--business-instance-id", default="biz_dev")
    parser.add_argument("--user-id", default="usr_dev")
    parser.add_argument("--groups", default="grp_admin,grp_eng")
    parser.add_argument("--roles", default="owner,admin")
    parser.add_argument("--max-security-level", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=float, default=120.0)
    parser.add_argument("--pace-ms", type=float, default=250.0)
    parser.add_argument("--no-warmup", action="store_true")
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    golden = load_golden_set(args.golden_set)
    client = LiveApiClient(args.api or api_base(args.cell), api_headers(args), args.timeout_seconds)
    proof = run_quality_eval(
        golden,
        vector_store_id=args.vector_store_id,
        request_json=client.request_json,
        selected_candidates=set(args.candidates) if args.candidates else None,
        warmup=not args.no_warmup,
        pace_seconds=max(0.0, args.pace_ms / 1000.0),
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"QUALITY_STATUS={proof['status'].upper()}")
    print(f"GOLDEN_SET_ID={proof['golden_set_id']}")
    print(f"VECTOR_STORE_ID={proof['vector_store']['id']}")
    print(f"REQUIRED_CANDIDATE_ID={proof['required_candidate_id']}")
    print(f"RECOMMENDED_CANDIDATE_ID={proof['recommended_candidate_id']}")
    metric_k = proof["metric_k"]
    request_top_k = proof["request_top_k"]
    for candidate in proof["candidate_results"]:
        metrics = candidate["metrics"]
        print(
            f"candidate={candidate['id']} status={candidate['status']} "
            f"hit_at_{metric_k}={metrics.get(f'hit_at_{metric_k}')} mrr={metrics.get('mrr')} "
            f"ndcg_at_{metric_k}={metrics.get(f'ndcg_at_{metric_k}')} "
            f"support_at_{request_top_k}={metrics.get(f'support_at_{request_top_k}')} "
            f"citation_complete_rate={metrics.get('citation_complete_rate')} "
            f"latency_ms_p95={metrics.get('latency_ms_p95')} failures={candidate['threshold_failures']}"
        )
    if args.output:
        print(f"PROOF_FILE={args.output.resolve()}")
    return 0 if proof["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
