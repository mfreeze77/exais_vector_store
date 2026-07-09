from __future__ import annotations

import pytest
from pydantic import ValidationError

from svs_common.bakeoff import BakeoffService
from svs_common.evals import golden_retrieval_metrics
from svs_common.schemas import BakeoffRunRequest, Principal


class _Rows:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []

    def mappings(self):
        return self

    def first(self):
        return self.row

    def all(self):
        return self.rows


class _Db:
    def __init__(self):
        self.calls = []

    def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params or {}))
        return _Rows()


def _principal() -> Principal:
    return Principal(tenant_id="tenant", business_instance_id="biz", user_id="user")


def _golden_queries() -> list[dict[str, object]]:
    return [
        {
            "id": "exact_chunk",
            "query": "find chunk a",
            "expected_chunk_ids": ["chk_a"],
            "results_by_model_profile_id": {
                "hash_mock_1536": ["chk_a", "chk_b"],
                "openai_text_embedding_3_small_1536": ["chk_b", "chk_a"],
            },
        },
        {
            "id": "document_match_with_leakage",
            "query": "find document two",
            "expected_document_ids": ["doc_2"],
            "forbidden_chunk_ids": ["chk_secret"],
            "results_by_model_profile_id": {
                "hash_mock_1536": [
                    {"chunk_id": "chk_x", "document_id": "doc_2"},
                    {"chunk_id": "chk_secret", "document_id": "doc_secret"},
                ],
                "openai_text_embedding_3_small_1536": [
                    {"chunk_id": "chk_y", "document_id": "doc_none"},
                ],
            },
        },
    ]


def test_golden_retrieval_metrics_score_chunk_document_and_leakage_matches():
    metrics = golden_retrieval_metrics(_golden_queries(), "hash_mock_1536", k=2)

    assert metrics["result_source"] == "golden_results"
    assert metrics["query_count"] == 2
    assert metrics["judged_query_count"] == 2
    assert metrics["recall_at_k"] == 1.0
    assert metrics["precision_at_k"] == 0.5
    assert metrics["mrr"] == 1.0
    assert metrics["ndcg_at_k"] == 1.0
    assert metrics["leakage_count"] == 1
    assert metrics["leakage_query_count"] == 1
    assert [item["id"] for item in metrics["per_query"]] == ["exact_chunk", "document_match_with_leakage"]


def test_bakeoff_create_run_uses_golden_metrics_when_results_are_present():
    service = BakeoffService()
    db = _Db()
    req = BakeoffRunRequest(
        name="golden",
        model_profile_ids=["hash_mock_1536", "openai_text_embedding_3_small_1536"],
        queries=_golden_queries(),
        top_k=2,
    )

    response = service.create_run(db, _principal(), req)

    assert response.status == "completed"
    assert response.metrics["metric_source"] == "golden_results"
    assert response.metrics["candidate_count"] == 2
    assert response.metrics["best_model_profile_id"] == "hash_mock_1536"
    first, second = response.results
    assert first["model_profile_id"] == "hash_mock_1536"
    assert first["result_source"] == "golden_results"
    assert first["recall_at_k"] == 1.0
    assert first["leakage_count"] == 1
    assert first["score"] == 0.85
    assert second["model_profile_id"] == "openai_text_embedding_3_small_1536"
    assert second["result_source"] == "golden_results"
    assert second["score"] < first["score"]
    assert len([call for call in db.calls if "INSERT INTO bakeoff_results" in call[0]]) == 2


def test_bakeoff_create_run_keeps_proxy_fallback_without_candidate_results():
    service = BakeoffService()
    req = BakeoffRunRequest(
        name="proxy",
        model_profile_ids=["hash_mock_1536"],
        queries=[{"id": "q1", "query": "fallback", "expected_chunk_ids": ["chk_1"]}],
    )

    response = service.create_run(_Db(), _principal(), req)

    assert response.metrics["metric_source"] == "proxy"
    assert response.results[0]["result_source"] == "proxy"
    assert response.results[0]["judged_query_count"] == 0
    assert response.results[0]["recall_proxy"] == 1.0
    assert response.results[0]["score"] > 0


def test_bakeoff_top_k_is_bounded_for_metrics():
    with pytest.raises(ValidationError):
        BakeoffRunRequest(name="bad", model_profile_ids=["hash_mock_1536"], top_k=0)
