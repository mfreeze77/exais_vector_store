from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_script():
    path = ROOT / "scripts" / "release" / "corpus-quality-eval.py"
    spec = importlib.util.spec_from_file_location("corpus_quality_eval", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def golden():
    return {
        "schema_version": 1,
        "id": "test-golden",
        "expected_store_name": "expertaiservices",
        "minimum_completed_files": 2,
        "required_candidate_id": "default_auto",
        "promotion_min_score_delta": 0.01,
        "metric_k": 2,
        "request_top_k": 3,
        "thresholds": {
            "min_hit_at_2": 1.0,
            "min_top1_accuracy": 0.5,
            "min_mrr": 0.75,
            "min_ndcg_at_2": 0.8,
            "min_support_at_3": 1.0,
            "min_citation_complete_rate": 1.0,
            "min_mean_unique_files_at_3": 2.0,
            "max_error_rate": 0.0,
            "max_latency_ms_p95": 50.0,
        },
        "candidates": [{
            "id": "default_auto",
            "rewrite_query": False,
            "ranking_options": {"ranker": "auto", "score_threshold": 0.0},
        }],
        "cases": [
            {
                "id": "alpha",
                "query": "find alpha",
                "expected_filenames": ["alpha.md"],
                "support_terms": ["alpha-proof"],
            },
            {
                "id": "beta",
                "query": "find beta",
                "expected_filenames": ["beta.md"],
                "support_terms": ["beta evidence"],
            },
        ],
    }


def result(filename: str, text: str, score: float):
    file_id = f"doc_{filename}"
    annotation = {
        "type": "file_citation",
        "index": 0,
        "file_id": file_id,
        "filename": filename,
    }
    return {
        "file_id": file_id,
        "filename": filename,
        "score": score,
        "content": [{"type": "text", "text": text, "annotations": [annotation]}],
        "annotations": [annotation],
        "citation": {
            "file_id": file_id,
            "filename": filename,
            "chunk_id": f"chk_{filename}",
            "start_index": 0,
            "end_index": 1,
            "annotation": annotation,
        },
    }


def test_live_quality_gate_scores_filename_relevance_support_and_citations_without_text_leakage():
    script = load_script()

    def request_json(method, path, payload):
        if method == "GET":
            return {
                "id": "vs_test",
                "name": "expertaiservices",
                "status": "completed",
                "file_counts": {"completed": 2, "total": 2},
            }, 1.0
        if payload["query"] == "find alpha":
            data = [result("alpha.md", "Alpha proof passage", 0.9), result("noise.md", "noise", 0.2)]
        else:
            data = [result("noise.md", "noise", 0.8), result("beta.md", "Beta evidence passage", 0.7)]
        return {"data": data, "search_query": payload["query"]}, 20.0

    proof = script.run_quality_eval(
        golden(),
        vector_store_id="vs_test",
        request_json=request_json,
        warmup=False,
    )

    assert proof["status"] == "pass"
    assert proof["recommended_candidate_id"] == "default_auto"
    candidate = proof["candidate_results"][0]
    assert candidate["status"] == "pass"
    assert candidate["metrics"]["hit_at_2"] == 1.0
    assert candidate["metrics"]["top1_accuracy"] == 0.5
    assert candidate["metrics"]["mrr"] == 0.75
    assert candidate["metrics"]["support_at_3"] == 1.0
    assert candidate["metrics"]["citation_complete_rate"] == 1.0
    assert "Alpha proof passage" not in repr(proof)
    assert "Beta evidence passage" not in repr(proof)


def test_quality_gate_fails_required_candidate_on_support_and_store_thresholds():
    script = load_script()
    fixture = golden()
    fixture["minimum_completed_files"] = 3

    def request_json(method, path, payload):
        if method == "GET":
            return {
                "id": "vs_test",
                "name": "expertaiservices",
                "status": "completed",
                "file_counts": {"completed": 2, "total": 2},
            }, 1.0
        return {"data": [result("noise.md", "no supporting evidence", 0.5)]}, 10.0

    proof = script.run_quality_eval(
        fixture,
        vector_store_id="vs_test",
        request_json=request_json,
        warmup=False,
    )

    assert proof["status"] == "fail"
    assert proof["store_failures"] == ["completed_file_count_below_minimum"]
    assert "min_support_at_3" in proof["candidate_results"][0]["threshold_failures"]


def test_golden_set_validation_rejects_duplicate_case_ids():
    script = load_script()
    fixture = golden()
    fixture["cases"].append(dict(fixture["cases"][0]))

    with pytest.raises(script.QualityEvalError, match="case ids must be unique"):
        script.validate_golden_set(fixture)


def test_api_failure_keeps_safe_http_code_in_query_proof():
    script = load_script()

    def request_json(method, path, payload):
        if method == "GET":
            return {
                "id": "vs_test",
                "name": "expertaiservices",
                "status": "completed",
                "file_counts": {"completed": 2, "total": 2},
            }, 1.0
        raise script.ApiRequestError("HTTP_429")

    proof = script.run_quality_eval(
        golden(),
        vector_store_id="vs_test",
        request_json=request_json,
        warmup=False,
    )

    assert proof["status"] == "fail"
    assert {query["error"] for query in proof["candidate_results"][0]["queries"]} == {"HTTP_429"}


def test_citation_completeness_requires_native_identity_span_and_strict_annotation():
    script = load_script()
    item = result("alpha.md", "Alpha proof passage", 0.9)

    assert script._citation_complete(item) is True
    item["citation"].pop("chunk_id")
    assert script._citation_complete(item) is False


def test_document_metrics_dedupe_chunk_results_and_record_both_rank_units():
    script = load_script()
    case = {
        "id": "alpha",
        "query": "find alpha",
        "expected_filenames": ["alpha.md"],
        "support_terms": ["alpha proof"],
    }
    response = {
        "data": [
            result("noise.md", "noise one", 0.9),
            result("noise.md", "noise two", 0.8),
            result("alpha.md", "alpha proof", 0.7),
        ]
    }

    scored = script.score_query(case, response, metric_k=2, request_top_k=3, latency_ms=10.0)

    assert scored["ranking_unit"] == "unique_filename_first_occurrence"
    assert scored["first_relevant_rank"] == 2
    assert scored["reciprocal_rank"] == 0.5
    assert scored["top_files"][0]["document_rank"] == 1
    assert scored["top_files"][0]["result_rank"] == 1
    assert scored["top_files"][1]["document_rank"] == 2
    assert scored["top_files"][1]["result_rank"] == 3
    assert scored["top_files"][1]["chunk_id"] == "chk_alpha.md"


def test_support_terms_match_token_sequences_not_substrings():
    script = load_script()
    evidence = script.normalize_evidence("URLs are not row-level security policies")

    assert script.evidence_contains(evidence, "RLS") is False
    assert script.evidence_contains(script.normalize_evidence("RLS policy"), "RLS") is True
    assert script.evidence_contains(script.normalize_evidence("warm-up retry"), "warm-up") is True


def test_document_ranking_ignores_api_results_beyond_requested_raw_window():
    script = load_script()
    case = {
        "id": "alpha",
        "query": "find alpha",
        "expected_filenames": ["alpha.md"],
        "support_terms": ["alpha proof"],
    }
    response = {
        "data": [
            result("noise.md", "noise one", 0.9),
            result("noise.md", "noise two", 0.8),
            result("noise.md", "noise three", 0.7),
            result("alpha.md", "alpha proof", 0.6),
        ]
    }

    scored = script.score_query(case, response, metric_k=3, request_top_k=3, latency_ms=10.0)

    assert scored["result_count"] == 3
    assert scored["first_relevant_rank"] is None
    assert scored["hit_at_k"] is False
    assert scored["reciprocal_rank"] == 0.0
    assert [item["filename"] for item in scored["top_files"]] == ["noise.md"]


def test_support_phrase_cannot_match_across_passage_boundaries():
    script = load_script()
    case = {
        "id": "alpha",
        "query": "find alpha",
        "expected_filenames": ["alpha.md"],
        "support_terms": ["merge results"],
    }
    response = {
        "data": [
            result("alpha.md", "the operation will merge", 0.9),
            result("alpha.md", "results remain ranked", 0.8),
        ]
    }

    scored = script.score_query(case, response, metric_k=2, request_top_k=2, latency_ms=10.0)

    assert scored["support_complete"] is False
    assert scored["missing_support_terms"] == ["merge results"]


def test_promotion_margin_keeps_passing_required_candidate_for_immaterial_delta():
    script = load_script()
    fixture = golden()
    fixture["candidates"].append({
        "id": "alternative",
        "rewrite_query": False,
        "ranking_options": {"ranker": "none", "score_threshold": 0.0},
    })

    def request_json(method, path, payload):
        if method == "GET":
            return {
                "id": "vs_test",
                "name": "expertaiservices",
                "status": "completed",
                "file_counts": {"completed": 2, "total": 2},
            }, 1.0
        if payload["query"] == "find alpha":
            data = [result("alpha.md", "Alpha proof passage", 0.9), result("noise.md", "noise", 0.2)]
            if payload["ranking_options"]["ranker"] == "auto":
                data.append(result("noise.md", "duplicate noise", 0.1))
            else:
                data.append(result("other.md", "other", 0.1))
        else:
            data = [
                result("beta.md", "Beta evidence passage", 0.8),
                result("noise.md", "noise", 0.2),
                result("other.md", "other", 0.1),
            ]
        return {"data": data}, 20.0 if payload["ranking_options"]["ranker"] == "auto" else 19.0

    proof = script.run_quality_eval(
        fixture,
        vector_store_id="vs_test",
        request_json=request_json,
        warmup=False,
    )

    assert proof["recommended_candidate_id"] == "default_auto"
    assert proof["recommendation_reason"] == "required_candidate_within_promotion_margin"


def test_repo_ticket_golden_set_is_valid_and_answerability_anchored():
    script = load_script()
    fixture = script.load_golden_set(ROOT / "evals" / "expertaiservices-tickets" / "golden.json")

    assert len(fixture["cases"]) == 19
    assert fixture["required_candidate_id"] == "default_auto"
    for case in fixture["cases"]:
        assert case["support_terms"]
        source_evidence = []
        for filename in case["expected_filenames"]:
            source = ROOT / "tickets" / filename
            assert source.is_file(), f"missing judged source for {case['id']}: {filename}"
            source_evidence.append(script.normalize_evidence(source.read_text(encoding="utf-8")))
        for term in case["support_terms"]:
            assert any(script.evidence_contains(source, term) for source in source_evidence), (
                f"unanswerable support term for {case['id']}: {term}"
            )
