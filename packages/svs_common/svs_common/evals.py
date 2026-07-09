from __future__ import annotations
from dataclasses import dataclass
import math
from typing import Any

@dataclass
class RetrievalEvalCase:
    id: str
    query: str
    expected_chunk_ids: list[str]
    forbidden_chunk_ids: list[str]
    security_level: int = 1

def recall_at_k(result_ids: list[str], expected_ids: list[str], k: int) -> float:
    if not expected_ids:
        return 1.0
    return len(set(result_ids[:k]).intersection(expected_ids)) / len(set(expected_ids))

def leakage_count(result_ids: list[str], forbidden_ids: list[str]) -> int:
    return len(set(result_ids).intersection(forbidden_ids))


def precision_at_k(result_ids: list[str], expected_ids: list[str], k: int) -> float:
    if k <= 0:
        return 0.0
    if not expected_ids:
        return 1.0
    return len(set(result_ids[:k]).intersection(expected_ids)) / k


def reciprocal_rank(result_ids: list[str], expected_ids: list[str]) -> float:
    expected = set(expected_ids)
    if not expected:
        return 1.0
    for rank, result_id in enumerate(result_ids, start=1):
        if result_id in expected:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(result_ids: list[str], expected_ids: list[str], k: int) -> float:
    if k <= 0:
        return 0.0
    expected = set(expected_ids)
    if not expected:
        return 1.0
    dcg = 0.0
    seen: set[str] = set()
    for rank, result_id in enumerate(result_ids[:k], start=1):
        if result_id in expected and result_id not in seen:
            dcg += 1.0 / math.log2(rank + 1)
            seen.add(result_id)
    ideal_count = min(len(expected), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
    return dcg / idcg if idcg else 0.0


def _query_results_for_profile(query: dict[str, Any], profile_id: str) -> list[Any]:
    for key in ("results_by_model_profile_id", "result_ids_by_model_profile_id"):
        grouped = query.get(key)
        if isinstance(grouped, dict):
            results = grouped.get(profile_id)
            if isinstance(results, list):
                return results
    shared_results = query.get("result_ids")
    return shared_results if isinstance(shared_results, list) else []


def _result_match_ids(result: Any) -> set[str]:
    if isinstance(result, str):
        return {result}
    if not isinstance(result, dict):
        return set()
    ids: set[str] = set()
    for key in ("id", "chunk_id", "document_id"):
        value = result.get(key)
        if isinstance(value, str) and value:
            ids.add(value)
    return ids


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


def _expected_ids(query: dict[str, Any]) -> set[str]:
    expected: set[str] = set()
    for key in ("expected_chunk_ids", "expected_document_ids"):
        values = query.get(key)
        if isinstance(values, list):
            expected.update(str(value) for value in values if isinstance(value, str) and value)
    return expected


def _forbidden_ids(query: dict[str, Any]) -> set[str]:
    forbidden: set[str] = set()
    for key in ("forbidden_chunk_ids", "forbidden_document_ids"):
        values = query.get(key)
        if isinstance(values, list):
            forbidden.update(str(value) for value in values if isinstance(value, str) and value)
    return forbidden


def golden_retrieval_metrics(queries: list[dict[str, Any]], profile_id: str, *, k: int) -> dict[str, Any]:
    judged = []
    leakage_total = 0
    leakage_query_count = 0
    for query in queries:
        if not isinstance(query, dict):
            continue
        results = _query_results_for_profile(query, profile_id)
        if not results:
            continue
        expected = _expected_ids(query)
        if not expected:
            continue
        ranked_matches: list[str | None] = []
        matched_expected_at_k: set[str] = set()
        forbidden = _forbidden_ids(query)
        query_leakage = 0
        for rank, result in enumerate(results, start=1):
            match_ids = _result_match_ids(result)
            matching_expected = sorted(match_ids.intersection(expected))
            ranked_matches.append(matching_expected[0] if matching_expected else None)
            if rank <= k:
                matched_expected_at_k.update(matching_expected)
            if match_ids.intersection(forbidden):
                query_leakage += 1
        leakage_total += query_leakage
        if query_leakage:
            leakage_query_count += 1

        relevant_at_k = sum(1 for match in ranked_matches[:k] if match is not None)
        first_relevant_rank = next(
            (rank for rank, match in enumerate(ranked_matches, start=1) if match is not None),
            None,
        )
        seen_ndcg: set[str] = set()
        dcg = 0.0
        for rank, match in enumerate(ranked_matches[:k], start=1):
            if match is not None and match not in seen_ndcg:
                dcg += 1.0 / math.log2(rank + 1)
                seen_ndcg.add(match)
        ideal_count = min(len(expected), k)
        idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_count + 1))
        judged.append({
            "id": query.get("id"),
            "recall_at_k": len(matched_expected_at_k) / len(expected),
            "precision_at_k": relevant_at_k / k if k > 0 else 0.0,
            "mrr": (1.0 / first_relevant_rank) if first_relevant_rank else 0.0,
            "ndcg_at_k": (dcg / idcg) if idcg else 0.0,
            "leakage_count": query_leakage,
        })
    if not judged:
        return {
            "result_source": "proxy",
            "query_count": len(queries),
            "judged_query_count": 0,
            "top_k": k,
        }

    def average(key: str) -> float:
        return round(sum(float(item[key]) for item in judged) / len(judged), 6)

    return {
        "result_source": "golden_results",
        "query_count": len(queries),
        "judged_query_count": len(judged),
        "top_k": k,
        "recall_at_k": average("recall_at_k"),
        "precision_at_k": average("precision_at_k"),
        "mrr": average("mrr"),
        "ndcg_at_k": average("ndcg_at_k"),
        "leakage_count": leakage_total,
        "leakage_query_count": leakage_query_count,
        "per_query": judged,
    }
