from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from fastapi import HTTPException

from svs_api import main as api_main
from svs_common.bakeoff import BakeoffRetrievalResult, BakeoffService
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
    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls = []

    def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params or {}))
        if self.results:
            result = self.results.pop(0)
            if isinstance(result, list):
                return _Rows(rows=result)
            return _Rows(row=result)
        return _Rows()


class _Runner:
    def __init__(self):
        self.calls = []

    def retrieve(self, **kwargs):
        self.calls.append(kwargs)
        profile_id = kwargs["model_profile_id"]
        query = kwargs["query"]
        if profile_id == "hash_mock_1536":
            result_id = query["expected_chunk_ids"][0]
            latency_ms = 11
        else:
            result_id = "chk_miss"
            latency_ms = 28
        return BakeoffRetrievalResult(
            results=[{"chunk_id": result_id, "document_id": f"doc_{result_id}"}],
            latency_ms=latency_ms,
            metadata={"runner": "test", "api_token": "must-not-leak", "client": object()},
        )


def _principal(scopes=None) -> Principal:
    return Principal(
        tenant_id="tenant",
        business_instance_id="biz",
        user_id="user",
        scopes=scopes or ["evals:read", "evals:write"],
    )


def _queries() -> list[dict[str, object]]:
    return [
        {"id": "q1", "query": "find alpha", "expected_chunk_ids": ["chk_alpha"], "estimated_tokens": 12},
        {"id": "q2", "query": "find beta", "expected_chunk_ids": ["chk_beta"], "estimated_tokens": 14},
    ]


def test_live_bakeoff_fans_out_queries_through_injected_runner():
    runner = _Runner()
    service = BakeoffService(retrieval_runner=runner)
    req = BakeoffRunRequest(
        name="live",
        execution_mode="live",
        model_profile_ids=["hash_mock_1536", "openai_text_embedding_3_small_1536"],
        queries=_queries(),
        top_k=2,
        vector_store_id="vs_live",
        knowledge_base_id="kb_live",
        retrieval_profile_id="hybrid_rrf_secure_v2",
        golden_set_id="golden_live",
        selection_policy={"min_recall_at_k": 1.0, "max_latency_ms": 20, "max_estimated_cost_usd": 0.0},
    )

    response = service.create_run(_Db(), _principal(), req)

    assert len(runner.calls) == 4
    assert {call["model_profile_id"] for call in runner.calls} == {
        "hash_mock_1536",
        "openai_text_embedding_3_small_1536",
    }
    assert all(call["vector_store_id"] == "vs_live" for call in runner.calls)
    assert all(call["retrieval_profile_id"] == "hybrid_rrf_secure_v2" for call in runner.calls)
    assert response.metrics["execution_mode"] == "live"
    assert response.metrics["metric_source"] == "live_golden_results"
    assert response.metrics["selection_status"] == "selected"
    assert response.metrics["winner_model_profile_id"] == "hash_mock_1536"
    first, second = response.results
    assert first["model_profile_id"] == "hash_mock_1536"
    assert first["recall_at_k"] == 1.0
    assert first["latency_ms_p95"] == 11
    assert first["estimated_tokens"] == 26
    assert first["estimated_cost_usd"] == 0.0
    assert first["live_query_results"][0]["result_ids"] == ["chk_alpha"]
    assert first["live_query_results"][0]["estimated_tokens"] == 12
    assert first["live_query_results"][0]["runner_metadata"] == {
        "runner": "test",
        "api_token": "<redacted>",
        "client": "<object>",
    }
    assert second["recall_at_k"] == 0.0
    assert second["estimated_cost_usd"] is not None


def test_bakeoff_list_runs_is_scoped_and_paginated():
    rows = [
        {
            "id": "eval_2",
            "name": "second",
            "mode": "markdown_docs_v1",
            "model_profile_ids": ["hash_mock_1536"],
            "status": "completed",
            "metrics": {"selection_status": "selected"},
            "created_at": 1720000002,
            "completed_at": 1720000003,
        },
        {
            "id": "eval_1",
            "name": "first",
            "mode": "markdown_docs_v1",
            "model_profile_ids": ["openai_text_embedding_3_small_1536"],
            "status": "completed",
            "metrics": {},
            "created_at": 1720000001,
            "completed_at": 1720000002,
        },
    ]
    db = _Db(results=[rows])

    data, has_more = BakeoffService().list_runs(db, _principal(), limit=1)

    assert has_more is True
    assert data == [{
        "id": "eval_2",
        "name": "second",
        "mode": "markdown_docs_v1",
        "model_profile_ids": ["hash_mock_1536"],
        "status": "completed",
        "metrics": {"selection_status": "selected"},
        "created_at": 1720000002,
        "completed_at": 1720000003,
    }]
    sql, params = db.calls[0]
    assert "tenant_id=:tenant_id" in sql
    assert "business_instance_id=:biz_id" in sql
    assert params["tenant_id"] == "tenant"
    assert params["biz_id"] == "biz"
    assert params["limit"] == 2


def test_list_bakeoffs_route_requires_eval_read_scope():
    db = _Db(results=[[]])
    page = api_main.list_bakeoffs(principal=_principal(["evals:read"]), db=db)

    assert page == {"object": "list", "data": [], "first_id": None, "last_id": None, "has_more": False}
    with pytest.raises(HTTPException) as exc:
        api_main.list_bakeoffs(principal=_principal(["retrieval:read"]), db=_Db())
    assert exc.value.status_code == 403


def _load_live_bakeoff_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "release" / "live-bakeoff.py"
    spec = importlib.util.spec_from_file_location("live_bakeoff_script", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_live_bakeoff_script_fixture_mode_and_header_redaction(capsys):
    script = _load_live_bakeoff_script()

    exit_code = script.main(["--api-token", "svs_live_secret_token"])

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "svs_live_secret_token" not in out
    assert '"mode": "fixture"' in out

    args = script.build_parser().parse_args(["--api-token", "svs_live_secret_token"])
    assert script.redacted_header_summary(script.api_headers(args))["Authorization"] == "Bearer <redacted>"
