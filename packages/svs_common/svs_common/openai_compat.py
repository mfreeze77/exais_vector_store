from __future__ import annotations

import re
from hashlib import sha256
from typing import Any

from .schemas import ChunkRecord, OpenAIVectorStoreSearchRequest


class OpenAICompatError(ValueError):
    pass


SUPPORTED_INTERNAL_FILTER_KEYS = {"document_id", "knowledge_base_id", "classification", "acl_bucket"}
SENSITIVE_ATTRIBUTE_RE = re.compile(r"(api[_-]?key|authorization|bearer|secret|token|password|credential)", re.I)
SAFE_ATTRIBUTE_KEY_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


def validate_file_attribute_filter(key: str, value: Any) -> None:
    if not isinstance(key, str) or not SAFE_ATTRIBUTE_KEY_RE.match(key):
        raise OpenAICompatError(f"unsupported file attribute key {key!r}")
    if SENSITIVE_ATTRIBUTE_RE.search(key):
        raise OpenAICompatError(f"file attribute key {key!r} is sensitive and cannot be used for search filtering")
    if not isinstance(value, (str, int, float, bool)):
        raise OpenAICompatError(f"file attribute {key!r} must compare against a string, number, or boolean")


def validate_filter_value(key: str, value: Any) -> None:
    if not isinstance(value, (str, int, float, bool)):
        raise OpenAICompatError(f"filter {key!r} must compare against a string, number, or boolean")


def file_attribute_payload_key(key: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", key).strip("_").lower()
    digest = sha256(key.encode("utf-8")).hexdigest()[:10]
    return f"file_attr_{safe[:48]}_{digest}"


def safe_file_attributes(attributes: dict[str, Any] | None) -> dict[str, str | int | float | bool]:
    safe: dict[str, str | int | float | bool] = {}
    for key, value in (attributes or {}).items():
        if not isinstance(value, (str, int, float, bool)):
            continue
        try:
            validate_file_attribute_filter(str(key), value)
        except OpenAICompatError:
            continue
        safe[str(key)] = value
    return safe


def file_attribute_payload(attributes: dict[str, Any] | None) -> dict[str, Any]:
    return {file_attribute_payload_key(key): value for key, value in safe_file_attributes(attributes).items()}


def openai_search_options_to_search_request_kwargs(req: OpenAIVectorStoreSearchRequest) -> dict[str, Any]:
    ranking = req.ranking_options
    ranker = ranking.ranker if ranking else "auto"
    return {
        "query": req.query,
        "top_k": req.top_k or req.max_num_results,
        "retrieval_profile_id": req.retrieval_profile_id,
        "mode": req.mode,
        "include_content": req.include_content,
        "include_metadata": req.include_metadata,
        "filters": openai_filter_to_internal(req.filters or req.attribute_filter),
        "search_metadata": {
            "openai_compat": {
                "requested_max_num_results": req.max_num_results,
                "top_k_alias": req.top_k,
                "rewrite_query": req.rewrite_query,
                "ranker": ranker,
                "score_threshold": ranking.score_threshold if ranking else None,
            }
        },
    }


def openai_filter_to_internal(raw_filter: dict[str, Any] | None) -> dict[str, Any]:
    if not raw_filter:
        return {}
    if not isinstance(raw_filter, dict):
        raise OpenAICompatError("filters must be an object")

    if "type" not in raw_filter:
        internal = {k: v for k, v in raw_filter.items() if k in SUPPORTED_INTERNAL_FILTER_KEYS}
        file_attrs = {k: v for k, v in raw_filter.items() if k not in SUPPORTED_INTERNAL_FILTER_KEYS}
        for key, value in internal.items():
            validate_filter_value(str(key), value)
        for key, value in file_attrs.items():
            validate_file_attribute_filter(key, value)
        if file_attrs:
            internal["file_attribute_filters"] = dict(file_attrs)
        return internal

    kind = str(raw_filter.get("type") or "").lower()
    if kind == "and":
        merged: dict[str, Any] = {}
        children = raw_filter.get("filters")
        if not isinstance(children, list) or not children:
            raise OpenAICompatError("and filters require a non-empty filters list")
        for child in children:
            child_filter = openai_filter_to_internal(child)
            for key, value in child_filter.items():
                if key == "file_attribute_filters":
                    merged_attrs = merged.setdefault("file_attribute_filters", {})
                    for attr_key, attr_value in value.items():
                        if attr_key in merged_attrs and merged_attrs[attr_key] != attr_value:
                            raise OpenAICompatError(f"conflicting file attribute filters for {attr_key}")
                        merged_attrs[attr_key] = attr_value
                else:
                    if key in merged and merged[key] != value:
                        raise OpenAICompatError(f"conflicting filters for {key}")
                    merged[key] = value
        return merged
    if kind == "or":
        raise OpenAICompatError("or filters are not implemented in ExAIS yet")
    if kind != "eq":
        raise OpenAICompatError(f"filter operation {kind!r} is not implemented in ExAIS yet")

    key = raw_filter.get("key")
    if "value" not in raw_filter:
        raise OpenAICompatError("eq filters require value")
    value = raw_filter["value"]
    if key in SUPPORTED_INTERNAL_FILTER_KEYS:
        validate_filter_value(str(key), value)
        return {str(key): value}
    validate_file_attribute_filter(key, value)
    return {"file_attribute_filters": {str(key): value}}


def merge_chunk_results(result_lists: list[list[ChunkRecord]], limit: int) -> list[ChunkRecord]:
    scores: dict[str, float] = {}
    chunks: dict[str, ChunkRecord] = {}
    for result_list in result_lists:
        for rank, chunk in enumerate(result_list, start=1):
            base = float(chunk.score or 0.0)
            scores[chunk.id] = scores.get(chunk.id, 0.0) + base + (1.0 / (60 + rank))
            chunks.setdefault(chunk.id, chunk)
    ordered = sorted(scores, key=lambda chunk_id: scores[chunk_id], reverse=True)
    return [chunks[chunk_id].model_copy(update={"score": scores[chunk_id]}) for chunk_id in ordered[:limit]]


def apply_openai_ranking_options(
    req: OpenAIVectorStoreSearchRequest,
    chunks: list[ChunkRecord],
) -> list[ChunkRecord]:
    if not chunks:
        return []
    max_score = max(float(ch.score or 0.0) for ch in chunks)
    normalized: list[ChunkRecord] = []
    for ch in chunks:
        raw = float(ch.score or 0.0)
        score = raw / max_score if max_score > 0 else 0.0
        normalized.append(ch.model_copy(update={"score": round(max(0.0, min(score, 1.0)), 6)}))
    threshold = req.ranking_options.score_threshold if req.ranking_options else None
    if threshold is not None:
        normalized = [ch for ch in normalized if float(ch.score or 0.0) >= threshold]
    return normalized[: (req.top_k or req.max_num_results)]


def vector_store_search_results_page(
    req: OpenAIVectorStoreSearchRequest,
    chunks: list[ChunkRecord],
    file_lookup: dict[str, dict[str, Any]],
    *,
    search_query: str | None = None,
) -> dict[str, Any]:
    data = []
    for ch in chunks:
        file_meta = file_lookup.get(ch.document_id, {})
        attributes = dict(file_meta.get("attributes") or {}) if req.include_metadata else {}
        item = {
            "file_id": file_meta.get("file_id") or ch.document_id,
            "filename": file_meta.get("filename"),
            "score": ch.score,
            "attributes": attributes,
            "content": [{"type": "text", "text": ch.text}] if req.include_content else [],
        }
        data.append(item)
    return {
        "object": "vector_store.search_results.page",
        "search_query": search_query or req.query,
        "data": data,
        "has_more": False,
        "next_page": None,
    }
