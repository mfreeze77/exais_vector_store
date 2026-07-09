from __future__ import annotations

import re
from typing import Any

INDEX_PART_RE = re.compile(r"[^a-z0-9]+")
UNDERSCORE_RE = re.compile(r"_+")


def safe_index_part(value: Any) -> str:
    """Normalize a logical index component for Qdrant/OpenSearch names."""
    safe = INDEX_PART_RE.sub("_", str(value or "").strip().lower()).strip("_")
    return UNDERSCORE_RE.sub("_", safe)


def active_index_version(settings: Any, override: str | None = None) -> str:
    value = override if override is not None else getattr(settings, "svs_index_version", "")
    return safe_index_part(value)


def index_version_suffix(settings: Any, override: str | None = None) -> str:
    version = active_index_version(settings, override)
    return f"_{version}" if version else ""
