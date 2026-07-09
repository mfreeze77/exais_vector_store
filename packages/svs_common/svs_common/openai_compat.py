from __future__ import annotations

import json
import re
import secrets
from base64 import urlsafe_b64decode, urlsafe_b64encode
from hashlib import sha256
from typing import Any

from .openai_metadata import SAFE_ATTRIBUTE_KEY_RE, SENSITIVE_ATTRIBUTE_RE
from .schemas import (
    OPENAI_RESPONSES_FILE_SEARCH_DEFAULT_MAX_NUM_RESULTS,
    ChunkRecord,
    OpenAIVectorStoreSearchRequest,
)


class OpenAICompatError(ValueError):
    pass


SUPPORTED_INTERNAL_FILTER_KEYS = {"document_id", "knowledge_base_id", "classification", "acl_bucket"}
MAX_FILE_ATTRIBUTE_FILTER_ALTERNATIVES = 32
RANGE_FILTER_TYPES = {"gt", "gte", "lt", "lte"}
NEGATION_FILTER_TYPES = {"ne", "nin"}
RESPONSES_FILE_SEARCH_RESULTS_INCLUDE = "output[*].file_search_call.search_results"
RESPONSES_FILE_SEARCH_RESULTS_INCLUDE_CANONICAL = "file_search_call.results"
RESPONSES_FILE_SEARCH_RESULTS_INCLUDE_ALIASES = frozenset({
    RESPONSES_FILE_SEARCH_RESULTS_INCLUDE,
    RESPONSES_FILE_SEARCH_RESULTS_INCLUDE_CANONICAL,
    "output[*].file_search_call.results",
})
OPENAI_FILE_CITATION_KEYS = frozenset({"type", "index", "file_id", "filename"})
OPENAI_CITATION_MARKER_RE = re.compile(r"【\d+†source】")
OPENAI_MODEL_CITATION_START = "\ue200"
OPENAI_MODEL_CITATION_DELIMITER = "\ue202"
OPENAI_MODEL_CITATION_STOP = "\ue201"
OPENAI_MODEL_CITATION_SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
OPENAI_MODEL_CITATION_LINE_LOCATOR_RE = re.compile(r"^L\d+(?:-L\d+)?$")
OUTPUT_GUARD_ID = "pii_secret_citation_guard_v1"
OPENAI_VECTOR_STORE_SEARCH_PAGE_TOKEN_PREFIX = "vs_search_page_"
MAX_VECTOR_STORE_SEARCH_PAGE_OFFSET = 1000
OUTPUT_GUARD_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "private_key",
        re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?-----END [A-Z0-9 ]*PRIVATE KEY-----", re.I | re.S),
        "[REDACTED_PRIVATE_KEY]",
    ),
    ("bearer_token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/\-=]{12,}", re.I), "Bearer [REDACTED_SECRET]"),
    ("openai_api_key", re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{12,}\b"), "[REDACTED_SECRET]"),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY]"),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I), "[REDACTED_EMAIL]"),
    ("phone", re.compile(r"(?<!\w)(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}(?!\w)"), "[REDACTED_PHONE]"),
)
SECRET_ASSIGNMENT_RE = re.compile(
    r"\b(api[_-]?key|secret|token|password|passwd|pwd)\s*[:=]\s*['\"]?[^'\"\s,;]{6,}['\"]?",
    re.I,
)


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


def validate_file_attribute_filter_values(key: str, values: Any) -> list[str | int | float | bool]:
    if not isinstance(values, list) or not values:
        raise OpenAICompatError(f"file attribute {key!r} in filters require a non-empty value list")
    normalized: list[str | int | float | bool] = []
    for value in values:
        validate_file_attribute_filter(key, value)
        normalized.append(value)
    return normalized


def validate_file_attribute_range_filter(key: str, value: Any) -> dict[str, Any]:
    if not isinstance(key, str) or not SAFE_ATTRIBUTE_KEY_RE.match(key):
        raise OpenAICompatError(f"unsupported file attribute key {key!r}")
    if SENSITIVE_ATTRIBUTE_RE.search(key):
        raise OpenAICompatError(f"file attribute key {key!r} is sensitive and cannot be used for search filtering")
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise OpenAICompatError(f"file attribute {key!r} range filters require a string or number")
    return {"key": key, "value": value}


def _dedupe_file_attribute_options(options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, Any], ...]] = set()
    for option in options:
        if not option:
            continue
        key = tuple(sorted(option.items(), key=lambda item: item[0]))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(option)
    if len(deduped) > MAX_FILE_ATTRIBUTE_FILTER_ALTERNATIVES:
        raise OpenAICompatError(
            f"file attribute filters expand to more than {MAX_FILE_ATTRIBUTE_FILTER_ALTERNATIVES} alternatives"
        )
    return deduped


def _merge_file_attribute_options(
    left_options: list[dict[str, Any]],
    right_options: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for left in left_options:
        for right in right_options:
            option = dict(left)
            conflict = False
            for key, value in right.items():
                if key in option and option[key] != value:
                    conflict = True
                    break
                option[key] = value
            if not conflict:
                merged.append(option)
    if not merged:
        raise OpenAICompatError("conflicting file attribute filters")
    return _dedupe_file_attribute_options(merged)


def _file_attribute_options_from_filter(filter_value: dict[str, Any]) -> list[dict[str, Any]]:
    unsupported = [
        key
        for key in filter_value
        if key not in {"file_attribute_filters", "file_attribute_filter_any"}
    ]
    if unsupported:
        raise OpenAICompatError("or filters currently support file attribute filters only")
    base = dict(filter_value.get("file_attribute_filters") or {})
    options = [dict(option) for option in (filter_value.get("file_attribute_filter_any") or [])]
    if not options:
        return [base] if base else []
    if base:
        options = _merge_file_attribute_options([base], options)
    return options


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


def _output_guard_metadata(redactions: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not redactions:
        return None
    return {"id": OUTPUT_GUARD_ID, "redactions": redactions}


def _merge_output_guard_metadata(guards: list[dict[str, Any]]) -> dict[str, Any] | None:
    totals: dict[str, int] = {}
    for guard in guards:
        if not isinstance(guard, dict):
            continue
        for redaction in guard.get("redactions") or []:
            if not isinstance(redaction, dict):
                continue
            kind = redaction.get("type")
            count = redaction.get("count")
            if isinstance(kind, str) and isinstance(count, int):
                totals[kind] = totals.get(kind, 0) + count
    if not totals:
        return None
    return {
        "id": OUTPUT_GUARD_ID,
        "redactions": [{"type": kind, "count": totals[kind]} for kind in sorted(totals)],
    }


def output_guard_text(text: str) -> tuple[str, dict[str, Any] | None]:
    guarded = text or ""
    redactions: list[dict[str, Any]] = []
    for kind, pattern, replacement in OUTPUT_GUARD_RULES:
        guarded, count = pattern.subn(replacement, guarded)
        if count:
            redactions.append({"type": kind, "count": count})

    def replace_secret_assignment(match: re.Match[str]) -> str:
        key = match.group(1)
        return f"{key}=[REDACTED_SECRET]"

    guarded, count = SECRET_ASSIGNMENT_RE.subn(replace_secret_assignment, guarded)
    if count:
        redactions.append({"type": "secret_assignment", "count": count})
    return guarded, _output_guard_metadata(redactions)


def openai_search_options_to_search_request_kwargs(req: OpenAIVectorStoreSearchRequest) -> dict[str, Any]:
    ranking = req.ranking_options
    ranker = ranking.ranker if ranking else "auto"
    hybrid_search = ranking.hybrid_search.model_dump(exclude_none=True) if ranking and ranking.hybrid_search else None
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
                "next_page": req.next_page,
                "ranker": ranker,
                "score_threshold": ranking.score_threshold if ranking else None,
                "hybrid_search": hybrid_search,
            }
        },
    }


def encode_vector_store_search_next_page(offset: int) -> str:
    if isinstance(offset, bool) or not isinstance(offset, int) or offset <= 0:
        raise OpenAICompatError("next_page cursor offset must be a positive integer")
    if offset > MAX_VECTOR_STORE_SEARCH_PAGE_OFFSET:
        raise OpenAICompatError("next_page cursor offset exceeds the supported search window")
    payload = json.dumps({"offset": offset}, separators=(",", ":")).encode("utf-8")
    encoded = urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    return f"{OPENAI_VECTOR_STORE_SEARCH_PAGE_TOKEN_PREFIX}{encoded}"


def vector_store_search_next_page_offset(next_page: str | None) -> int:
    if next_page is None:
        return 0
    if not isinstance(next_page, str) or not next_page.strip():
        raise OpenAICompatError("next_page must be a non-empty cursor string")
    if not next_page.startswith(OPENAI_VECTOR_STORE_SEARCH_PAGE_TOKEN_PREFIX):
        raise OpenAICompatError("next_page is not a valid vector store search cursor")
    raw = next_page[len(OPENAI_VECTOR_STORE_SEARCH_PAGE_TOKEN_PREFIX):]
    padded = raw + ("=" * (-len(raw) % 4))
    try:
        decoded = json.loads(urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpenAICompatError("next_page is not a valid vector store search cursor") from exc
    offset = decoded.get("offset") if isinstance(decoded, dict) else None
    if isinstance(offset, bool) or not isinstance(offset, int) or offset <= 0:
        raise OpenAICompatError("next_page is not a valid vector store search cursor")
    if offset > MAX_VECTOR_STORE_SEARCH_PAGE_OFFSET:
        raise OpenAICompatError("next_page cursor offset exceeds the supported search window")
    return offset


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
                elif key == "file_attribute_filter_any":
                    options = [dict(option) for option in value]
                    if "file_attribute_filter_any" in merged:
                        merged["file_attribute_filter_any"] = _merge_file_attribute_options(
                            merged["file_attribute_filter_any"],
                            options,
                        )
                    else:
                        merged["file_attribute_filter_any"] = _dedupe_file_attribute_options(options)
                elif key == "file_attribute_ranges":
                    merged.setdefault("file_attribute_ranges", []).extend(value)
                elif key in {"file_attribute_not_filters", "file_attribute_not_any"}:
                    merged.setdefault(key, []).extend(value)
                else:
                    if key in merged and merged[key] != value:
                        raise OpenAICompatError(f"conflicting filters for {key}")
                    merged[key] = value
        return merged
    if kind == "or":
        children = raw_filter.get("filters")
        if not isinstance(children, list) or not children:
            raise OpenAICompatError("or filters require a non-empty filters list")
        options: list[dict[str, Any]] = []
        for child in children:
            options.extend(_file_attribute_options_from_filter(openai_filter_to_internal(child)))
        options = _dedupe_file_attribute_options(options)
        if not options:
            raise OpenAICompatError("or filters must contain file attribute comparisons")
        return {"file_attribute_filter_any": options}
    if kind not in {"eq", "in", *RANGE_FILTER_TYPES, *NEGATION_FILTER_TYPES}:
        raise OpenAICompatError(f"filter operation {kind!r} is not implemented in ExAIS yet")

    key = raw_filter.get("key")
    if "value" not in raw_filter:
        raise OpenAICompatError(f"{kind} filters require value")
    value = raw_filter["value"]
    if kind == "ne":
        if key in SUPPORTED_INTERNAL_FILTER_KEYS:
            raise OpenAICompatError("ne filters currently support file attributes only")
        validate_file_attribute_filter(key, value)
        return {"file_attribute_not_filters": [{"key": str(key), "value": value}]}
    if kind == "nin":
        if key in SUPPORTED_INTERNAL_FILTER_KEYS:
            raise OpenAICompatError("nin filters currently support file attributes only")
        values = validate_file_attribute_filter_values(key, value)
        return {"file_attribute_not_any": [{"key": str(key), "values": values}]}
    if kind in RANGE_FILTER_TYPES:
        if key in SUPPORTED_INTERNAL_FILTER_KEYS:
            raise OpenAICompatError("range filters currently support file attributes only")
        validated = validate_file_attribute_range_filter(key, value)
        return {"file_attribute_ranges": [{"key": str(validated["key"]), "op": kind, "value": validated["value"]}]}
    if kind == "in":
        if key in SUPPORTED_INTERNAL_FILTER_KEYS:
            raise OpenAICompatError("in filters currently support file attributes only")
        values = validate_file_attribute_filter_values(key, value)
        return {"file_attribute_filter_any": [{str(key): item} for item in values]}
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
    *,
    limit: int | None = None,
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
    return normalized[: (limit if limit is not None else (req.top_k or req.max_num_results))]


def vector_store_search_page_window(
    req: OpenAIVectorStoreSearchRequest,
    chunks: list[ChunkRecord],
) -> tuple[list[ChunkRecord], str | None]:
    page_size = req.top_k or req.max_num_results
    offset = vector_store_search_next_page_offset(req.next_page)
    page = chunks[offset:offset + page_size]
    next_offset = offset + page_size
    if len(chunks) > next_offset:
        return page, encode_vector_store_search_next_page(next_offset)
    return page, None


def _public_url(source_uri: str | None) -> str | None:
    if not source_uri:
        return None
    if source_uri.startswith(("http://", "https://")):
        return source_uri
    return None


def _compact_dict(raw: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in raw.items() if value is not None}


def openai_file_citation_annotation(*, file_id: str, filename: str, index: int = 0) -> dict[str, Any]:
    annotation = {
        "type": "file_citation",
        "index": index,
        "file_id": file_id,
        "filename": filename,
    }
    return validate_openai_file_citation_annotation(annotation, context="OpenAI file citation")


def openai_annotation_from_citation(citation: dict[str, Any]) -> dict[str, Any]:
    return openai_file_citation_annotation(
        file_id=str(citation["file_id"]),
        filename=str(citation["filename"]),
        index=int(citation.get("index", 0)),
    )


def openai_message_file_citation_annotation(
    *,
    annotation: dict[str, Any],
    start_index: int,
    end_index: int,
    text: str,
) -> dict[str, Any]:
    strict_annotation = validate_openai_file_citation_annotation(
        annotation,
        context="OpenAI message file citation",
    )
    for name, value in {"start_index": start_index, "end_index": end_index}.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise OpenAICompatError(f"OpenAI message file citation {name} must be a non-negative integer")
    if end_index < start_index:
        raise OpenAICompatError("OpenAI message file citation end_index must be greater than or equal to start_index")
    if not isinstance(text, str) or not text:
        raise OpenAICompatError("OpenAI message file citation text must be a non-empty string")
    if end_index != start_index + len(text):
        raise OpenAICompatError("OpenAI message file citation span must match text length")
    return {
        "type": "file_citation",
        "start_index": start_index,
        "end_index": end_index,
        "text": text,
        "file_citation": {"file_id": strict_annotation["file_id"]},
    }


def native_citation_with_openai_annotation(citation: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(citation)
    enriched["annotation"] = openai_annotation_from_citation(enriched)
    marker = enriched.get("marker")
    if isinstance(marker, str) and marker:
        start_index = enriched["annotation"]["index"]
        enriched["start_index"] = start_index
        enriched["end_index"] = start_index + len(marker)
        enriched["message_annotation"] = openai_message_file_citation_annotation(
            annotation=enriched["annotation"],
            start_index=start_index,
            end_index=enriched["end_index"],
            text=marker,
        )
    return enriched


def openai_file_citation_marker(source_number: int) -> str:
    return f"【{source_number}†source】"


def _validate_openai_model_citation_source_id(source_id: str) -> str:
    if not isinstance(source_id, str) or not OPENAI_MODEL_CITATION_SOURCE_ID_RE.fullmatch(source_id):
        raise OpenAICompatError("OpenAI model citation source_id must match [A-Za-z0-9_-]+")
    return source_id


def openai_model_citation_source_id(index: int, *, turn: int = 0, kind: str = "file") -> str:
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise OpenAICompatError("OpenAI model citation source index must be a non-negative integer")
    if isinstance(turn, bool) or not isinstance(turn, int) or turn < 0:
        raise OpenAICompatError("OpenAI model citation turn must be a non-negative integer")
    if not isinstance(kind, str) or not re.fullmatch(r"[A-Za-z]+", kind):
        raise OpenAICompatError("OpenAI model citation source kind must contain letters only")
    return f"turn{turn}{kind}{index}"


def openai_model_citation_marker(
    source_ids: str | list[str],
    *,
    locator: str | None = None,
    family: str = "cite",
) -> str:
    if not isinstance(family, str) or not OPENAI_MODEL_CITATION_SOURCE_ID_RE.fullmatch(family):
        raise OpenAICompatError("OpenAI model citation family must match [A-Za-z0-9_-]+")
    if isinstance(source_ids, str):
        normalized_ids = [source_ids]
    elif isinstance(source_ids, list):
        normalized_ids = source_ids
    else:
        raise OpenAICompatError("OpenAI model citation source_ids must be a string or list")
    if not normalized_ids:
        raise OpenAICompatError("OpenAI model citation requires at least one source_id")
    normalized_ids = [_validate_openai_model_citation_source_id(source_id) for source_id in normalized_ids]
    parts = [family, *normalized_ids]
    if locator is not None:
        if not isinstance(locator, str) or not OPENAI_MODEL_CITATION_LINE_LOCATOR_RE.fullmatch(locator):
            raise OpenAICompatError("OpenAI model citation locator must be a line range like L8-L13")
        parts.append(locator)
    return (
        OPENAI_MODEL_CITATION_START
        + OPENAI_MODEL_CITATION_DELIMITER.join(parts)
        + OPENAI_MODEL_CITATION_STOP
    )


def extract_openai_model_citations(
    text: str,
    *,
    families: tuple[str, ...] = ("cite",),
) -> list[dict[str, Any]]:
    if not isinstance(text, str):
        raise OpenAICompatError("OpenAI model citation text must be a string")
    if not families:
        return []
    for family in families:
        if not isinstance(family, str) or not OPENAI_MODEL_CITATION_SOURCE_ID_RE.fullmatch(family):
            raise OpenAICompatError("OpenAI model citation families must match [A-Za-z0-9_-]+")
    family_pattern = "|".join(re.escape(family) for family in families)
    token_re = re.compile(
        rf"{re.escape(OPENAI_MODEL_CITATION_START)}"
        rf"(?P<family>{family_pattern})"
        rf"{re.escape(OPENAI_MODEL_CITATION_DELIMITER)}"
        rf"(?P<body>.*?)"
        rf"{re.escape(OPENAI_MODEL_CITATION_STOP)}",
        re.S,
    )
    citations: list[dict[str, Any]] = []
    for match in token_re.finditer(text):
        parts = [part.strip() for part in match.group("body").split(OPENAI_MODEL_CITATION_DELIMITER)]
        parts = [part for part in parts if part]
        if not parts:
            continue
        locator = None
        if OPENAI_MODEL_CITATION_LINE_LOCATOR_RE.fullmatch(parts[-1]):
            locator = parts.pop()
        if not parts or any(OPENAI_MODEL_CITATION_SOURCE_ID_RE.fullmatch(part) is None for part in parts):
            continue
        citations.append({
            "raw": match.group(0),
            "family": match.group("family"),
            "source_ids": parts,
            "locator": locator,
            "start": match.start(),
            "end": match.end(),
        })
    return citations


def strip_openai_model_citations(text: str, citations: list[dict[str, Any]] | None = None) -> str:
    if not isinstance(text, str):
        raise OpenAICompatError("OpenAI model citation text must be a string")
    citations = citations if citations is not None else extract_openai_model_citations(text)
    clean_text = text
    for citation in sorted(citations, key=lambda item: item["start"], reverse=True):
        clean_text = clean_text[:citation["start"]] + clean_text[citation["end"]:]
    return clean_text


def validate_openai_file_citation_annotation(annotation: Any, *, context: str) -> dict[str, Any]:
    if not isinstance(annotation, dict):
        raise OpenAICompatError(f"{context} annotation must be an object")
    if set(annotation) != OPENAI_FILE_CITATION_KEYS:
        raise OpenAICompatError(f"{context} annotation must be strict OpenAI file_citation fields")
    if annotation.get("type") != "file_citation":
        raise OpenAICompatError(f"{context} annotation type must be file_citation")
    index = annotation.get("index")
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise OpenAICompatError(f"{context} annotation index must be a non-negative integer")
    if not isinstance(annotation.get("file_id"), str) or not annotation.get("file_id").strip():
        raise OpenAICompatError(f"{context} annotation file_id must be a non-empty string")
    if not isinstance(annotation.get("filename"), str) or not annotation.get("filename").strip():
        raise OpenAICompatError(f"{context} annotation filename must be a non-empty string")
    return annotation


def openai_file_citation_marker_at(text: str, index: int, *, context: str, text_label: str = "output text") -> str:
    if index < 0 or index >= len(text):
        raise OpenAICompatError(f"{context} annotation index is outside {text_label}")
    match = OPENAI_CITATION_MARKER_RE.match(text, index)
    if match is None:
        raise OpenAICompatError(f"{context} annotation index does not point at a visible source marker")
    return match.group(0)


def _text_with_openai_file_citation_marker(text: str, source_number: int) -> tuple[str, int, str]:
    marker = openai_file_citation_marker(source_number)
    if not text:
        return marker, 0, marker
    separator = "" if text[-1].isspace() else " "
    marker_index = len(text) + len(separator)
    return f"{text}{separator}{marker}", marker_index, marker


def chunk_file_citation(
    chunk: ChunkRecord,
    file_meta: dict[str, Any] | None = None,
    *,
    index: int = 0,
) -> dict[str, Any]:
    file_meta = file_meta or {}
    file_id = file_meta.get("file_id") or chunk.file_id or chunk.document_id
    filename = file_meta.get("filename") or chunk.filename or chunk.title or chunk.document_id
    title = file_meta.get("title") or chunk.title
    source_uri = file_meta.get("source_uri") or chunk.source_uri
    citation = openai_file_citation_annotation(file_id=str(file_id), filename=str(filename), index=index)
    citation.update(_compact_dict({
        "chunk_id": chunk.id,
        "document_id": chunk.document_id,
        "title": title,
        "url": _public_url(source_uri),
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "heading_path": chunk.heading_path or None,
        "score": chunk.score,
    }))
    return citation


def vector_store_search_results_page(
    req: OpenAIVectorStoreSearchRequest,
    chunks: list[ChunkRecord],
    file_lookup: dict[str, dict[str, Any]],
    *,
    search_query: str | list[str] | None = None,
    next_page: str | None = None,
) -> dict[str, Any]:
    data = []
    citations = []
    for source_number, ch in enumerate(chunks, start=1):
        file_meta = file_lookup.get(ch.document_id, {})
        attributes = dict(file_meta.get("attributes") or {}) if req.include_metadata else {}
        guarded_text, output_guard = output_guard_text(ch.text) if req.include_content else ("", None)
        citation_index = 0
        marker = None
        if req.include_content:
            guarded_text, citation_index, marker = _text_with_openai_file_citation_marker(guarded_text, source_number)
        citation = chunk_file_citation(ch, file_meta, index=citation_index)
        if marker:
            citation["marker"] = marker
        model_source_id = openai_model_citation_source_id(source_number - 1)
        citation["model_source_id"] = model_source_id
        citation["model_marker"] = openai_model_citation_marker(model_source_id)
        citation = native_citation_with_openai_annotation(citation)
        annotation = citation["annotation"]
        citations.append(citation)
        item = {
            "file_id": citation["file_id"],
            "filename": citation["filename"],
            "score": ch.score,
            "attributes": attributes,
            "content": [{"type": "text", "text": guarded_text, "annotations": [annotation]}] if req.include_content else [],
            "annotations": [annotation],
            "citation": citation,
            "citations": [citation],
        }
        if output_guard:
            item["output_guard"] = output_guard
        data.append(item)
    return {
        "object": "vector_store.search_results.page",
        "search_query": search_query or req.query,
        "data": data,
        "citations": citations,
        "has_more": next_page is not None,
        "next_page": next_page,
    }


def extract_responses_input_text(raw_input: Any) -> str:
    texts: list[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, str):
            texts.append(value)
            return
        if isinstance(value, list):
            for item in value:
                collect(item)
            return
        if not isinstance(value, dict):
            return
        content = value.get("content")
        if isinstance(content, (str, list, dict)):
            collect(content)
            return
        text_value = value.get("text")
        if isinstance(text_value, str):
            texts.append(text_value)

    collect(raw_input)
    return "\n".join(text.strip() for text in texts if text and text.strip())


def responses_input_items(raw_input: Any, *, item_id: str) -> list[dict[str, Any]]:
    def normalize_content(content: Any) -> list[dict[str, Any]]:
        if isinstance(content, str):
            return [{"type": "input_text", "text": content}]
        if isinstance(content, dict):
            content_type = content.get("type")
            if content_type and isinstance(content.get("text"), str):
                return [{"type": content_type, "text": content["text"]}]
            return []
        if isinstance(content, list):
            parts: list[dict[str, Any]] = []
            for part in content:
                if isinstance(part, str):
                    parts.append({"type": "input_text", "text": part})
                elif isinstance(part, dict):
                    copied = {key: value for key, value in part.items() if key in {"type", "text", "file_id", "filename"}}
                    if copied.get("type"):
                        parts.append(copied)
            return parts
        return []

    if isinstance(raw_input, str):
        return [{
            "id": item_id,
            "type": "message",
            "role": "user",
            "content": [{"type": "input_text", "text": raw_input}],
        }]
    if isinstance(raw_input, dict):
        raw_input = [raw_input]
    if not isinstance(raw_input, list):
        return []
    items: list[dict[str, Any]] = []
    for index, item in enumerate(raw_input):
        if not isinstance(item, dict):
            continue
        item_type = item.get("type") or "message"
        role = item.get("role") or "user"
        content = normalize_content(item.get("content"))
        if not content:
            continue
        input_item = {
            "id": item.get("id") if isinstance(item.get("id"), str) else f"{item_id}_{index}",
            "type": item_type,
            "role": role,
            "content": content,
        }
        items.append(input_item)
    return items


def responses_output_text(response: dict[str, Any]) -> str:
    if not isinstance(response, dict):
        return ""
    texts: list[str] = []
    for item in response.get("output") or []:
        if not isinstance(item, dict):
            continue
        for part in item.get("content") or []:
            if not isinstance(part, dict) or part.get("type") != "output_text":
                continue
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                visible_stripped = OPENAI_CITATION_MARKER_RE.sub("", text)
                texts.append(strip_openai_model_citations(visible_stripped).strip())
    return "\n".join(text for text in texts if text)


def responses_previous_context_text(
    response: dict[str, Any],
    input_items: list[dict[str, Any]],
    *,
    max_chars: int = 4000,
) -> str:
    if isinstance(max_chars, bool) or max_chars < 1:
        raise OpenAICompatError("previous response context max_chars must be positive")
    pieces = [
        extract_responses_input_text(input_items),
        responses_output_text(response),
    ]
    context = "\n\n".join(piece.strip() for piece in pieces if piece and piece.strip())
    if len(context) <= max_chars:
        return context
    return context[-max_chars:].lstrip()


def responses_continuation_query(current_query: str, previous_context: str | None, *, max_previous_chars: int = 4000) -> str:
    current = current_query.strip()
    previous = (previous_context or "").strip()
    if not previous:
        return current
    if isinstance(max_previous_chars, bool) or max_previous_chars < 1:
        raise OpenAICompatError("previous response context max_previous_chars must be positive")
    if len(previous) > max_previous_chars:
        previous = previous[-max_previous_chars:].lstrip()
    return f"{current}\n\n{previous}"


def response_with_file_search_include(response: dict[str, Any], *, include_search_results: bool) -> dict[str, Any]:
    copied = dict(response)
    copied["output"] = []
    for item in response.get("output") or []:
        if not isinstance(item, dict):
            continue
        output_item = dict(item)
        if output_item.get("type") == "file_search_call" and not include_search_results:
            output_item["results"] = None
            output_item["search_results"] = None
        copied["output"].append(output_item)
    return copied


def _response_stream_snapshot(response: dict[str, Any], *, status: str, output: list[dict[str, Any]] | None) -> dict[str, Any]:
    snapshot = dict(response)
    snapshot["status"] = status
    snapshot["output"] = output or []
    if status != "completed":
        snapshot["completed_at"] = None
        snapshot["usage"] = None
        snapshot.pop("citations", None)
        snapshot.pop("output_guard", None)
    return snapshot


def _response_stream_added_item(item: dict[str, Any]) -> dict[str, Any]:
    if item.get("type") == "file_search_call":
        return {
            "type": "file_search_call",
            "id": item.get("id"),
            "status": "in_progress",
            "queries": [],
            "results": None,
            "search_results": None,
        }
    added_item = dict(item)
    if "status" in added_item:
        added_item["status"] = "in_progress"
    return added_item


def openai_response_stream_events(
    response: dict[str, Any],
    *,
    include_obfuscation: bool = True,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    sequence_number = 0

    def emit(event_type: str, **payload: Any) -> None:
        nonlocal sequence_number
        sequence_number += 1
        if include_obfuscation and event_type.endswith(".delta"):
            payload.setdefault("obfuscation", secrets.token_urlsafe(16))
        events.append({"type": event_type, "sequence_number": sequence_number, **payload})

    in_progress = _response_stream_snapshot(response, status="in_progress", output=[])
    emit("response.created", response=in_progress)
    emit("response.in_progress", response=in_progress)

    output = response.get("output") or []
    for output_index, raw_item in enumerate(output):
        if not isinstance(raw_item, dict):
            continue
        item = dict(raw_item)
        item_id = str(item.get("id") or "")
        emit("response.output_item.added", output_index=output_index, item=_response_stream_added_item(item))

        if item.get("type") == "file_search_call":
            emit("response.file_search_call.in_progress", item_id=item_id, output_index=output_index)
            emit("response.file_search_call.searching", item_id=item_id, output_index=output_index)
            emit("response.file_search_call.completed", item_id=item_id, output_index=output_index)

        if item.get("type") == "message":
            for content_index, raw_part in enumerate(item.get("content") or []):
                if not isinstance(raw_part, dict):
                    continue
                part = dict(raw_part)
                if part.get("type") != "output_text":
                    emit(
                        "response.content_part.added",
                        item_id=item_id,
                        output_index=output_index,
                        content_index=content_index,
                        part=part,
                    )
                    emit(
                        "response.content_part.done",
                        item_id=item_id,
                        output_index=output_index,
                        content_index=content_index,
                        part=part,
                    )
                    continue
                text = str(part.get("text") or "")
                emit(
                    "response.content_part.added",
                    item_id=item_id,
                    output_index=output_index,
                    content_index=content_index,
                    part={"type": "output_text", "text": "", "annotations": []},
                )
                if text:
                    emit(
                        "response.output_text.delta",
                        item_id=item_id,
                        output_index=output_index,
                        content_index=content_index,
                        delta=text,
                    )
                for annotation_index, annotation in enumerate(part.get("annotations") or []):
                    emit(
                        "response.output_text.annotation.added",
                        item_id=item_id,
                        output_index=output_index,
                        content_index=content_index,
                        annotation_index=annotation_index,
                        annotation=annotation,
                    )
                emit(
                    "response.output_text.done",
                    item_id=item_id,
                    output_index=output_index,
                    content_index=content_index,
                    text=text,
                )
                emit(
                    "response.content_part.done",
                    item_id=item_id,
                    output_index=output_index,
                    content_index=content_index,
                    part=part,
                )

        emit("response.output_item.done", output_index=output_index, item=item)

    emit("response.completed", response=_response_stream_snapshot(response, status="completed", output=output))
    return events


def openai_response_sse_events(
    response: dict[str, Any],
    *,
    starting_after: int | None = None,
    include_obfuscation: bool = True,
):
    minimum_sequence = int(starting_after or 0)
    for event in openai_response_stream_events(response, include_obfuscation=include_obfuscation):
        if event["sequence_number"] <= minimum_sequence:
            continue
        yield f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False, separators=(',', ':'))}\n\n"


def responses_include_search_results(include: Any) -> bool:
    include = include or []
    if isinstance(include, str):
        include = [include]
    if not isinstance(include, list):
        raise OpenAICompatError("include must be a list")
    unsupported_include = [item for item in include if item not in RESPONSES_FILE_SEARCH_RESULTS_INCLUDE_ALIASES]
    if unsupported_include:
        raise OpenAICompatError(f"Unsupported Responses include paths: {unsupported_include}")
    return any(item in RESPONSES_FILE_SEARCH_RESULTS_INCLUDE_ALIASES for item in include)


def responses_input_items_page(
    input_items: list[dict[str, Any]],
    *,
    limit: int = 20,
    order: str = "desc",
    after: str | None = None,
) -> dict[str, Any]:
    bounded_limit = min(max(int(limit), 1), 100)
    ordered = list(input_items)
    if order == "desc":
        ordered.reverse()
    elif order != "asc":
        raise OpenAICompatError("input_items order must be 'asc' or 'desc'")
    if after:
        for index, item in enumerate(ordered):
            if item.get("id") == after:
                ordered = ordered[index + 1:]
                break
        else:
            ordered = []
    page = ordered[:bounded_limit]
    has_more = len(ordered) > bounded_limit
    return {
        "object": "list",
        "data": page,
        "first_id": page[0].get("id") if page else None,
        "last_id": page[-1].get("id") if page else None,
        "has_more": has_more,
    }


def responses_file_search_tools(raw_tools: Any) -> list[dict[str, Any]]:
    if raw_tools is None:
        return []
    if not isinstance(raw_tools, list):
        raise OpenAICompatError("tools must be a list")
    tools: list[dict[str, Any]] = []
    for index, raw_tool in enumerate(raw_tools):
        if not isinstance(raw_tool, dict):
            raise OpenAICompatError(f"tool at index {index} must be an object")
        tool_type = raw_tool.get("type")
        if tool_type != "file_search":
            raise OpenAICompatError(f"unsupported Responses tool {tool_type!r}; only file_search is implemented")
        vector_store_ids = raw_tool.get("vector_store_ids")
        if not isinstance(vector_store_ids, list) or not vector_store_ids:
            raise OpenAICompatError("file_search tools require a non-empty vector_store_ids list")
        public_ids = []
        for vector_store_id in vector_store_ids:
            if not isinstance(vector_store_id, str) or not vector_store_id:
                raise OpenAICompatError("vector_store_ids must contain non-empty strings")
            public_ids.append(vector_store_id)
        max_results = raw_tool.get("max_num_results", OPENAI_RESPONSES_FILE_SEARCH_DEFAULT_MAX_NUM_RESULTS)
        if isinstance(max_results, bool) or not isinstance(max_results, int) or max_results < 1 or max_results > 50:
            raise OpenAICompatError("file_search max_num_results must be an integer from 1 to 50")
        ranking_options = raw_tool.get("ranking_options")
        if ranking_options is not None and not isinstance(ranking_options, dict):
            raise OpenAICompatError("file_search ranking_options must be an object")
        filters = raw_tool.get("filters")
        if filters is not None and not isinstance(filters, dict):
            raise OpenAICompatError("file_search filters must be an object")
        tools.append({
            "type": "file_search",
            "vector_store_ids": public_ids,
            "filters": filters,
            "max_num_results": max_results,
            "ranking_options": ranking_options or {"ranker": "auto", "score_threshold": 0.0},
        })
    return tools


def validate_responses_file_search_tool_choice(raw_tool_choice: Any) -> None:
    if raw_tool_choice is None:
        return
    if isinstance(raw_tool_choice, str):
        if raw_tool_choice in {"auto", "required"}:
            return
        if raw_tool_choice == "none":
            raise OpenAICompatError("Responses tool_choice 'none' is incompatible with file_search citation output")
        raise OpenAICompatError("unsupported Responses tool_choice; only file_search choices are implemented")
    if not isinstance(raw_tool_choice, dict):
        raise OpenAICompatError("Responses tool_choice must be a string or object")

    choice_type = raw_tool_choice.get("type")
    if choice_type == "file_search":
        return
    if choice_type == "allowed_tools":
        mode = raw_tool_choice.get("mode")
        if mode not in {"auto", "required"}:
            raise OpenAICompatError("Responses allowed_tools tool_choice mode must be 'auto' or 'required'")
        allowed_tools = raw_tool_choice.get("tools")
        if not isinstance(allowed_tools, list) or not allowed_tools:
            raise OpenAICompatError("Responses allowed_tools tool_choice requires a non-empty tools list")
        for index, allowed_tool in enumerate(allowed_tools):
            if not isinstance(allowed_tool, dict):
                raise OpenAICompatError(f"Responses allowed_tools entry {index} must be an object")
            if allowed_tool.get("type") == "file_search":
                return
        raise OpenAICompatError("Responses allowed_tools tool_choice must include file_search for citation output")
    raise OpenAICompatError("unsupported Responses tool_choice object; only file_search choices are implemented")


def _response_token_estimate(text: str) -> int:
    return max(0, (len(text) + 3) // 4)


def _response_value_token_estimate(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        return _response_token_estimate(value)
    if isinstance(value, bool):
        return 1
    if isinstance(value, (int, float)):
        return 1
    if isinstance(value, dict):
        return sum(_response_value_token_estimate(v) for v in value.values())
    if isinstance(value, list):
        return sum(_response_value_token_estimate(v) for v in value)
    return _response_token_estimate(str(value))


def responses_input_token_count(payload: dict[str, Any]) -> int:
    if not isinstance(payload, dict):
        raise OpenAICompatError("Responses input_tokens payload must be an object")
    counted_fields = (
        "input",
        "instructions",
        "tools",
        "tool_choice",
        "text",
        "reasoning",
        "previous_response_id",
    )
    return sum(_response_value_token_estimate(payload.get(field)) for field in counted_fields)


def _responses_compact_input_items(raw_input: Any, *, item_id: str) -> list[dict[str, Any]]:
    def text_parts(content: Any) -> list[dict[str, str]]:
        if isinstance(content, str):
            return [{"type": "input_text", "text": content}]
        if isinstance(content, dict):
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                return [{"type": "input_text", "text": text}]
            return []
        if isinstance(content, list):
            parts: list[dict[str, str]] = []
            for part in content:
                if isinstance(part, str) and part.strip():
                    parts.append({"type": "input_text", "text": part})
                elif isinstance(part, dict):
                    text = part.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append({"type": "input_text", "text": text})
            return parts
        return []

    if raw_input is None:
        return []
    if isinstance(raw_input, str):
        raw_input = [{"role": "user", "content": raw_input}]
    elif isinstance(raw_input, dict):
        raw_input = [raw_input]
    elif not isinstance(raw_input, list):
        raise OpenAICompatError("Responses compact input must be a string, object, or list")

    items: list[dict[str, Any]] = []
    for index, raw_item in enumerate(raw_input):
        if isinstance(raw_item, str):
            raw_item = {"role": "user", "content": raw_item}
        if not isinstance(raw_item, dict):
            raise OpenAICompatError(f"Responses compact input item {index} must be an object")
        if raw_item.get("role", "user") != "user":
            continue
        parts = text_parts(raw_item.get("content"))
        if not parts:
            continue
        items.append({
            "id": raw_item.get("id") if isinstance(raw_item.get("id"), str) else f"{item_id}_{index}",
            "type": "message",
            "status": "completed",
            "role": "user",
            "content": parts,
        })
    return items


def responses_compact_response(
    *,
    payload: dict[str, Any],
    response_id: str,
    compaction_id: str,
    item_id: str,
    created_at: int,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise OpenAICompatError("Responses compact payload must be an object")
    model = payload.get("model")
    if not isinstance(model, str) or not model.strip():
        raise OpenAICompatError("Responses compact model must be a non-empty string")
    if payload.get("stream") not in (None, False):
        raise OpenAICompatError("Responses compact does not support streaming")
    preserved_items = _responses_compact_input_items(payload.get("input"), item_id=item_id)
    digest_payload = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    encrypted_content = f"svs_compaction_v1_{sha256(digest_payload.encode('utf-8')).hexdigest()}"
    output = [
        *preserved_items,
        {
            "id": compaction_id,
            "type": "compaction",
            "encrypted_content": encrypted_content,
        },
    ]
    input_tokens = responses_input_token_count(payload) + _response_value_token_estimate(model)
    output_tokens = _response_value_token_estimate(output)
    return {
        "id": response_id,
        "object": "response.compaction",
        "created_at": created_at,
        "output": output,
        "usage": {
            "input_tokens": input_tokens,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": output_tokens,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": input_tokens + output_tokens,
        },
    }


def _strip_result_text_citation_markers(text: str) -> str:
    return OPENAI_CITATION_MARKER_RE.sub("", text).rstrip()


def _result_text(item: dict[str, Any]) -> str:
    for content in item.get("content") or []:
        if isinstance(content, dict) and content.get("type") == "text" and isinstance(content.get("text"), str):
            return _strip_result_text_citation_markers(content["text"])
    return ""


def _response_snippet(text: str, max_chars: int = 1200) -> str:
    collapsed = re.sub(r"\s+", " ", text).strip()
    if len(collapsed) <= max_chars:
        return collapsed
    return collapsed[:max_chars].rstrip() + "..."


def _flatten_search_page_items(search_pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[tuple[Any, ...], dict[str, Any]] = {}
    unkeyed: list[dict[str, Any]] = []
    for search_page in search_pages:
        page = search_page.get("page") if isinstance(search_page.get("page"), dict) else search_page
        vector_store_id = search_page.get("vector_store_id")
        for item in page.get("data") or []:
            if not isinstance(item, dict):
                continue
            copied = dict(item)
            if vector_store_id:
                copied["vector_store_id"] = vector_store_id
            copied = _with_vector_store_ids(copied, [vector_store_id] if vector_store_id else [])
            dedupe_key = _file_search_item_dedupe_key(copied)
            if dedupe_key is None:
                unkeyed.append(copied)
                continue
            existing = deduped.get(dedupe_key)
            if existing is None:
                deduped[dedupe_key] = copied
            else:
                deduped[dedupe_key] = _merge_duplicate_search_item(existing, copied)
    items = [*deduped.values(), *unkeyed]
    return sorted(items, key=lambda item: float(item.get("score") or 0.0), reverse=True)


def _file_search_item_dedupe_key(item: dict[str, Any]) -> tuple[Any, ...] | None:
    citation = item.get("citation") if isinstance(item.get("citation"), dict) else {}
    chunk_id = citation.get("chunk_id")
    if chunk_id:
        return ("chunk", str(chunk_id))
    file_id = item.get("file_id")
    text = _result_text(item)
    if file_id and text:
        return ("file_text", str(file_id), sha256(text.encode("utf-8")).hexdigest())
    return None


def _with_vector_store_ids(item: dict[str, Any], vector_store_ids: list[Any]) -> dict[str, Any]:
    ids: list[str] = []
    raw_item_ids = item.get("vector_store_ids")
    item_ids = raw_item_ids if isinstance(raw_item_ids, list) else ([raw_item_ids] if raw_item_ids else [])
    for candidate in [*item_ids, item.get("vector_store_id"), *vector_store_ids]:
        if not candidate:
            continue
        value = str(candidate)
        if value not in ids:
            ids.append(value)
    if ids:
        item = dict(item)
        item["vector_store_ids"] = ids
        item.setdefault("vector_store_id", ids[0])
    return item


def _merge_duplicate_search_item(existing: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    existing_score = float(existing.get("score") or 0.0)
    candidate_score = float(candidate.get("score") or 0.0)
    winner = candidate if candidate_score > existing_score else existing
    merged_ids: list[str] = []
    for item in (existing, candidate):
        raw_item_ids = item.get("vector_store_ids")
        item_ids = raw_item_ids if isinstance(raw_item_ids, list) else ([raw_item_ids] if raw_item_ids else [])
        for vector_store_id in item_ids or ([item.get("vector_store_id")] if item.get("vector_store_id") else []):
            value = str(vector_store_id)
            if value not in merged_ids:
                merged_ids.append(value)
    merged = dict(winner)
    if merged_ids:
        merged["vector_store_ids"] = merged_ids
        merged.setdefault("vector_store_id", merged_ids[0])
    return merged


def _file_search_call_results(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    for item in items:
        text, _ = _guarded_result_text(item)
        result = _compact_dict({
            "file_id": item.get("file_id"),
            "filename": item.get("filename"),
            "score": item.get("score"),
            "text": text,
            "attributes": item.get("attributes") or {},
        })
        results.append(result)
    return results


def _guarded_result_text(item: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    text = _result_text(item)
    existing_guard = item.get("output_guard")
    if isinstance(existing_guard, dict):
        return text, existing_guard
    return output_guard_text(text)


def openai_responses_file_search_response(
    *,
    payload: dict[str, Any],
    query: str,
    tools: list[dict[str, Any]],
    search_pages: list[dict[str, Any]],
    response_id: str,
    message_id: str,
    file_search_call_id: str,
    created_at: int,
    include_search_results: bool = False,
    file_search_queries: list[str] | None = None,
) -> dict[str, Any]:
    items = _flatten_search_page_items(search_pages)
    annotations: list[dict[str, Any]] = []
    citations: list[dict[str, Any]] = []
    output_guards: list[dict[str, Any]] = []
    if not items:
        output_text = "No matching vector store content found."
    else:
        output_text = "Relevant vector store content:"
        source_number = 0
        for item in items:
            guarded_text, output_guard = _guarded_result_text(item)
            snippet = _response_snippet(guarded_text)
            if not snippet:
                continue
            source_number += 1
            output_text += "\n\n"
            output_text += snippet
            output_text += " "
            marker = openai_file_citation_marker(source_number)
            citation_index = len(output_text)
            output_text += marker
            citation = dict(item.get("citation") or {})
            citation.setdefault("file_id", item.get("file_id"))
            citation.setdefault("filename", item.get("filename"))
            citation["index"] = citation_index
            citation["marker"] = marker
            model_source_id = openai_model_citation_source_id(source_number - 1)
            citation["model_source_id"] = model_source_id
            citation["model_marker"] = openai_model_citation_marker(model_source_id)
            if item.get("vector_store_id"):
                citation["vector_store_id"] = item["vector_store_id"]
            if item.get("vector_store_ids"):
                citation["vector_store_ids"] = list(item["vector_store_ids"])
            if output_guard:
                output_guards.append(output_guard)
                citation["output_guard"] = output_guard
            citation = native_citation_with_openai_annotation(citation)
            annotation = citation["annotation"]
            annotations.append(annotation)
            citations.append(citation)
        if not annotations:
            output_text = "No matching vector store content found."

    file_search_call = {
        "type": "file_search_call",
        "id": file_search_call_id,
        "status": "completed",
        "queries": file_search_queries or [query],
        "results": None,
        "search_results": None,
    }
    if include_search_results:
        file_search_results = _file_search_call_results(items)
        file_search_call["results"] = file_search_results
        file_search_call["search_results"] = file_search_results

    input_tokens = _response_token_estimate(query)
    output_tokens = _response_token_estimate(output_text)
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    response = {
        "id": response_id,
        "object": "response",
        "created_at": created_at,
        "status": "completed",
        "completed_at": created_at,
        "background": bool(payload.get("background", False)),
        "error": None,
        "incomplete_details": None,
        "instructions": payload.get("instructions"),
        "max_output_tokens": payload.get("max_output_tokens"),
        "max_tool_calls": payload.get("max_tool_calls"),
        "model": payload.get("model") or "exai-vector-store-retrieval",
        "output": [
            file_search_call,
            {
                "type": "message",
                "id": message_id,
                "status": "completed",
                "role": "assistant",
                "content": [{
                    "type": "output_text",
                    "text": output_text,
                    "annotations": annotations,
                }],
            },
        ],
        "parallel_tool_calls": payload.get("parallel_tool_calls", True),
        "previous_response_id": payload.get("previous_response_id"),
        "reasoning": payload.get("reasoning") or {"effort": None, "summary": None},
        "service_tier": payload.get("service_tier", "default"),
        "store": payload.get("store", True),
        "temperature": payload.get("temperature", 1.0),
        "text": payload.get("text") or {"format": {"type": "text"}},
        "tool_choice": payload.get("tool_choice", "auto"),
        "tools": tools,
        "top_logprobs": payload.get("top_logprobs", 0),
        "top_p": payload.get("top_p", 1.0),
        "truncation": payload.get("truncation", "disabled"),
        "usage": {
            "input_tokens": input_tokens,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": output_tokens,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": input_tokens + output_tokens,
        },
        "user": payload.get("user"),
        "metadata": metadata,
        "citations": citations,
    }
    merged_guard = _merge_output_guard_metadata(output_guards)
    if merged_guard:
        response["output_guard"] = merged_guard
    return response


def _response_output_text_parts(response: dict[str, Any]):
    for output_index, item in enumerate(response.get("output") or []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for content_index, part in enumerate(item.get("content") or []):
            if isinstance(part, dict) and part.get("type") == "output_text":
                yield output_index, content_index, part


def _validate_response_file_citation_annotation(annotation: Any, *, context: str) -> dict[str, Any]:
    return validate_openai_file_citation_annotation(annotation, context=context)


def _response_annotation_marker(text: str, index: int, *, context: str) -> str:
    return openai_file_citation_marker_at(text, index, context=context)


def openai_response_citation_references(response: dict[str, Any]) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for output_index, content_index, part in _response_output_text_parts(response):
        text = part.get("text")
        part_context = f"output item {output_index} content {content_index}"
        if not isinstance(text, str):
            raise OpenAICompatError(f"{part_context} output_text text must be a string")
        annotations = part.get("annotations")
        if annotations is None:
            annotations = []
        if not isinstance(annotations, list):
            raise OpenAICompatError(f"{part_context} output_text annotations must be a list")
        annotation_marker_indexes: set[int] = set()
        for annotation_index, raw_annotation in enumerate(annotations):
            context = f"{part_context} annotation {annotation_index}"
            annotation = _validate_response_file_citation_annotation(raw_annotation, context=context)
            marker = _response_annotation_marker(text, annotation["index"], context=context)
            annotation_marker_indexes.add(annotation["index"])
            message_annotation = openai_message_file_citation_annotation(
                annotation=annotation,
                start_index=annotation["index"],
                end_index=annotation["index"] + len(marker),
                text=marker,
            )
            references.append({
                "output_index": output_index,
                "content_index": content_index,
                "annotation_index": annotation_index,
                "start_index": annotation["index"],
                "end_index": annotation["index"] + len(marker),
                "text": marker,
                "annotation": annotation,
                "message_annotation": message_annotation,
            })
        for marker_match in OPENAI_CITATION_MARKER_RE.finditer(text):
            if marker_match.start() not in annotation_marker_indexes:
                raise OpenAICompatError(
                    f"{part_context} visible source marker has no OpenAI file_citation annotation"
                )
    return references


def ensure_openai_response_citation_integrity(response: dict[str, Any]) -> None:
    output_annotations = [
        (reference["annotation"], reference["text"], reference["message_annotation"])
        for reference in openai_response_citation_references(response)
    ]

    native_citations = response.get("citations") or []
    if not native_citations:
        if output_annotations:
            raise OpenAICompatError("Responses output annotations require native citation proof")
        return
    if not isinstance(native_citations, list):
        raise OpenAICompatError("Responses native citations must be a list")
    if len(native_citations) != len(output_annotations):
        raise OpenAICompatError("Responses native citations must mirror output annotations one-to-one")
    for index, raw_citation in enumerate(native_citations):
        if not isinstance(raw_citation, dict):
            raise OpenAICompatError(f"native citation {index} must be an object")
        annotation, marker, message_annotation = output_annotations[index]
        if raw_citation.get("annotation") != annotation:
            raise OpenAICompatError(f"native citation {index} annotation does not mirror output annotation")
        if raw_citation.get("marker") != marker:
            raise OpenAICompatError(f"native citation {index} marker does not match output text")
        if (
            raw_citation.get("message_annotation") is not None
            and raw_citation.get("message_annotation") != message_annotation
        ):
            raise OpenAICompatError(f"native citation {index} message annotation does not mirror output annotation")
