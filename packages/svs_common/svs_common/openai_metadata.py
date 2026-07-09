from __future__ import annotations

import math
import re
from typing import Any

OPENAI_METADATA_MAX_PAIRS = 16
OPENAI_METADATA_KEY_MAX_LENGTH = 64
OPENAI_METADATA_STRING_VALUE_MAX_LENGTH = 512
OPENAI_VECTOR_STORE_RESERVED_METADATA_KEYS = frozenset({"_openai_description", "_openai_chunking_strategy"})

SENSITIVE_ATTRIBUTE_RE = re.compile(r"(api[_-]?key|authorization|bearer|secret|token|password|credential)", re.I)
SAFE_ATTRIBUTE_KEY_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


def _validate_key(key: Any, *, context: str, safe_keys: bool, reserved_keys: frozenset[str]) -> str:
    if not isinstance(key, str) or not key:
        raise ValueError(f"{context} keys must be non-empty strings")
    if len(key) > OPENAI_METADATA_KEY_MAX_LENGTH:
        raise ValueError(f"{context} key {key!r} exceeds {OPENAI_METADATA_KEY_MAX_LENGTH} characters")
    if key in reserved_keys:
        raise ValueError(f"{context} key {key!r} is reserved for ExAIS internal state")
    if safe_keys and not SAFE_ATTRIBUTE_KEY_RE.match(key):
        raise ValueError(f"unsupported file attribute key {key!r}")
    if safe_keys and SENSITIVE_ATTRIBUTE_RE.search(key):
        raise ValueError(f"file attribute key {key!r} is sensitive and cannot be stored for search filtering")
    return key


def _validate_value(
    key: str,
    value: Any,
    *,
    context: str,
    allow_numbers: bool,
    allow_booleans: bool,
) -> str | int | float | bool:
    if isinstance(value, str):
        if len(value) > OPENAI_METADATA_STRING_VALUE_MAX_LENGTH:
            raise ValueError(
                f"{context} value for {key!r} exceeds {OPENAI_METADATA_STRING_VALUE_MAX_LENGTH} characters"
            )
        return value
    if isinstance(value, bool):
        if allow_booleans:
            return value
        raise ValueError(f"{context} value for {key!r} must be a string")
    if isinstance(value, (int, float)):
        if not allow_numbers:
            raise ValueError(f"{context} value for {key!r} must be a string")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError(f"{context} value for {key!r} must be a finite number")
        return value
    if allow_numbers or allow_booleans:
        raise ValueError(f"{context} value for {key!r} must be a string, number, or boolean")
    raise ValueError(f"{context} value for {key!r} must be a string")


def validate_openai_metadata_map(
    raw: Any | None,
    *,
    context: str,
    allow_numbers: bool,
    allow_booleans: bool,
    safe_keys: bool = False,
    reserved_keys: frozenset[str] = frozenset(),
) -> dict[str, str | int | float | bool]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{context} must be an object")
    if len(raw) > OPENAI_METADATA_MAX_PAIRS:
        raise ValueError(f"{context} cannot exceed {OPENAI_METADATA_MAX_PAIRS} key-value pairs")
    normalized: dict[str, str | int | float | bool] = {}
    for raw_key, raw_value in raw.items():
        key = _validate_key(raw_key, context=context, safe_keys=safe_keys, reserved_keys=reserved_keys)
        normalized[key] = _validate_value(
            key,
            raw_value,
            context=context,
            allow_numbers=allow_numbers,
            allow_booleans=allow_booleans,
        )
    return normalized


def validate_openai_metadata(
    raw: Any | None,
    *,
    context: str = "metadata",
    reserved_keys: frozenset[str] = OPENAI_VECTOR_STORE_RESERVED_METADATA_KEYS,
) -> dict[str, str]:
    return {
        key: str(value)
        for key, value in validate_openai_metadata_map(
            raw,
            context=context,
            allow_numbers=False,
            allow_booleans=False,
            reserved_keys=reserved_keys,
        ).items()
    }


def validate_openai_file_attributes(
    raw: Any | None,
    *,
    context: str = "attributes",
    reserved_keys: frozenset[str] = frozenset(),
) -> dict[str, str | int | float | bool]:
    return validate_openai_metadata_map(
        raw,
        context=context,
        allow_numbers=True,
        allow_booleans=True,
        safe_keys=True,
        reserved_keys=reserved_keys,
    )
