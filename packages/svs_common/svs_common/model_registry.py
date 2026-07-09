from __future__ import annotations
from functools import lru_cache
import os
from pathlib import Path
from typing import Any
import yaml

CONFIG_DIR = Path(os.getenv("SVS_CONFIG_DIR") or ("configs" if Path("configs").exists() else "/app/configs"))
ONE_MILLION_TOKENS = 1_000_000

def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}

@lru_cache
def vectorization_modes() -> dict[str, Any]:
    return _load(CONFIG_DIR / "vectorization-modes.yaml").get("modes", {})

@lru_cache
def model_registry() -> dict[str, Any]:
    return _load(CONFIG_DIR / "model-registry.yaml")

@lru_cache
def retrieval_profiles() -> dict[str, Any]:
    return _load(CONFIG_DIR / "retrieval-profiles.yaml").get("profiles", {})

def select_mode(filename: str | None, mime_type: str | None, requested_mode: str | None, metadata: dict | None = None) -> str:
    if requested_mode and requested_mode != "auto_detect_v1":
        return requested_mode
    metadata = metadata or {}
    name, mime = (filename or "").lower(), (mime_type or "").lower()
    if name.endswith(".md") and metadata.get("source_pdf_id"):
        return "pdf_markdown_external_v1"
    if name.endswith(".md") or mime in {"text/markdown", "text/x-markdown"}:
        return "markdown_docs_v1"
    if name.endswith(".pdf") or mime == "application/pdf":
        return "raw_pdf_research_v1"
    if name.endswith((".py", ".ts", ".tsx", ".js", ".java", ".go", ".rs", ".cs", ".php")):
        return "code_repo_v1"
    if name.endswith((".csv", ".tsv", ".json", ".jsonl")) or mime in {"text/csv", "text/tab-separated-values", "application/json", "application/jsonl", "application/x-ndjson"}:
        return "tables_csv_json_v1"
    if name.endswith((".log", ".logs", ".err", ".out", ".stacktrace")) or mime in {"text/x-log", "application/log", "application/x-log"}:
        return "logs_errors_v1"
    return "markdown_docs_v1"

def resolve_vectorization_profile(filename: str | None, mime_type: str | None, requested_mode: str | None, metadata: dict | None = None) -> tuple[str, dict[str, Any]]:
    mode_id = select_mode(filename, mime_type, requested_mode, metadata)
    return mode_id, vectorization_modes().get(mode_id, vectorization_modes().get("markdown_docs_v1", {}))

def resolve_embedding_profile(mode_id: str, security_level: int) -> str:
    modes = vectorization_modes()
    registry = model_registry()
    policies = registry.get("policies", {})
    if security_level >= int(policies.get("require_private_provider_above_security_level", 4)):
        return policies.get("fallback_private_embedding_profile", "bge_m3_local")
    return modes.get(mode_id, {}).get("embedding_profile") or policies.get("default_embedding_profile", "openai_text_embedding_3_small_1536")

def resolve_model_profile_id(
    model_profile_id: str | None = None,
    *,
    provider: str | None = None,
    model: str | None = None,
    dimensions: int | None = None,
    registry: dict[str, Any] | None = None,
) -> tuple[str | None, dict[str, Any] | None]:
    registry = registry or model_registry()
    profiles = registry.get("models", {})
    if model_profile_id:
        return model_profile_id, profiles.get(model_profile_id)

    if not provider and not model:
        return None, None

    normalized_provider = (provider or "").strip().lower()
    normalized_model = (model or "").strip()
    for pid, profile in profiles.items():
        if profile.get("kind") != "embedding" or profile.get("provider") == "routing_alias":
            continue
        if normalized_provider and str(profile.get("provider", "")).lower() != normalized_provider:
            continue
        if normalized_model and str(profile.get("model", "")) != normalized_model:
            continue
        if dimensions is not None and int(profile.get("dimensions") or 0) != int(dimensions):
            continue
        return pid, profile
    return None, None

def estimate_embedding_cost(
    model_profile_id: str | None,
    input_tokens: int,
    *,
    provider: str | None = None,
    model: str | None = None,
    dimensions: int | None = None,
    registry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    registry = registry or model_registry()
    resolved_id, profile = resolve_model_profile_id(
        model_profile_id,
        provider=provider,
        model=model,
        dimensions=dimensions,
        registry=registry,
    )
    tokens = max(0, int(input_tokens or 0))
    base = {
        "model_profile_id": resolved_id or model_profile_id,
        "provider": (profile or {}).get("provider") or provider,
        "model": (profile or {}).get("model") or model,
        "dimensions": (profile or {}).get("dimensions") or dimensions,
        "estimated_tokens": tokens,
        "estimated_cost_usd": None,
        "currency": None,
        "unit": None,
        "input_per_1m_tokens_usd": None,
        "cost_source": None,
        "reason": None,
    }
    if not profile:
        base["reason"] = "unknown_model_profile"
        return base
    cost = profile.get("cost") or {}
    unit = cost.get("unit")
    price = cost.get("input_per_1m_tokens_usd")
    if unit != "1m_input_tokens" or price is None:
        base["reason"] = "cost_unavailable"
        return base

    price_float = float(price)
    base.update(
        {
            "estimated_cost_usd": round((tokens / ONE_MILLION_TOKENS) * price_float, 10),
            "currency": cost.get("currency", "USD"),
            "unit": unit,
            "input_per_1m_tokens_usd": price_float,
            "cost_source": cost.get("source"),
        }
    )
    return base
