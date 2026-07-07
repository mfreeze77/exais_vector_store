from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release" / "openai-file-search-parity-eval.py"


def load_module():
    spec = importlib.util.spec_from_file_location("openai_file_search_parity_eval", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_ticket_golden_cases_reference_existing_files():
    module = load_module()
    cases = module.load_cases(ROOT / "evals" / "openai-file-search-parity" / "ticket_golden.json")

    module.validate_cases(cases, ROOT)


def test_score_response_requires_results_and_expected_text():
    module = load_module()
    query_case = {"min_results": 1, "must_contain": ["RunPod", "Marker"]}
    response = {
        "search_query": "RunPod Marker warmup",
        "data": [
            {
                "filename": "WAVE-010-runpod-marker-pdf-ingestion.md",
                "content": [{"type": "text", "text": "RunPod Marker retries after warmup."}],
            }
        ],
    }

    assert module.score_response(query_case, response) == {
        "passed": True,
        "result_count": 1,
        "missing": [],
        "search_query": "RunPod Marker warmup",
    }


def test_score_response_reports_missing_expected_text():
    module = load_module()
    scored = module.score_response(
        {"min_results": 1, "must_contain": ["Voyage"]},
        {"search_query": "embedding", "data": [{"content": [{"type": "text", "text": "OpenAI embedding proof."}]}]},
    )

    assert scored["passed"] is False
    assert scored["missing"] == ["Voyage"]
