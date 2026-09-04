from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest
from svs_common.marker_quality import (
    evaluate_profile,
    extract_page_markers,
    extract_tables,
    summarize_markdown,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "release" / "marker-fiscal-quality-proof.py"
PROFILE = (
    REPO_ROOT
    / "instances"
    / "ks-state-civics"
    / "vector-stores"
    / "kansas-fiscal-documents"
    / "quality"
    / "fy2025-director-presentation.json"
)


def _load_script():
    spec = importlib.util.spec_from_file_location("marker_fiscal_quality_proof", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


script = _load_script()


MARKDOWN_TABLE = """
| Policy | FY24 | FY25 | FY26 |
|---|---:|---:|---:|
| Childcare Tax Credit | - | $6.0 | 6.0 |
| Total Direct State Benefit | 22.0 | 439.5 | 314.7 |
"""

HTML_TABLE = """
<table>
  <tr><th>SGF</th><th>EDIF</th></tr>
  <tr><td>FY 2025 Gov. Rec.</td><td>$41,000,000</td><td>$2,000,000</td></tr>
</table>
"""


def test_extract_tables_accepts_marker_markdown_and_html_shapes() -> None:
    tables = extract_tables(MARKDOWN_TABLE + HTML_TABLE)
    assert len(tables) == 2
    assert tables[0][-1] == ["Total Direct State Benefit", "22.0", "439.5", "314.7"]
    assert tables[1][-1] == ["FY 2025 Gov. Rec.", "$41,000,000", "$2,000,000"]


def test_summary_is_derived_from_the_same_markdown() -> None:
    markdown = MARKDOWN_TABLE + HTML_TABLE
    summary = summarize_markdown(markdown)
    assert summary["marker_markdown_chars"] == len(markdown)
    assert (
        summary["marker_markdown_sha256"]
        == hashlib.sha256(markdown.encode("utf-8")).hexdigest()
    )
    assert summary["marker_table_count"] == 2
    assert summary["marker_table_row_count"] == 5
    assert summary["marker_table_cell_count"] == 17
    assert summary["marker_page_marker_count"] == 0
    assert summary["marker_page_marker_first"] is None
    assert summary["marker_page_marker_last"] is None
    assert summary["marker_page_marker_sequence_complete"] is False


def test_page_markers_accept_marker_pagination_and_legacy_comments() -> None:
    markdown = (
        "{0}" + "-" * 48 + "\nfirst\n"
        "<!-- page: 7 -->\nlegacy\n"
        "{1}" + "-" * 48 + "\nsecond\n"
    )
    assert extract_page_markers(markdown) == [0, 7, 1]


def test_profile_requires_values_to_remain_on_their_source_row() -> None:
    profile = {
        "schema_version": 1,
        "minimums": {"tables": 1},
        "required_anchors": ["Childcare Tax Credit"],
        "table_checks": [
            {
                "id": "tax",
                "headers": ["Policy", "FY25"],
                "rows": [["Childcare Tax Credit", "-", "6.0", "6.0"]],
            }
        ],
    }
    assert evaluate_profile(MARKDOWN_TABLE, profile)["passed"] is True

    broken = MARKDOWN_TABLE.replace(
        "| Childcare Tax Credit | - | $6.0 | 6.0 |",
        "| Childcare Tax Credit | - | - | - |\n| unrelated | - | $6.0 | 6.0 |",
    )
    result = evaluate_profile(broken, profile)
    assert result["passed"] is False
    assert next(check for check in result["checks"] if check["id"] == "table:tax") == {
        "id": "table:tax",
        "passed": False,
        "expected_rows": 1,
        "matched_rows": 0,
        "row_results": [{"row_id": "Childcare Tax Credit", "passed": False}],
    }


def test_profile_does_not_accept_a_numeric_substring_as_an_exact_value() -> None:
    profile = {
        "schema_version": 1,
        "table_checks": [
            {
                "id": "exact-amount",
                "headers": ["Policy", "FY25"],
                "rows": [["Childcare Tax Credit", "6.0"]],
            }
        ],
    }
    altered = MARKDOWN_TABLE.replace("$6.0", "$16.0")
    result = evaluate_profile(altered, profile)
    assert result["passed"] is False
    assert result["checks"][0]["matched_rows"] == 0


def test_committed_fiscal_profile_is_hash_pinned_and_has_three_table_checks() -> None:
    assert hashlib.sha256(PROFILE.read_bytes()).hexdigest() == (
        "c7d024d803c7e0feb685569a1eac786a622ade2445fb740a42e9d4b4968b53f0"
    )
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    assert profile["schema_version"] == 1
    assert profile["document"]["sha256"] == (
        "8cc58bf8da72e204c2966fb7e8c1034aca334cbcf7b0f68a8ec4e701eea4c717"
    )
    assert len(profile["table_checks"]) == 3
    assert all(check["rows"] for check in profile["table_checks"])


def test_quality_proof_refuses_a_different_pdf_before_marker(tmp_path: Path) -> None:
    profile = json.loads(PROFILE.read_text(encoding="utf-8"))
    path = tmp_path / profile["document"]["filename"]
    path.write_bytes(b"%PDF-1.7\nnot the pinned source")
    with pytest.raises(ValueError, match="SHA-256"):
        script.validate_source(path, profile)


def test_quality_proof_refuses_a_changed_profile(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    path.write_text('{"schema_version": 1}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="profile SHA-256"):
        script.load_profile(path, "0" * 64)


def test_quality_proof_writes_atomically(tmp_path: Path) -> None:
    destination = tmp_path / "proof" / "quality.json"
    script.write_json_atomic(destination, {"passed": True})
    assert json.loads(destination.read_text(encoding="utf-8")) == {"passed": True}
    assert not list(destination.parent.glob(".tmp-marker-quality-*"))
