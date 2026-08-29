from __future__ import annotations
from functools import lru_cache
import os
from pathlib import Path
from typing import Any
import yaml
from .schemas import ExpertModelPolicy

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


class ModelRegistryConfigurationError(ValueError):
    """Raised when a policy points at an absent or incompatible model profile."""


def resolve_expert_chat_profiles(
    model_policy: ExpertModelPolicy,
    *,
    registry: dict[str, Any] | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    """Resolve ordered chat candidates without inspecting provider credentials."""

    registry = registry or model_registry()
    policies = registry.get("chat_policies") or {}
    policy = policies.get(model_policy.policy_id)
    if not isinstance(policy, dict):
        raise ModelRegistryConfigurationError(f"Unknown expert chat policy: {model_policy.policy_id}")

    preferred_id = (
        (model_policy.preferred_model_profile_id or "").strip()
        or str(policy.get("preferred_model_profile_id") or "").strip()
    )
    if not preferred_id:
        raise ModelRegistryConfigurationError(
            f"Expert chat policy {model_policy.policy_id!r} has no preferred model profile"
        )

    fallback_ids = [
        str(profile_id).strip()
        for profile_id in (
            model_policy.fallback_model_profile_ids
            or policy.get("fallback_model_profile_ids")
            or []
        )
        if str(profile_id).strip()
    ]
    policy_allows_fallback = bool(policy.get("allow_fallback", True))
    ordered_ids = [preferred_id]
    if model_policy.allow_fallback and policy_allows_fallback:
        ordered_ids.extend(fallback_ids)

    profiles = registry.get("chat_models") or {}
    resolved: list[tuple[str, dict[str, Any]]] = []
    seen: set[str] = set()
    for profile_id in ordered_ids:
        if profile_id in seen:
            continue
        seen.add(profile_id)
        profile = profiles.get(profile_id)
        if not isinstance(profile, dict):
            raise ModelRegistryConfigurationError(f"Unknown expert chat model profile: {profile_id}")
        if profile.get("kind") != "chat":
            raise ModelRegistryConfigurationError(f"Expert model profile {profile_id!r} is not a chat profile")
        if not str(profile.get("provider") or "").strip() or not str(profile.get("model") or "").strip():
            raise ModelRegistryConfigurationError(
                f"Expert chat model profile {profile_id!r} must define provider and model"
            )
        try:
            max_security_level = int(profile["max_security_level"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelRegistryConfigurationError(
                f"Expert chat model profile {profile_id!r} must define max_security_level from 0 through 5"
            ) from exc
        if not 0 <= max_security_level <= 5:
            raise ModelRegistryConfigurationError(
                f"Expert chat model profile {profile_id!r} must define max_security_level from 0 through 5"
            )
        resolved.append((profile_id, dict(profile)))
    return resolved

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
