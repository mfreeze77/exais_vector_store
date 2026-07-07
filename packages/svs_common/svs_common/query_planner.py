from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class QueryPlan:
    original_query: str
    effective_query: str
    subqueries: list[str]
    rewritten: bool


FILLER_PREFIX_RE = re.compile(
    r"^\s*(?:please\s+)?(?:can\s+you|could\s+you|would\s+you|tell\s+me|show\s+me|find|search\s+for|look\s+up)\b\s*",
    re.I,
)


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


def plan_query(query: str, *, rewrite_query: bool = False) -> QueryPlan:
    normalized = normalize_query_text(query)
    if not rewrite_query:
        return QueryPlan(original_query=query, effective_query=normalized, subqueries=[normalized], rewritten=False)
    effective = rewrite_query_for_search(normalized)
    subqueries = decompose_query(effective)
    return QueryPlan(original_query=query, effective_query=effective, subqueries=subqueries, rewritten=effective != normalized or len(subqueries) > 1)
