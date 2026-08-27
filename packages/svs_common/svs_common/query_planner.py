from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any


KANSAS_CIVICS_LEGAL_PROFILE_ID = "ks_civics_legal_v1"


@dataclass(frozen=True)
class QueryPlan:
    original_query: str
    effective_query: str
    subqueries: list[str]
    rewritten: bool
    filters: dict[str, Any] = field(default_factory=dict)
    profile_id: str | None = None


FILLER_PREFIX_RE = re.compile(
    r"^\s*(?:please\s+)?(?:can\s+you|could\s+you|would\s+you|tell\s+me|show\s+me|find|search\s+for|look\s+up)\b\s*",
    re.I,
)
KS_LABELED_DOCKET_RE = re.compile(r"\b(?:docket(?:\s+(?:no\.?|number))?|no\.?)\s*(\d{4,6})\b", re.I)
KS_DOCKET_RE = re.compile(r"\b(?:docket(?:\s+(?:no\.?|number))?\s*)?(?:no\.?\s*)?(\d{5,6})\b", re.I)
KS_DECISION_DATE_RE = re.compile(r"\b((?:19[8-9]\d|20\d{2})-\d{2}-\d{2})\b")
KS_DECISION_YEAR_RE = re.compile(r"\b(19[8-9]\d|20\d{2})\b")
KS_COURT_OF_APPEALS_RE = re.compile(r"\b(?:kansas\s+)?court\s+of\s+appeals\b|\bcourt\s+of\s+appeals\b", re.I)
KS_SUPREME_COURT_RE = re.compile(r"\b(?:kansas\s+)?supreme\s+court\b", re.I)
KS_UNPUBLISHED_RE = re.compile(r"\bunpublished\b", re.I)
KS_PUBLISHED_RE = re.compile(r"\bpublished\b", re.I)


def normalize_query_text(query: str) -> str:
    return re.sub(r"\s+", " ", query).strip(" \t\r\n?.!")


def rewrite_query_for_search(query: str) -> str:
    rewritten = normalize_query_text(query)
    for _ in range(4):
        next_value = FILLER_PREFIX_RE.sub("", rewritten).strip()
        if next_value == rewritten:
            break
        rewritten = next_value
    rewritten = re.sub(r"\bwhat\s+(?:was|were|is|are)\s+the\s+", "", rewritten, flags=re.I).strip()
    return normalize_query_text(rewritten) or normalize_query_text(query)


def decompose_query(query: str, *, max_subqueries: int = 4) -> list[str]:
    normalized = normalize_query_text(query)
    parts = re.split(r"\s+(?:and|also)\s+|[;?]+", normalized, flags=re.I)
    subqueries: list[str] = []
    for part in parts:
        candidate = normalize_query_text(part)
        if len(candidate.split()) >= 2 and candidate.lower() not in {q.lower() for q in subqueries}:
            subqueries.append(candidate)
        if len(subqueries) >= max_subqueries:
            break
    return subqueries or [normalized]


def merge_query_filters(base: dict[str, Any] | None, planned: dict[str, Any] | None) -> dict[str, Any]:
    merged = copy.deepcopy(base or {})
    for key, value in (planned or {}).items():
        if key == "file_attribute_filters" and isinstance(value, dict):
            target = merged.setdefault("file_attribute_filters", {})
            if not isinstance(target, dict):
                continue
            for attr_key, attr_value in value.items():
                target.setdefault(attr_key, attr_value)
            continue
        merged.setdefault(key, copy.deepcopy(value))
    return merged


def _ks_civics_file_attribute_filters(query: str) -> dict[str, str]:
    attributes: dict[str, str] = {}

    docket_match = KS_LABELED_DOCKET_RE.search(query) or KS_DOCKET_RE.search(query)
    if docket_match:
        attributes["docket_number"] = docket_match.group(1)

    date_match = KS_DECISION_DATE_RE.search(query)
    if date_match:
        decision_date = date_match.group(1)
        attributes["decision_date"] = decision_date
        attributes["decision_year"] = decision_date[:4]
    else:
        year_match = KS_DECISION_YEAR_RE.search(query)
        if year_match:
            attributes["decision_year"] = year_match.group(1)

    if KS_COURT_OF_APPEALS_RE.search(query):
        attributes["court"] = "Court of Appeals"
    elif KS_SUPREME_COURT_RE.search(query):
        attributes["court"] = "Supreme Court"

    if KS_UNPUBLISHED_RE.search(query):
        attributes["status"] = "Unpublished"
    elif KS_PUBLISHED_RE.search(query):
        attributes["status"] = "Published"

    return attributes


def _ks_civics_effective_query(query: str) -> str:
    cleaned = KS_LABELED_DOCKET_RE.sub(" ", query)
    cleaned = KS_DOCKET_RE.sub(" ", cleaned)
    cleaned = KS_DECISION_DATE_RE.sub(" ", cleaned)
    cleaned = KS_DECISION_YEAR_RE.sub(" ", cleaned)
    cleaned = KS_UNPUBLISHED_RE.sub(" ", cleaned)
    cleaned = KS_PUBLISHED_RE.sub(" ", cleaned)
    cleaned = KS_COURT_OF_APPEALS_RE.sub(" ", cleaned)
    cleaned = KS_SUPREME_COURT_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\b(?:from|in|on|decided)\s*$", " ", cleaned, flags=re.I)
    return rewrite_query_for_search(cleaned) or normalize_query_text(query)


def _plan_ks_civics_query(query: str, *, rewrite_query: bool) -> QueryPlan:
    normalized = normalize_query_text(query)
    extracted_query = _ks_civics_effective_query(normalized)
    effective = rewrite_query_for_search(extracted_query) if rewrite_query else extracted_query
    subqueries = decompose_query(effective) if rewrite_query else [effective]
    attributes = _ks_civics_file_attribute_filters(normalized)
    filters = {"file_attribute_filters": attributes} if attributes else {}
    rewritten = effective != normalized or len(subqueries) > 1 or bool(filters)
    return QueryPlan(
        original_query=query,
        effective_query=effective,
        subqueries=subqueries,
        rewritten=rewritten,
        filters=filters,
        profile_id=KANSAS_CIVICS_LEGAL_PROFILE_ID,
    )


def plan_query(query: str, *, rewrite_query: bool = False, profile_id: str | None = None) -> QueryPlan:
    if profile_id == KANSAS_CIVICS_LEGAL_PROFILE_ID:
        return _plan_ks_civics_query(query, rewrite_query=rewrite_query)
    normalized = normalize_query_text(query)
    if not rewrite_query:
        return QueryPlan(original_query=query, effective_query=normalized, subqueries=[normalized], rewritten=False, profile_id=profile_id)
    effective = rewrite_query_for_search(normalized)
    subqueries = decompose_query(effective)
    return QueryPlan(
        original_query=query,
        effective_query=effective,
        subqueries=subqueries,
        rewritten=effective != normalized or len(subqueries) > 1,
        profile_id=profile_id,
    )
