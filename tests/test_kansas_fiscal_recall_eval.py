from __future__ import annotations

import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "scripts" / "release"
SCRIPT = RELEASE / "kansas-fiscal-recall-eval.py"
sys.path.insert(0, str(RELEASE))


def _load_module():
    spec = importlib.util.spec_from_file_location("kansas_fiscal_recall_eval", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["kansas_fiscal_recall_eval"] = module
    spec.loader.exec_module(module)
    return module


def test_fiscal_eval_requires_term_citation_and_ledger_provenance():
    module = _load_module()
    query = {"must_include_any": ["appropriation", "budget"]}
    passing = {
        "data": [
            {
                "content": "The approved budget appropriation is listed here.",
                "citation": {"url": "https://budget.kansas.gov/fy2027.pdf"},
                "attributes": {
                    "source_revision_id": "revision-1",
                    "source_identity": "logical-document-1",
                },
            }
        ]
    }

    assert module.score_result(query, passing)["passed"] is True

    no_provenance = {
        "data": [
            {
                "content": "The approved budget appropriation is listed here.",
                "citation": {"url": "https://budget.kansas.gov/fy2027.pdf"},
            }
        ]
    }
    assert module.score_result(query, no_provenance)["passed"] is False


def test_fiscal_eval_dry_run_names_all_quality_requirements():
    module = _load_module()

    proof = module.dry_run_eval()

    assert proof["passed"] is True
    assert proof["query_count"] == 5
    assert len(proof["requirements"]) == 3
