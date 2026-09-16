"""Spend-cap enforcement for the paid extraction path.

A cap that is described in a plan but not enforced at the call site is not a
cap. These tests cover the refusal boundary, because that is the only part that
costs money when it is wrong.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "release"))

from extraction_budget import Budget, estimate_for, pdf_page_estimate  # noqa: E402


def test_a_document_that_does_not_fit_is_refused_not_truncated():
    budget = Budget(max_pages=10)
    assert budget.admit("a", 6) is True
    assert budget.admit("b", 6) is False, "6 + 6 > 10"
    assert budget.admitted_pages == 6
    assert budget.pages_remaining == 4
    assert "page cap would be exceeded" in budget.refused[0]["reason"]


def test_a_document_that_exactly_fills_the_budget_is_admitted():
    budget = Budget(max_pages=10)
    assert budget.admit("a", 10) is True
    assert budget.pages_remaining == 0
    assert budget.admit("b", 1) is False


def test_the_document_cap_bounds_a_wrong_page_estimate():
    budget = Budget(max_pages=1000, max_documents=2)
    assert budget.admit("a", 1) is True
    assert budget.admit("b", 1) is True
    assert budget.admit("c", 1) is False
    assert "document cap reached" in budget.refused[0]["reason"]


def test_an_unenforced_budget_says_so():
    budget = Budget.unlimited()
    assert budget.enforced is False
    assert budget.as_dict()["enforced"] is False
    assert budget.admit("anything", 10_000) is True


def test_a_budget_reports_what_it_refused():
    budget = Budget(max_pages=5)
    budget.admit("a", 5)
    budget.admit("b", 3, basis="page_tree_count")
    payload = budget.as_dict()
    assert payload["admitted_document_count"] == 1
    assert payload["refused_count"] == 1
    assert payload["refused"][0]["document"] == "b"
    assert payload["refused"][0]["basis"] == "page_tree_count"


def test_page_estimate_reports_its_basis():
    pages, basis = pdf_page_estimate(b"%PDF-1.4 /Type /Pages /Count 7 >> /Type /Page ")
    assert pages == 7 and basis == "page_tree_count"
    pages, basis = pdf_page_estimate(b"%PDF-1.4 /Type /Page x /Type /Page y")
    assert pages == 2 and basis == "page_object_scan"
    pages, basis = pdf_page_estimate(b"%PDF-1.4 " + b"\x00" * 90_000)
    assert basis == "byte_size_heuristic" and pages >= 1


def test_a_non_pdf_is_not_billable(tmp_path):
    path = tmp_path / "x.docx"
    path.write_bytes(b"PK\x03\x04")
    assert estimate_for(path) == (0, "not_billable")


def test_the_plan_and_the_extractor_share_one_estimator():
    """A cap computed against one number and enforced against another is not a cap."""
    import importlib.util

    def load(name: str):
        path = ROOT / "scripts" / "release" / name
        spec = importlib.util.spec_from_file_location(name.replace("-", "_").replace(".py", ""), path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    plan = load("topeka-extraction-plan.py")
    assert plan.pdf_page_estimate is pdf_page_estimate


# --------------------------------------------------------------------------
# the refusal must reach the report
# --------------------------------------------------------------------------

import importlib.util  # noqa: E402


def _extractor():
    path = ROOT / "scripts" / "release" / "topeka-ordinance-pdf-extract.py"
    spec = importlib.util.spec_from_file_location("topeka_ordinance_pdf_extract", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_a_fully_refused_run_is_not_reported_as_complete():
    """The reviewer's probe: status complete, selected_count 0, no trace of the cap."""
    extractor = _extractor()
    budget = Budget(max_pages=1)
    assert budget.admit("over-budget-doc", 40) is False

    report = extractor.build_report(
        manifest_path=Path("m.jsonl"), extracted_dir=Path("x"),
        selected_count=0, results=[], dry_run=False,
        budget=budget, requested_count=1,
    )
    assert report["status"] == "capped", "a capped run must not read as complete"
    assert report["refused_by_budget_count"] == 1
    assert report["requested_count"] == 1
    assert report["budget"]["refused_count"] == 1
    assert "refused by the spend cap" in report["remaining_after_cap"]


def test_a_partially_refused_run_reports_both_halves():
    extractor = _extractor()
    budget = Budget(max_pages=10)
    assert budget.admit("fits", 10) is True
    assert budget.admit("does-not", 5) is False

    report = extractor.build_report(
        manifest_path=Path("m.jsonl"), extracted_dir=Path("x"),
        selected_count=1, results=[{"status": "extracted", "index": 1}], dry_run=False,
        budget=budget, requested_count=2,
    )
    assert report["status"] == "capped"
    assert report["result_count"] == 1
    assert report["refused_by_budget_count"] == 1
    assert report["budget"]["reserved_page_estimate"] == 10


def test_an_uncapped_complete_run_still_reports_complete():
    extractor = _extractor()
    report = extractor.build_report(
        manifest_path=Path("m.jsonl"), extracted_dir=Path("x"),
        selected_count=1, results=[{"status": "extracted", "index": 1}], dry_run=False,
        budget=Budget.unlimited(), requested_count=1,
    )
    assert report["status"] == "complete"
    assert report["refused_by_budget_count"] == 0
    assert report["budget"]["enforced"] is False


# --------------------------------------------------------------------------
# retries and money
# --------------------------------------------------------------------------

def test_the_cap_reserves_every_attempt_not_just_the_first():
    """The provider bills per attempt, so one document can cost attempts x pages."""
    budget = Budget(max_pages=10, attempts=3)
    assert budget.admit("a", 4) is False, "4 pages x 3 attempts = 12 > 10"
    assert budget.admit("b", 3) is True, "3 x 3 = 9 fits"
    assert budget.admitted_pages == 9
    assert budget.admitted[0]["worst_case_pages"] == 9


def test_a_single_attempt_budget_charges_pages_once():
    budget = Budget(max_pages=10, attempts=1)
    assert budget.admit("a", 10) is True
    assert budget.admitted_pages == 10


def test_a_monetary_cap_is_denominated_in_currency():
    budget = Budget(max_spend=0.05, unit_price_per_page=0.004)
    assert budget.admit("a", 12) is True, "12 x 0.004 = 0.048"
    assert budget.admit("b", 1) is False, "0.052 > 0.05"
    assert budget.admitted_spend == pytest.approx(0.048)
    assert "spend cap would be exceeded" in budget.refused[0]["reason"]


def test_a_spend_cap_without_a_price_refuses_rather_than_passing_everything():
    budget = Budget(max_spend=100.0)
    assert budget.admit("a", 1) is False
    assert "needs unit_price_per_page" in budget.refused[0]["reason"]


def test_retries_and_money_compose():
    budget = Budget(max_spend=0.10, unit_price_per_page=0.01, attempts=2)
    assert budget.admit("a", 4) is True, "4 x 2 x 0.01 = 0.08"
    assert budget.admit("b", 2) is False, "would reach 0.12"
    assert budget.as_dict()["attempts_charged_per_document"] == 2


# --------------------------------------------------------------------------
# the wiring, not just the class
# --------------------------------------------------------------------------

def _run_extract_rows(monkeypatch, tmp_path, *, client_max_attempts, cli_attempts, max_pages):
    """Drive extract_rows the way the command does, with a stub client."""
    import asyncio

    extractor = _extractor()
    pdf = tmp_path / "raw" / "pdfs" / "20407.pdf"
    pdf.parent.mkdir(parents=True)
    # 5 pages by the page-tree reading.
    pdf.write_bytes(b"%PDF-1.4 /Type /Pages /Count 5 >> " + b"/Type /Page x " * 5)
    manifest = tmp_path / "manifests" / "ordinances.jsonl"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({
        "id": "topeka-ordinance:a", "ordinance_number": "20407", "category": "ordinance",
        "pdf_url": "https://files.topeka.gov/community/ordinances/2023/Ordinance20407.pdf",
        "saved_path": "raw/pdfs/20407.pdf", "sha256": "0" * 64,
    }) + "\n", encoding="utf-8")

    class StubClient:
        max_attempts = client_max_attempts

    rows = [json.loads(line) for line in manifest.read_text().splitlines() if line.strip()]
    budget = Budget(max_pages=max_pages)
    report = asyncio.run(extractor.extract_rows(
        rows,
        manifest_path=manifest,
        extracted_dir=tmp_path / "extracted",
        pdf_dir=None,
        output_manifest=tmp_path / "out.jsonl",
        report_path=tmp_path / "report.json",
        offset=0, limit=0, concurrency=1,
        client=StubClient(),
        dry_run=True,
        # These assertions are about admission, not extraction; the stub client
        # cannot extract, and a failure there must not mask the budget result.
        allow_failures=True,
        attempts=cli_attempts,
        budget=budget,
    ))
    return budget, report


def test_the_budget_reserves_the_attempts_the_client_will_actually_make(monkeypatch, tmp_path):
    """Budget default 1 vs client default 2 let a 10-page admission bill 20."""
    budget, report = _run_extract_rows(
        monkeypatch, tmp_path, client_max_attempts=2, cli_attempts=None, max_pages=10,
    )
    assert budget.attempts == 2, "the budget must take the client's resolved retry setting"
    # 5 pages x 2 attempts = 10, which exactly fills a 10-page cap.
    assert budget.admitted_pages == 10
    assert report["refused_by_budget_count"] == 0


def test_a_client_that_retries_more_shrinks_what_the_same_cap_admits(tmp_path):
    budget, report = _run_extract_rows(
        None, tmp_path, client_max_attempts=3, cli_attempts=None, max_pages=10,
    )
    assert budget.attempts == 3
    # 5 x 3 = 15 > 10, so the one document is refused.
    assert budget.admitted_pages == 0
    assert report["refused_by_budget_count"] == 1
    assert report["status"] in {"capped", "pending"}


def test_an_explicit_attempts_flag_overrides_the_client_default(tmp_path):
    budget, _ = _run_extract_rows(
        None, tmp_path, client_max_attempts=5, cli_attempts=1, max_pages=10,
    )
    assert budget.attempts == 1, "--attempts is what the client will be told to use"
    assert budget.admitted_pages == 5


def test_the_client_default_is_not_one():
    """If this ever becomes 1, the earlier mismatch stops being possible --
    and this test should be the thing that notices."""
    from svs_common.marker_client import DEFAULT_MARKER_MAX_ATTEMPTS

    assert DEFAULT_MARKER_MAX_ATTEMPTS >= 1
    assert DEFAULT_MARKER_MAX_ATTEMPTS == 2, (
        "the budget derives attempts from the client at runtime, so this is a "
        "notification that the provider default moved, not a constraint"
    )


def test_a_client_without_a_declared_retry_setting_falls_back_to_the_library_default(tmp_path):
    """Never to 1: under-reserving is the failure that costs money."""
    from svs_common.marker_client import DEFAULT_MARKER_MAX_ATTEMPTS

    class ClientWithoutTheAttribute:
        pass

    extractor = _extractor()
    import asyncio

    pdf = tmp_path / "raw" / "pdfs" / "20407.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.4 /Type /Pages /Count 5 >> " + b"/Type /Page x " * 5)
    manifest = tmp_path / "manifests" / "ordinances.jsonl"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({
        "id": "topeka-ordinance:a", "ordinance_number": "20407", "category": "ordinance",
        "pdf_url": "https://files.topeka.gov/x.pdf", "saved_path": "raw/pdfs/20407.pdf",
        "sha256": "0" * 64,
    }) + "\n", encoding="utf-8")

    budget = Budget(max_pages=1)
    asyncio.run(extractor.extract_rows(
        [json.loads(line) for line in manifest.read_text().splitlines() if line.strip()],
        manifest_path=manifest, extracted_dir=tmp_path / "e", pdf_dir=None,
        output_manifest=tmp_path / "o.jsonl", report_path=tmp_path / "r.json",
        offset=0, limit=0, concurrency=1, client=ClientWithoutTheAttribute(),
        dry_run=True, allow_failures=True, budget=budget,
    ))
    assert budget.attempts == DEFAULT_MARKER_MAX_ATTEMPTS
