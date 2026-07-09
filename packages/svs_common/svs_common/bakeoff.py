from __future__ import annotations

from dataclasses import dataclass, field
import math
import time
from typing import Any, Protocol

from sqlalchemy import text
from sqlalchemy.orm import Session

from .chunking import estimate_tokens
from .db import jsonb_param
from .evals import golden_retrieval_metrics
from .ids import new_id
from .model_registry import estimate_embedding_cost, model_registry
from .schemas import BakeoffRunRequest, BakeoffRunResponse, Principal
from .sql import jsonb_text


@dataclass
class BakeoffRetrievalResult:
    result_ids: list[str] = field(default_factory=list)
    results: list[Any] = field(default_factory=list)
    latency_ms: float | int | None = None
    status: str = "completed"
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BakeoffRetrievalRunner(Protocol):
    def retrieve(
        self,
        *,
        db: Session,
        principal: Principal,
        query: dict[str, Any],
        model_profile_id: str,
        retrieval_profile_id: str | None,
        vector_store_id: str | None,
        knowledge_base_id: str | None,
        top_k: int,
        mode: str,
    ) -> BakeoffRetrievalResult:
        ...


def _result_primary_id(result: Any) -> str | None:
    if isinstance(result, str):
        return result
    if not isinstance(result, dict):
        return None
    for key in ("chunk_id", "id", "document_id"):
        value = result.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _result_ids(results: list[Any]) -> list[str]:
    ids: list[str] = []
    for result in results:
        result_id = _result_primary_id(result)
        if result_id:
            ids.append(result_id)
    return ids


def _coerce_result_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _profile_fixture_results(query: dict[str, Any], profile_id: str) -> list[Any]:
    for key in (
        "live_results_by_model_profile_id",
        "results_by_model_profile_id",
        "result_ids_by_model_profile_id",
    ):
        grouped = query.get(key)
        if isinstance(grouped, dict):
            results = grouped.get(profile_id)
            if isinstance(results, list):
                return results
    return _coerce_result_list(query.get("result_ids"))


def _profile_fixture_value(query: dict[str, Any], key: str, profile_id: str) -> Any:
    grouped = query.get(key)
    if isinstance(grouped, dict):
        return grouped.get(profile_id)
    return query.get(key)


SENSITIVE_METRIC_KEY_PARTS = ("secret", "api_key", "authorization", "password", "credential")
SENSITIVE_TOKEN_KEY_PARTS = ("api", "auth", "access", "refresh", "session", "bearer")


def _json_safe(value: Any, *, key: str | None = None) -> Any:
    normalized_key = (key or "").lower()
    is_sensitive_token_key = "token" in normalized_key and any(
        part in normalized_key for part in SENSITIVE_TOKEN_KEY_PARTS
    )
    if normalized_key and (
        is_sensitive_token_key or any(part in normalized_key for part in SENSITIVE_METRIC_KEY_PARTS)
    ):
        return "<redacted>"
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {str(k): _json_safe(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v, key=key) for v in value]
    return f"<{type(value).__name__}>"


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    rank = (len(ordered) - 1) * percentile
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return round(ordered[int(rank)], 3)
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower), 3)


class FixtureBakeoffRetrievalRunner:
    """Deterministic runner for tests, fixtures, and credential-free scripts."""

    def retrieve(
        self,
        *,
        db: Session,
        principal: Principal,
        query: dict[str, Any],
        model_profile_id: str,
        retrieval_profile_id: str | None,
        vector_store_id: str | None,
        knowledge_base_id: str | None,
        top_k: int,
        mode: str,
    ) -> BakeoffRetrievalResult:
        error = _profile_fixture_value(query, "error_by_model_profile_id", model_profile_id)
        if isinstance(error, str) and error:
            return BakeoffRetrievalResult(status="failed", error=error, latency_ms=0, results=[], result_ids=[])
        results = _profile_fixture_results(query, model_profile_id)[:top_k]
        latency_ms = _profile_fixture_value(query, "latency_ms_by_model_profile_id", model_profile_id)
        if latency_ms is None:
            latency_ms = query.get("latency_ms", 0)
        return BakeoffRetrievalResult(
            results=results,
            result_ids=_result_ids(results),
            latency_ms=float(latency_ms or 0),
            status="completed",
            metadata={"source": "fixture"},
        )


class BakeoffService:
    """Retrieval-model bakeoff ledger with deterministic and live fan-out modes."""

    def __init__(self, retrieval_runner: BakeoffRetrievalRunner | None = None):
        self.retrieval_runner = retrieval_runner or FixtureBakeoffRetrievalRunner()

    def create_run(self, db: Session, principal: Principal, req: BakeoffRunRequest) -> BakeoffRunResponse:
        run_id = new_id("eval")
        db.execute(jsonb_text('''
            INSERT INTO bakeoff_runs(id, tenant_id, business_instance_id, user_id, name, mode, model_profile_ids, queries, status)
            VALUES (:id, :tenant_id, :biz_id, :user_id, :name, :mode, :model_profile_ids, CAST(:queries AS jsonb), 'running')
        '''), {
            "id": run_id,
            "tenant_id": principal.tenant_id,
            "biz_id": principal.business_instance_id,
            "user_id": principal.user_id,
            "name": req.name,
            "mode": req.mode,
            "model_profile_ids": req.model_profile_ids,
            "queries": jsonb_param(req.queries),
        })

        registry = model_registry().get("models", {})
        execution_mode = "live" if req.execution_mode in {"live", "live_retrieval"} else "deterministic"
        if execution_mode == "live":
            results = self._live_results(db, principal, req, registry)
        else:
            results = self._deterministic_results(req, registry)

        for result in results:
            db.execute(jsonb_text('''
                INSERT INTO bakeoff_results(id, tenant_id, business_instance_id, run_id, model_profile_id, metrics, status)
                VALUES (:id, :tenant_id, :biz_id, :run_id, :model_profile_id, CAST(:metrics AS jsonb), :status)
            ''', "metrics"), {
                "id": new_id("bres"),
                "tenant_id": principal.tenant_id,
                "biz_id": principal.business_instance_id,
                "run_id": run_id,
                "model_profile_id": result["model_profile_id"],
                "metrics": jsonb_param(_json_safe(result)),
                "status": result.get("status") or "completed",
            })

        metrics = self._run_metrics(req, results, execution_mode)
        db.execute(
            jsonb_text(
                "UPDATE bakeoff_runs SET status='completed', metrics=CAST(:metrics AS jsonb), completed_at=now() WHERE id=:id",
                "metrics",
            ),
            {"id": run_id, "metrics": jsonb_param(_json_safe(metrics))},
        )
        return BakeoffRunResponse(id=run_id, status="completed", metrics=metrics, results=results)

    def _deterministic_results(self, req: BakeoffRunRequest, registry: dict[str, Any]) -> list[dict[str, Any]]:
        results = []
        for profile_id in req.model_profile_ids:
            p = registry.get(profile_id, {})
            latency_proxy_ms = 40 + int(p.get("dimensions", 1536)) / 10
            metrics = golden_retrieval_metrics(req.queries, profile_id, k=req.top_k)
            if metrics["result_source"] == "golden_results":
                score = self._golden_score(metrics)
            else:
                total_queries = max(1, len(req.queries))
                positive_refs = sum(
                    1 for q in req.queries if q.get("expected_chunk_ids") or q.get("expected_document_ids")
                )
                metrics["recall_proxy"] = positive_refs / total_queries
                score = round(
                    (metrics["recall_proxy"] * 0.7)
                    + (1.0 / max(1.0, latency_proxy_ms / 100)) * 0.3,
                    4,
                )
            results.append({
                "model_profile_id": profile_id,
                "provider": p.get("provider"),
                "model": p.get("model"),
                "dimensions": p.get("dimensions"),
                "latency_proxy_ms": latency_proxy_ms,
                "status": "completed",
                "score": score,
                **metrics,
            })
        return results

    def _live_results(
        self,
        db: Session,
        principal: Principal,
        req: BakeoffRunRequest,
        registry: dict[str, Any],
    ) -> list[dict[str, Any]]:
        results = []
        for profile_id in req.model_profile_ids:
            p = registry.get(profile_id, {})
            live_queries: list[dict[str, Any]] = []
            live_details: list[dict[str, Any]] = []
            latencies: list[float] = []
            success_count = 0
            error_count = 0
            total_result_count = 0
            total_cost = 0.0
            cost_unavailable = False
            total_estimated_tokens = 0

            for index, query in enumerate(req.queries):
                query_obj = query if isinstance(query, dict) else {"query": str(query)}
                query_id = str(query_obj.get("id") or f"query_{index + 1}")
                query_text = str(query_obj.get("query") or query_obj.get("text") or "")
                started = time.perf_counter()
                try:
                    retrieved = self.retrieval_runner.retrieve(
                        db=db,
                        principal=principal,
                        query=query_obj,
                        model_profile_id=profile_id,
                        retrieval_profile_id=req.retrieval_profile_id,
                        vector_store_id=req.vector_store_id,
                        knowledge_base_id=req.knowledge_base_id,
                        top_k=req.top_k,
                        mode=req.mode,
                    )
                except Exception as exc:
                    retrieved = BakeoffRetrievalResult(status="failed", error=type(exc).__name__)
                elapsed_ms = max(0.0, (time.perf_counter() - started) * 1000)
                latency_ms = float(retrieved.latency_ms) if retrieved.latency_ms is not None else elapsed_ms
                result_items = retrieved.results or list(retrieved.result_ids)
                result_ids = retrieved.result_ids or _result_ids(result_items)
                status = retrieved.status or ("failed" if retrieved.error else "completed")
                if status == "completed":
                    success_count += 1
                else:
                    error_count += 1
                if retrieved.error:
                    error_count += 1 if status == "completed" else 0
                latencies.append(latency_ms)
                total_result_count += len(result_ids)

                estimated_tokens = _query_estimated_tokens(query_obj, query_text)
                total_estimated_tokens += estimated_tokens
                cost = _estimate_profile_query_cost(profile_id, estimated_tokens, p)
                if cost.get("estimated_cost_usd") is None:
                    cost_unavailable = True
                else:
                    total_cost += float(cost["estimated_cost_usd"])

                live_query = {
                    **query_obj,
                    "results_by_model_profile_id": {profile_id: result_items},
                }
                live_queries.append(live_query)
                live_details.append({
                    "id": query_id,
                    "query": query_text,
                    "status": status,
                    "error": retrieved.error,
                    "result_ids": result_ids,
                    "result_count": len(result_ids),
                    "latency_ms": round(latency_ms, 3),
                    "estimated_tokens": estimated_tokens,
                    "estimated_cost_usd": cost.get("estimated_cost_usd"),
                    "cost_reason": cost.get("reason"),
                    "runner_metadata": retrieved.metadata,
                })

            golden = golden_retrieval_metrics(live_queries, profile_id, k=req.top_k)
            score = self._live_score(golden, success_count, len(req.queries), latencies, error_count)
            latency_avg = round(sum(latencies) / len(latencies), 3) if latencies else None
            latency_p95 = _percentile(latencies, 0.95)
            candidate_status = "failed" if req.queries and success_count == 0 else "completed"
            if error_count and success_count:
                candidate_status = "completed_with_errors"
            result = {
                "model_profile_id": profile_id,
                "provider": p.get("provider"),
                "model": p.get("model"),
                "dimensions": p.get("dimensions"),
                "execution_mode": "live",
                "retrieval_profile_id": req.retrieval_profile_id,
                "vector_store_id": req.vector_store_id,
                "knowledge_base_id": req.knowledge_base_id,
                "status": candidate_status,
                "score": score,
                "query_count": len(req.queries),
                "success_count": success_count,
                "error_count": error_count,
                "total_result_count": total_result_count,
                "latency_ms_avg": latency_avg,
                "latency_ms_p95": latency_p95,
                "estimated_tokens": total_estimated_tokens,
                "estimated_cost_usd": None if cost_unavailable else round(total_cost, 10),
                "cost_reason": "cost_unavailable" if cost_unavailable else None,
                "live_query_results": live_details,
                **golden,
            }
            results.append(_json_safe(result))
        return results

    @staticmethod
    def _golden_score(metrics: dict[str, Any]) -> float:
        leakage_penalty = min(int(metrics.get("leakage_count") or 0), 10) * 0.1
        return round(max(
            0.0,
            (metrics["recall_at_k"] * 0.45)
            + (metrics["mrr"] * 0.25)
            + (metrics["ndcg_at_k"] * 0.2)
            + (metrics["precision_at_k"] * 0.1)
            - leakage_penalty,
        ), 4)

    def _live_score(
        self,
        golden: dict[str, Any],
        success_count: int,
        query_count: int,
        latencies: list[float],
        error_count: int,
    ) -> float:
        if golden["result_source"] == "golden_results":
            score = self._golden_score(golden)
        else:
            success_rate = success_count / max(1, query_count)
            result_rate = 1.0 if success_count else 0.0
            score = (success_rate * 0.7) + (result_rate * 0.2)
        latency_p95 = _percentile(latencies, 0.95)
        if latency_p95 is not None:
            score += min(0.1, 100.0 / max(1000.0, latency_p95) * 0.1)
        if error_count:
            score -= min(0.2, error_count * 0.05)
        return round(max(0.0, min(score, 1.0)), 4)

    def _run_metrics(
        self,
        req: BakeoffRunRequest,
        results: list[dict[str, Any]],
        execution_mode: str,
    ) -> dict[str, Any]:
        best = _best_candidate(results, req.selection_policy)
        selection = _apply_selection_policy(best, req.selection_policy, results)
        metric_source = _metric_source(results, execution_mode)
        return _json_safe({
            "candidate_count": len(results),
            "query_count": len(req.queries),
            "execution_mode": execution_mode,
            "mode": req.mode,
            "golden_set_id": req.golden_set_id,
            "vector_store_id": req.vector_store_id,
            "knowledge_base_id": req.knowledge_base_id,
            "retrieval_profile_id": req.retrieval_profile_id,
            "requested_metrics": req.metrics,
            "metric_source": metric_source,
            "selection_status": selection["status"],
            "best_model_profile_id": best.get("model_profile_id") if best else None,
            "winner_model_profile_id": selection["winner_model_profile_id"],
            "rejection_reasons": selection["rejection_reasons"],
            "selection_policy": req.selection_policy,
        })

    def get_run(self, db: Session, principal: Principal, run_id: str) -> BakeoffRunResponse | None:
        row = db.execute(text('''
            SELECT id, status, metrics FROM bakeoff_runs
            WHERE id=:id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
        '''), {"id": run_id, "tenant_id": principal.tenant_id, "biz_id": principal.business_instance_id}).mappings().first()
        if not row:
            return None
        results = db.execute(text('''
            SELECT metrics FROM bakeoff_results
            WHERE run_id=:id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
            ORDER BY created_at ASC
        '''), {"id": run_id, "tenant_id": principal.tenant_id, "biz_id": principal.business_instance_id}).mappings().all()
        return BakeoffRunResponse(
            id=row["id"],
            status=row["status"],
            metrics=dict(row["metrics"] or {}),
            results=[dict(r["metrics"] or {}) for r in results],
        )

    def list_runs(self, db: Session, principal: Principal, *, limit: int = 20) -> tuple[list[dict[str, Any]], bool]:
        req_limit = min(max(int(limit or 20), 1), 100)
        rows = db.execute(text('''
            SELECT id, name, mode, model_profile_ids, status, metrics,
                   extract(epoch from created_at)::bigint AS created_at,
                   extract(epoch from completed_at)::bigint AS completed_at
            FROM bakeoff_runs
            WHERE tenant_id=:tenant_id AND business_instance_id=:biz_id
            ORDER BY created_at DESC, id DESC
            LIMIT :limit
        '''), {
            "tenant_id": principal.tenant_id,
            "biz_id": principal.business_instance_id,
            "limit": req_limit + 1,
        }).mappings().all()
        data = []
        for row in rows[:req_limit]:
            data.append(_json_safe({
                "id": row["id"],
                "name": row["name"],
                "mode": row["mode"],
                "model_profile_ids": list(row["model_profile_ids"] or []),
                "status": row["status"],
                "metrics": dict(row["metrics"] or {}),
                "created_at": row["created_at"],
                "completed_at": row["completed_at"],
            }))
        return data, len(rows) > req_limit


def _query_estimated_tokens(query: dict[str, Any], query_text: str) -> int:
    explicit = query.get("estimated_tokens")
    if isinstance(explicit, int) and explicit >= 0:
        return explicit
    return estimate_tokens(query_text)


def _estimate_profile_query_cost(profile_id: str, tokens: int, profile: dict[str, Any]) -> dict[str, Any]:
    provider = profile.get("provider")
    privacy = profile.get("privacy")
    if provider == "hash_mock" or privacy in {"local_dev", "local_dev_only"}:
        return {
            "model_profile_id": profile_id,
            "provider": provider,
            "model": profile.get("model"),
            "dimensions": profile.get("dimensions"),
            "estimated_tokens": tokens,
            "estimated_cost_usd": 0.0,
            "currency": "USD",
            "unit": "1m_input_tokens",
            "input_per_1m_tokens_usd": 0.0,
            "cost_source": "local_dev",
            "reason": None,
        }
    return estimate_embedding_cost(profile_id, tokens)


def _metric_source(results: list[dict[str, Any]], execution_mode: str) -> str:
    has_golden = any(result.get("result_source") == "golden_results" for result in results)
    if execution_mode == "live":
        return "live_golden_results" if has_golden else "live_retrieval"
    return "golden_results" if has_golden else "proxy"


def _best_candidate(results: list[dict[str, Any]], selection_policy: dict[str, Any]) -> dict[str, Any] | None:
    if not results:
        return None
    metric = selection_policy.get("selection_metric") if isinstance(selection_policy, dict) else None
    if not isinstance(metric, str) or not metric:
        metric = "score"
    return max(results, key=lambda result: _numeric_metric(result, metric))


def _numeric_metric(result: dict[str, Any], key: str) -> float:
    value = result.get(key)
    if isinstance(value, bool) or value is None:
        return float("-inf")
    if isinstance(value, (int, float)):
        return float(value)
    return float("-inf")


def _apply_selection_policy(
    best: dict[str, Any] | None,
    selection_policy: dict[str, Any],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    if not best:
        return {"status": "rejected", "winner_model_profile_id": None, "rejection_reasons": ["no_candidates"]}
    policy = selection_policy if isinstance(selection_policy, dict) else {}
    reasons: list[str] = []
    if best.get("status") == "failed":
        reasons.append("winner_failed")
    if _threshold_failed(best, "score", policy.get("min_score")):
        reasons.append("score_below_minimum")
    if _threshold_failed(best, "recall_at_k", policy.get("min_recall_at_k")):
        reasons.append("recall_below_minimum")
    if policy.get("require_no_leakage") and int(best.get("leakage_count") or 0) > 0:
        reasons.append("leakage_present")
    max_leakage = policy.get("max_leakage_count")
    if isinstance(max_leakage, int) and int(best.get("leakage_count") or 0) > max_leakage:
        reasons.append("leakage_above_maximum")
    max_latency = policy.get("max_latency_ms")
    if isinstance(max_latency, (int, float)) and best.get("latency_ms_p95") is not None:
        if float(best["latency_ms_p95"]) > float(max_latency):
            reasons.append("latency_above_maximum")
    max_cost = policy.get("max_estimated_cost_usd")
    if isinstance(max_cost, (int, float)):
        cost = best.get("estimated_cost_usd")
        if cost is None:
            reasons.append("cost_unavailable")
        elif float(cost) > float(max_cost):
            reasons.append("cost_above_maximum")
    if policy.get("require_cost_estimate") and best.get("estimated_cost_usd") is None:
        reasons.append("cost_unavailable")
    if policy.get("require_all_candidates_success") and any(r.get("status") == "failed" for r in results):
        reasons.append("candidate_failed")
    status = "rejected" if reasons else "selected"
    return {
        "status": status,
        "winner_model_profile_id": None if reasons else best.get("model_profile_id"),
        "rejection_reasons": reasons,
    }


def _threshold_failed(result: dict[str, Any], key: str, minimum: Any) -> bool:
    if not isinstance(minimum, (int, float)):
        return False
    value = result.get(key)
    if not isinstance(value, (int, float)):
        return True
    return float(value) < float(minimum)
