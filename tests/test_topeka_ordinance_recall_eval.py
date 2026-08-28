from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release" / "topeka-ordinance-recall-eval.py"
sys.path.insert(0, str(SCRIPT.parent))


def load_module():
    spec = importlib.util.spec_from_file_location("topeka_ordinance_recall_eval", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["topeka_ordinance_recall_eval"] = module
    spec.loader.exec_module(module)
    return module


def test_ordinance_recall_dry_run_defines_official_pdf_queries():
    module = load_module()

    proof = module.dry_run_eval()

    assert proof["passed"] is True
    assert proof["query_count"] == 5
    expected = {case["expected_source_uri_contains"] for case in proof["queries"]}
    assert expected == {
        "Ordinance20679.pdf",
        "CharterOrdinance126.pdf",
        "Ordinance20340.pdf",
        "Ordinance20408.pdf",
        "Ordinance20407.pdf",
    }
    fire_code = next(case for case in proof["queries"] if case["id"] == "ordinance-20407-fire-code")
    assert "14.40.010" in fire_code["query"]
    assert "14.40.010" in fire_code["must_include_all"]
    assert "14.45.010" not in fire_code["query"]


def test_ordinance_recall_scores_matching_pdf_result():
    module = load_module()
    case = {
        "expected_source_collection": "topeka-ordinances",
        "expected_source_uri_contains": "CharterOrdinance126.pdf",
        "must_include_all": ["126", "hotel topeka", "8.5"],
    }
    page = {
        "data": [
            {
                "file_id": "doc_1",
                "filename": "CharterOrdinance126.md",
                "source_uri": None,
                "attributes": {
                    "source_collection": "topeka-ordinances",
                    "ordinance_number": "126",
                    "pdf_url": "https://files.topeka.gov/community/ordinances/charter/CharterOrdinance126.pdf",
                },
                "content": [{"type": "text", "text": "Hotel   Topeka rate is 8.5 percent."}],
            }
        ]
    }

    score = module.score_case(case, page)

    assert score["passed"] is True
    assert score["matches"][0]["filename"] == "CharterOrdinance126.md"


def test_ordinance_recall_rejects_codified_result_for_pdf_case():
    module = load_module()
    case = {
        "expected_source_collection": "topeka-ordinances",
        "expected_source_uri_contains": "Ordinance20679.pdf",
        "must_include_all": ["20679", "standard traffic"],
    }
    page = {
        "data": [
            {
                "file_id": "doc_2",
                "filename": "TMC-10.15.010.md",
                "source_uri": "https://topeka.municipal.codes/TMC/10.15.010",
                "attributes": {"source_collection": "topeka-codified-code"},
                "content": [{"type": "text", "text": "Standard Traffic Ordinance 20679."}],
            }
        ]
    }

    score = module.score_case(case, page)

    assert score["passed"] is False
    assert score["matches"] == []
