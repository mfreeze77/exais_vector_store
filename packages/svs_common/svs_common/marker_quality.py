from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from html.parser import HTMLParser
from typing import Any


def normalize_text(value: str) -> str:
    value = html.unescape(unicodedata.normalize("NFKC", value))
    value = value.translate(
        str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"', "–": "-", "—": "-"})
    )
    value = value.casefold().replace("\xa0", " ").replace(",", "").replace("$", "")
    return " ".join(value.split())


def _markdown_tables(markdown: str) -> list[list[list[str]]]:
    tables: list[list[list[str]]] = []
    current: list[list[str]] = []

    def flush() -> None:
        nonlocal current
        if len(current) >= 2:
            tables.append(current)
        current = []

    for line in markdown.splitlines():
        if line.count("|") < 2:
            flush()
            continue
        stripped = line.strip().strip("|")
        cells = [
            cell.strip().replace("\\|", "|")
            for cell in re.split(r"(?<!\\)\|", stripped)
        ]
        if len(cells) < 2:
            flush()
            continue
        if all(re.fullmatch(r":?-{3,}:?", cell.replace(" ", "")) for cell in cells):
            continue
        current.append(cells)
    flush()
    return tables


class _HTMLTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table_depth = 0
        self._current_table: list[list[str]] | None = None
        self._current_row: list[str] | None = None
        self._cell_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        tag = tag.casefold()
        if tag == "table":
            self._table_depth += 1
            if self._table_depth == 1:
                self._current_table = []
        elif tag == "tr" and self._table_depth == 1:
            self._current_row = []
        elif (
            tag in {"td", "th"}
            and self._table_depth == 1
            and self._current_row is not None
        ):
            self._cell_parts = []

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"td", "th"} and self._cell_parts is not None:
            assert self._current_row is not None
            self._current_row.append(" ".join(self._cell_parts).strip())
            self._cell_parts = None
        elif tag == "tr" and self._table_depth == 1 and self._current_row is not None:
            if self._current_row:
                assert self._current_table is not None
                self._current_table.append(self._current_row)
            self._current_row = None
        elif tag == "table" and self._table_depth:
            if (
                self._table_depth == 1
                and self._current_table
                and len(self._current_table) >= 2
            ):
                self.tables.append(self._current_table)
            self._table_depth -= 1
            if self._table_depth == 0:
                self._current_table = None


def extract_tables(markdown: str) -> list[list[list[str]]]:
    parser = _HTMLTableParser()
    parser.feed(markdown)
    return _markdown_tables(markdown) + parser.tables


def summarize_markdown(markdown: str) -> dict[str, Any]:
    tables = extract_tables(markdown)
    rows = [row for table in tables for row in table]
    return {
        "marker_markdown_chars": len(markdown),
        "marker_markdown_sha256": hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
        "marker_table_count": len(tables),
        "marker_table_row_count": len(rows),
        "marker_table_cell_count": sum(len(row) for row in rows),
    }


def _contains_all(values: list[str], expected: list[str]) -> bool:
    normalized_values = [normalize_text(value) for value in values]
    return all(
        any(normalize_text(term) in value for value in normalized_values)
        for term in expected
    )


def _row_matches(row: list[str], expected: list[str]) -> bool:
    cells = [normalized for value in row if (normalized := normalize_text(value))]
    expected_cells = [normalize_text(value) for value in expected]
    return cells == expected_cells


def evaluate_profile(markdown: str, profile: dict[str, Any]) -> dict[str, Any]:
    if profile.get("schema_version") != 1:
        raise ValueError("quality profile schema_version must be 1")
    metrics = summarize_markdown(markdown)
    minimums = profile.get("minimums") or {}
    if not isinstance(minimums, dict):
        raise TypeError("quality profile minimums must be an object")
    checks: list[dict[str, Any]] = []

    for field, metric in (
        ("markdown_chars", "marker_markdown_chars"),
        ("tables", "marker_table_count"),
        ("table_rows", "marker_table_row_count"),
    ):
        expected = minimums.get(field)
        if expected is None:
            continue
        if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
            raise ValueError(f"minimums.{field} must be a non-negative integer")
        actual = metrics[metric]
        checks.append(
            {
                "id": f"minimum:{field}",
                "passed": actual >= expected,
                "expected_minimum": expected,
                "actual": actual,
            }
        )

    normalized_markdown = normalize_text(markdown)
    anchors = profile.get("required_anchors") or []
    if not isinstance(anchors, list):
        raise TypeError("quality profile required_anchors must be an array")
    for anchor in anchors:
        if not isinstance(anchor, str) or not anchor.strip():
            raise ValueError("required_anchors must contain non-empty strings")
        checks.append(
            {
                "id": f"anchor:{anchor}",
                "passed": normalize_text(anchor) in normalized_markdown,
            }
        )

    tables = extract_tables(markdown)
    table_checks = profile.get("table_checks") or []
    if not isinstance(table_checks, list):
        raise TypeError("quality profile table_checks must be an array")
    for table_check in table_checks:
        if not isinstance(table_check, dict) or not isinstance(
            table_check.get("id"), str
        ):
            raise TypeError("every table check must have a string id")
        headers = table_check.get("headers") or []
        expected_rows = table_check.get("rows") or []
        if not all(isinstance(value, str) and value for value in headers):
            raise ValueError(f"table check {table_check['id']} has invalid headers")
        if not all(
            isinstance(row, list)
            and row
            and all(isinstance(value, str) and value for value in row)
            for row in expected_rows
        ):
            raise ValueError(f"table check {table_check['id']} has invalid rows")

        matching_table = None
        for table in tables:
            if _contains_all([cell for row in table for cell in row], headers):
                matching_table = table
                break
        row_results = [
            {
                "row_id": expected[0],
                "passed": matching_table is not None
                and any(_row_matches(row, expected) for row in matching_table),
            }
            for expected in expected_rows
        ]
        matched_rows = sum(result["passed"] for result in row_results)
        checks.append(
            {
                "id": f"table:{table_check['id']}",
                "passed": matching_table is not None
                and matched_rows == len(expected_rows),
                "expected_rows": len(expected_rows),
                "matched_rows": matched_rows,
                "row_results": row_results,
            }
        )

    return {
        "passed": bool(checks) and all(check["passed"] for check in checks),
        "metrics": metrics,
        "checks": checks,
    }


__all__ = [
    "evaluate_profile",
    "extract_tables",
    "normalize_text",
    "summarize_markdown",
]
