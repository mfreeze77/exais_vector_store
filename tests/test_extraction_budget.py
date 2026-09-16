"""Spend-cap enforcement for the paid extraction path.

A cap that is described in a plan but not enforced at the call site is not a
cap. These tests cover the refusal boundary, because that is the only part that
costs money when it is wrong.
"""
from __future__ import annotations

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
