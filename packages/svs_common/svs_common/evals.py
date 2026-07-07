from __future__ import annotations
from dataclasses import dataclass

@dataclass
class RetrievalEvalCase:
    id: str
    query: str
    expected_chunk_ids: list[str]
    forbidden_chunk_ids: list[str]
    security_level: int = 1

def recall_at_k(result_ids: list[str], expected_ids: list[str], k: int) -> float:
    if not expected_ids:
        return 1.0
    return len(set(result_ids[:k]).intersection(expected_ids)) / len(set(expected_ids))

def leakage_count(result_ids: list[str], forbidden_ids: list[str]) -> int:
    return len(set(result_ids).intersection(forbidden_ids))
