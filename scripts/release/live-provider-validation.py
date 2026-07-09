#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from typing import Any, Mapping
from urllib import error, request

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[1]
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(ROOT / "packages" / "svs_common"))

try:
    from svs_common.chunking import estimate_tokens
except Exception:
    def estimate_tokens(text: str) -> int:
        return max(1, len(text.split()) * 4 // 3)

try:
    from svs_common.model_registry import estimate_embedding_cost, model_registry
except Exception:
    def model_registry() -> dict[str, Any]:
        return FALLBACK_MODEL_REGISTRY

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
        profiles = registry.get("models", {})
        profile = profiles.get(model_profile_id or "")
        if profile is None:
            for candidate_id, candidate in profiles.items():
                if provider and str(candidate.get("provider", "")).lower() != provider:
                    continue
                if model and candidate.get("model") != model:
                    continue
                if dimensions is not None and int(candidate.get("dimensions") or 0) != int(dimensions):
                    continue
                model_profile_id = candidate_id
                profile = candidate
                break
        tokens = max(0, int(input_tokens or 0))
        base = {
            "model_profile_id": model_profile_id,
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
        cost = (profile or {}).get("cost") or {}
        price = cost.get("input_per_1m_tokens_usd")
        if cost.get("unit") != "1m_input_tokens" or price is None:
            base["reason"] = "cost_unavailable" if profile else "unknown_model_profile"
            return base
        price_float = float(price)
        base.update(
            {
                "estimated_cost_usd": round((tokens / 1_000_000) * price_float, 10),
                "currency": cost.get("currency", "USD"),
                "unit": cost.get("unit"),
                "input_per_1m_tokens_usd": price_float,
                "cost_source": cost.get("source"),
            }
        )
        return base

try:
    from svs_common.provider_probe import endpoint_routing_state
except Exception:
    def endpoint_routing_state(status: Any, health_status: Any) -> str:
        endpoint_status = str(status or "active").strip().lower()
        health = str(health_status or "unknown").strip().lower().replace("-", "_")
        if endpoint_status in {"disabled", "inactive", "deleted", "retired"}:
            return "disabled"
        if health in {"unhealthy", "failed", "down", "error", "disabled"}:
            return "fallback"
        if health == "healthy" and endpoint_status in {"active", "enabled"}:
            return "active"
        return "fallback"

try:
    from svs_common.providers import ProviderConfigurationError, provider_config_status
except Exception:
    class ProviderConfigurationError(RuntimeError):
        """Fallback used when repo runtime dependencies are not installed."""

    @dataclass(frozen=True)
    class ProviderConfigStatus:
        provider: str
        configured: bool
        required_env: tuple[str, ...] = ()
        reason: str | None = None
        health_status: str = "unknown"
        p95_latency_ms: int | None = None
        max_security_level: int | None = None
        region: str | None = None
        model_revision: str | None = None
        auth_secret_ref: str | None = None
        routing_state: str = "unknown"

    def provider_config_status(provider_name: str, settings: Any | None = None) -> ProviderConfigStatus:
        provider = (provider_name or "").strip().lower()
        env_names = {
            "openai": ("OPENAI_API_KEY",),
            "voyage": ("VOYAGE_API_KEY",),
            "cohere": ("COHERE_API_KEY",),
            "tei": ("TEI_ENDPOINT_URL",),
            "huggingface_tei": ("TEI_ENDPOINT_URL",),
            "jina": ("TEI_ENDPOINT_URL",),
            "runpod": ("RUNPOD_EMBEDDING_ENDPOINT_URL",),
            "runpod_serverless": ("RUNPOD_EMBEDDING_ENDPOINT_URL",),
            "runpod_serverless_or_local": ("RUNPOD_EMBEDDING_ENDPOINT_URL",),
            "infinity": ("INFINITY_ENDPOINT_URL",),
            "self_hosted": ("SELF_HOSTED_MODEL_ENDPOINT_URL",),
            "openai_compatible_private": ("SELF_HOSTED_MODEL_ENDPOINT_URL",),
        }.get(provider)
        attrs = {
            "OPENAI_API_KEY": "openai_api_key",
            "VOYAGE_API_KEY": "voyage_api_key",
            "COHERE_API_KEY": "cohere_api_key",
            "TEI_ENDPOINT_URL": "tei_endpoint_url",
            "RUNPOD_EMBEDDING_ENDPOINT_URL": "runpod_embedding_endpoint_url",
            "INFINITY_ENDPOINT_URL": "infinity_endpoint_url",
            "SELF_HOSTED_MODEL_ENDPOINT_URL": "self_hosted_model_endpoint_url",
        }
        if env_names is None:
            return ProviderConfigStatus(provider=provider or "unknown", configured=False, reason=f"unknown embedding provider: {provider_name}")
        configured = all(bool(str(getattr(settings, attrs[name], "") or "").strip()) for name in env_names)
        auth_secret_ref = None
        if provider.startswith("runpod") and getattr(settings, "runpod_api_key", None):
            auth_secret_ref = "envref://RUNPOD_API_KEY"
        if provider in {"self_hosted", "openai_compatible_private"} and getattr(settings, "self_hosted_model_api_key", None):
            auth_secret_ref = "envref://SELF_HOSTED_MODEL_API_KEY"
        return ProviderConfigStatus(
            provider=provider,
            configured=configured,
            required_env=env_names,
            reason=None if configured else f"{provider} embedding provider requires {', '.join(env_names)}",
            auth_secret_ref=auth_secret_ref,
        )

try:
    from svs_common.secrets import is_secret_key, parse_secret_reference
except Exception:
    @dataclass(frozen=True)
    class SecretReference:
        scheme: str
        locator: str
        name: str

    def is_secret_key(key: str) -> bool:
        normalized = key.upper()
        return any(marker in normalized for marker in ("PASSWORD", "SECRET", "API_KEY", "TOKEN", "PEPPER", "ACCESS_KEY"))

    def parse_secret_reference(value: str | None) -> SecretReference | None:
        if value is None:
            return None
        normalized = value.strip()
        match = re.match(r"^envref://(?P<name>[A-Za-z_][A-Za-z0-9_]*)$", normalized)
        if match:
            return SecretReference("envref", "", match.group("name"))
        match = re.match(r"^(?P<scheme>sops|age|vault)://(?P<locator>[^#\s]+)#(?P<name>[A-Za-z_][A-Za-z0-9_]*)$", normalized)
        if match:
            return SecretReference(match.group("scheme"), match.group("locator"), match.group("name"))
        return None


DEFAULT_PROVIDERS = ("openai", "runpod", "tei", "infinity", "self_hosted")
DEFAULT_RERANK_PROVIDERS = ("runpod", "infinity", "self_hosted", "openai_compatible_private")
DEFAULT_EMBEDDING_TEXT = "RM-014 live provider validation embedding probe."
DEFAULT_RERANK_QUERY = "Which document discusses live provider validation?"
DEFAULT_RERANK_DOCUMENTS = (
    "RM-014 validates live provider endpoints through the model gateway.",
    "This unrelated document describes local deterministic hash fixtures.",
)

ENV_TO_SETTING = {
    "OPENAI_API_KEY": "openai_api_key",
    "VOYAGE_API_KEY": "voyage_api_key",
    "COHERE_API_KEY": "cohere_api_key",
    "TEI_ENDPOINT_URL": "tei_endpoint_url",
    "INFINITY_ENDPOINT_URL": "infinity_endpoint_url",
    "RUNPOD_EMBEDDING_ENDPOINT_URL": "runpod_embedding_endpoint_url",
    "RUNPOD_API_KEY": "runpod_api_key",
    "SELF_HOSTED_MODEL_ENDPOINT_URL": "self_hosted_model_endpoint_url",
    "SELF_HOSTED_MODEL_API_KEY": "self_hosted_model_api_key",
}


@dataclass(frozen=True)
class ProviderProbeSpec:
    provider: str
    required_env: tuple[str, ...]
    model_profile_id: str | None
    embedding_model: str
    dimensions: int
    privacy: str
    endpoint_env: str | None = None
    auth_env: str | None = None
    rerank_model: str | None = None

    @property
    def supports_rerank(self) -> bool:
        return self.rerank_model is not None


PROVIDER_SPECS: dict[str, ProviderProbeSpec] = {
    "openai": ProviderProbeSpec(
        provider="openai",
        required_env=("OPENAI_API_KEY",),
        model_profile_id="openai_text_embedding_3_small_1536",
        embedding_model="text-embedding-3-small",
        dimensions=1536,
        privacy="external_api",
    ),
    "runpod": ProviderProbeSpec(
        provider="runpod",
        required_env=("RUNPOD_EMBEDDING_ENDPOINT_URL", "RUNPOD_API_KEY"),
        model_profile_id="qwen3_embedding_local_4b",
        embedding_model="Qwen/Qwen3-Embedding-4B",
        dimensions=2560,
        privacy="private_gpu",
        endpoint_env="RUNPOD_EMBEDDING_ENDPOINT_URL",
        auth_env="RUNPOD_API_KEY",
        rerank_model="Qwen/Qwen3-Reranker-4B",
    ),
    "runpod_serverless": ProviderProbeSpec(
        provider="runpod_serverless",
        required_env=("RUNPOD_EMBEDDING_ENDPOINT_URL", "RUNPOD_API_KEY"),
        model_profile_id="qwen3_embedding_local_4b",
        embedding_model="Qwen/Qwen3-Embedding-4B",
        dimensions=2560,
        privacy="private_gpu",
        endpoint_env="RUNPOD_EMBEDDING_ENDPOINT_URL",
        auth_env="RUNPOD_API_KEY",
        rerank_model="Qwen/Qwen3-Reranker-4B",
    ),
    "runpod_serverless_or_local": ProviderProbeSpec(
        provider="runpod_serverless_or_local",
        required_env=("RUNPOD_EMBEDDING_ENDPOINT_URL", "RUNPOD_API_KEY"),
        model_profile_id="qwen3_embedding_local_4b",
        embedding_model="Qwen/Qwen3-Embedding-4B",
        dimensions=2560,
        privacy="private_gpu",
        endpoint_env="RUNPOD_EMBEDDING_ENDPOINT_URL",
        auth_env="RUNPOD_API_KEY",
        rerank_model="Qwen/Qwen3-Reranker-4B",
    ),
    "tei": ProviderProbeSpec(
        provider="tei",
        required_env=("TEI_ENDPOINT_URL",),
        model_profile_id="bge_m3_tei_local",
        embedding_model="BAAI/bge-m3",
        dimensions=1024,
        privacy="private_gpu",
        endpoint_env="TEI_ENDPOINT_URL",
    ),
    "huggingface_tei": ProviderProbeSpec(
        provider="huggingface_tei",
        required_env=("TEI_ENDPOINT_URL",),
        model_profile_id="bge_m3_tei_local",
        embedding_model="BAAI/bge-m3",
        dimensions=1024,
        privacy="private_gpu",
        endpoint_env="TEI_ENDPOINT_URL",
    ),
    "infinity": ProviderProbeSpec(
        provider="infinity",
        required_env=("INFINITY_ENDPOINT_URL",),
        model_profile_id="bge_m3_infinity_local",
        embedding_model="BAAI/bge-m3",
        dimensions=1024,
        privacy="private_gpu",
        endpoint_env="INFINITY_ENDPOINT_URL",
        rerank_model="BAAI/bge-reranker-v2-m3",
    ),
    "self_hosted": ProviderProbeSpec(
        provider="self_hosted",
        required_env=("SELF_HOSTED_MODEL_ENDPOINT_URL",),
        model_profile_id=None,
        embedding_model="BAAI/bge-m3",
        dimensions=1024,
        privacy="private_gpu",
        endpoint_env="SELF_HOSTED_MODEL_ENDPOINT_URL",
        auth_env="SELF_HOSTED_MODEL_API_KEY",
        rerank_model="BAAI/bge-reranker-v2-m3",
    ),
    "openai_compatible_private": ProviderProbeSpec(
        provider="openai_compatible_private",
        required_env=("SELF_HOSTED_MODEL_ENDPOINT_URL",),
        model_profile_id=None,
        embedding_model="BAAI/bge-m3",
        dimensions=1024,
        privacy="private_gpu",
        endpoint_env="SELF_HOSTED_MODEL_ENDPOINT_URL",
        auth_env="SELF_HOSTED_MODEL_API_KEY",
        rerank_model="BAAI/bge-reranker-v2-m3",
    ),
}

FALLBACK_MODEL_REGISTRY: dict[str, Any] = {
    "models": {
        "openai_text_embedding_3_small_1536": {
            "provider": "openai",
            "kind": "embedding",
            "model": "text-embedding-3-small",
            "dimensions": 1536,
            "privacy": "external_api",
            "cost": {
                "currency": "USD",
                "unit": "1m_input_tokens",
                "input_per_1m_tokens_usd": 0.02,
                "source": "configs/model-registry.yaml",
            },
        },
        "qwen3_embedding_local_4b": {
            "provider": "runpod_serverless_or_local",
            "kind": "embedding",
            "model": "Qwen/Qwen3-Embedding-4B",
            "dimensions": 2560,
            "privacy": "private_gpu",
        },
        "bge_m3_tei_local": {
            "provider": "tei",
            "kind": "embedding",
            "model": "BAAI/bge-m3",
            "dimensions": 1024,
            "privacy": "private_gpu",
        },
        "bge_m3_infinity_local": {
            "provider": "infinity",
            "kind": "embedding",
            "model": "BAAI/bge-m3",
            "dimensions": 1024,
            "privacy": "private_gpu",
        },
    },
    "policies": {
        "deny_external_above_security_level": 3,
        "require_private_provider_above_security_level": 4,
        "default_embedding_profile": "openai_text_embedding_3_small_1536",
        "fallback_private_embedding_profile": "bge_m3_local",
    },
}


def parse_csv(raw: str | None) -> list[str]:
    return [item.strip().lower() for item in (raw or "").split(",") if item.strip()]


def strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = strip_quotes(value.strip())
    return values


def resolve_env_value(env: Mapping[str, str], key: str) -> tuple[str | None, str, str | None]:
    raw = env.get(key)
    if raw is None or str(raw).strip() == "":
        return None, key, "missing"
    value = str(raw).strip()
    ref = parse_secret_reference(value)
    if ref is None:
        return value, key, None
    if ref.scheme == "envref":
        resolved = os.environ.get(ref.name)
        if resolved and parse_secret_reference(resolved) is None:
            return resolved, f"envref://{ref.name}", None
        return None, f"envref://{ref.name}", "secret_reference_unresolved"
    return None, f"{ref.scheme}://...#{ref.name}", "external_secret_reference_not_resolved"


def merged_env(args: argparse.Namespace, base_env: Mapping[str, str] | None = None) -> dict[str, str]:
    values: dict[str, str] = {}
    if args.env_file:
        env_path = Path(args.env_file)
        if not env_path.is_absolute():
            env_path = ROOT / env_path
        values.update(read_env_file(env_path))
    values.update(dict(os.environ if base_env is None else base_env))
    return values


def settings_from_env(env: Mapping[str, str]) -> SimpleNamespace:
    values = {attr: None for attr in ENV_TO_SETTING.values()}
    for env_key, attr in ENV_TO_SETTING.items():
        value, _source, issue = resolve_env_value(env, env_key)
        if issue is None:
            values[attr] = value
    return SimpleNamespace(**values)


def input_status(env: Mapping[str, str], keys: tuple[str, ...]) -> list[dict[str, Any]]:
    statuses: list[dict[str, Any]] = []
    for key in keys:
        value, source, issue = resolve_env_value(env, key)
        statuses.append(
            {
                "name": key,
                "source": source,
                "present": value is not None,
                "secret": is_secret_key(key),
                "issue": issue,
            }
        )
    return statuses


def missing_required_inputs(env: Mapping[str, str], spec: ProviderProbeSpec) -> list[str]:
    missing: list[str] = []
    for key in spec.required_env:
        value, _source, issue = resolve_env_value(env, key)
        if value is None or issue is not None:
            missing.append(key)
    return missing


def secret_ref(env: Mapping[str, str], key: str | None) -> str | None:
    if not key:
        return None
    value, source, issue = resolve_env_value(env, key)
    if issue is None and value is not None:
        return f"envref://{key}"
    if source != key:
        return source
    return None


def is_private_provider(spec: ProviderProbeSpec) -> bool:
    return spec.privacy in {"private_gpu", "local_or_private_gpu", "local_dev_only"} or spec.endpoint_env is not None


def is_external_provider(spec: ProviderProbeSpec) -> bool:
    return spec.privacy.startswith("external")


def policy_decision(
    spec: ProviderProbeSpec,
    *,
    approved_providers: set[str],
    security_level: int,
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    provider = spec.provider.lower()
    policies = dict(registry.get("policies") or {})
    deny_external_above = int(policies.get("deny_external_above_security_level", 3))
    require_private_above = int(policies.get("require_private_provider_above_security_level", 4))
    if provider not in approved_providers:
        return {"allowed": False, "reason": "provider_not_approved"}
    if is_external_provider(spec) and security_level > deny_external_above:
        return {
            "allowed": False,
            "reason": "external_provider_denied_above_security_level",
            "deny_external_above_security_level": deny_external_above,
        }
    if security_level >= require_private_above and not is_private_provider(spec):
        return {
            "allowed": False,
            "reason": "private_provider_required_at_security_level",
            "require_private_provider_above_security_level": require_private_above,
        }
    return {"allowed": True, "reason": None}


def safe_error(exc: BaseException) -> dict[str, str]:
    if isinstance(exc, ProviderConfigurationError):
        return {"type": exc.__class__.__name__, "code": str(exc)}
    if isinstance(exc, error.HTTPError):
        return {"type": exc.__class__.__name__, "code": f"http_{exc.code}"}
    if isinstance(exc, error.URLError):
        reason = getattr(exc, "reason", None)
        reason_type = reason.__class__.__name__ if reason is not None else "url_error"
        return {"type": exc.__class__.__name__, "code": reason_type}
    return {"type": exc.__class__.__name__, "code": exc.__class__.__name__}


def numeric_usage(usage: Mapping[str, Any] | None) -> dict[str, int | float]:
    safe: dict[str, int | float] = {}
    for key, value in dict(usage or {}).items():
        if isinstance(value, (int, float)):
            safe[str(key)] = value
    return safe


def malformed_operation(*, provider: str, model: str, latency_ms: int, reason: str) -> dict[str, Any]:
    return {
        "status": "failed",
        "checked_live": True,
        "latency_ms": latency_ms,
        "provider": provider,
        "model": model,
        "error": {"type": "MalformedGatewayResponse", "code": reason},
    }


def embedding_payload(spec: ProviderProbeSpec, args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "input": [args.embedding_text],
        "provider": spec.provider,
        "model": args.model or spec.embedding_model,
        "dimensions": args.dimensions or spec.dimensions,
        "security_level": args.security_level,
        "input_type": "document",
    }
    if spec.model_profile_id:
        payload["model_profile_id"] = spec.model_profile_id
    return payload


def rerank_payload(spec: ProviderProbeSpec, args: argparse.Namespace) -> dict[str, Any]:
    return {
        "query": args.rerank_query,
        "documents": list(DEFAULT_RERANK_DOCUMENTS),
        "provider": spec.provider,
        "model": args.rerank_model or spec.rerank_model,
        "security_level": args.security_level,
        "top_n": 1,
    }


def cost_metadata(spec: ProviderProbeSpec, args: argparse.Namespace) -> dict[str, Any]:
    return estimate_embedding_cost(
        spec.model_profile_id,
        estimate_tokens(args.embedding_text),
        provider=spec.provider,
        model=args.model or spec.embedding_model,
        dimensions=args.dimensions or spec.dimensions,
    )


def post_gateway_json(gateway_url: str, path: str, payload: Mapping[str, Any], timeout_seconds: float) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        gateway_url.rstrip("/") + path,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with request.urlopen(req, timeout=timeout_seconds) as response:
        raw = response.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def probe_health(spec: ProviderProbeSpec, env: Mapping[str, str], args: argparse.Namespace) -> dict[str, Any]:
    if args.skip_health_probe or not spec.endpoint_env:
        return {
            "checked_live": False,
            "health_status": "unknown",
            "routing_state": "unknown",
            "reason": "health_probe_skipped",
        }
    endpoint_url, _source, endpoint_issue = resolve_env_value(env, spec.endpoint_env)
    if endpoint_url is None or endpoint_issue is not None:
        return {
            "checked_live": False,
            "health_status": "unknown",
            "routing_state": "unknown",
            "reason": "endpoint_not_configured",
        }
    api_key = None
    if spec.auth_env:
        api_key, _auth_source, _auth_issue = resolve_env_value(env, spec.auth_env)
    health_url = f"{endpoint_url.rstrip('/')}/health"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    req = request.Request(health_url, headers=headers, method="GET")
    started = perf_counter()
    try:
        with request.urlopen(req, timeout=args.timeout_seconds) as response:
            status_code = response.status
        observed_ms = int(round((perf_counter() - started) * 1000))
        healthy = status_code < 500
        health_status = "healthy" if healthy else "failed"
        reason = None if healthy else f"health_http_{status_code}"
    except error.HTTPError as exc:
        observed_ms = int(round((perf_counter() - started) * 1000))
        healthy = exc.code < 500
        health_status = "healthy" if healthy else "failed"
        reason = None if healthy else f"health_http_{exc.code}"
    except error.URLError as exc:
        observed_ms = int(round((perf_counter() - started) * 1000))
        healthy = False
        health_status = "failed"
        reason_obj = getattr(exc, "reason", None)
        reason = reason_obj.__class__.__name__ if reason_obj is not None else "url_error"
    return {
        "checked_live": True,
        "health_status": health_status,
        "healthy": healthy,
        "observed_latency_ms": observed_ms,
        "p95_latency_ms": observed_ms,
        "routing_state": endpoint_routing_state("active", health_status),
        "reason": reason,
    }


def run_embedding_probe(
    spec: ProviderProbeSpec,
    args: argparse.Namespace,
    *,
    gateway_url: str | None,
) -> dict[str, Any]:
    if not gateway_url:
        return {
            "status": "skipped",
            "checked_live": False,
            "provider": spec.provider,
            "model": args.model or spec.embedding_model,
            "reason": "gateway_url_required_for_live_provider_call",
        }
    payload = embedding_payload(spec, args)
    started = perf_counter()
    try:
        body = post_gateway_json(gateway_url, "/internal/models/embeddings", payload, args.timeout_seconds)
        latency_ms = int(round((perf_counter() - started) * 1000))
        data = body.get("data") or []
        first = data[0] if data else {}
        vector = first.get("embedding") if isinstance(first, dict) else None
        if not isinstance(vector, list) or not vector:
            return malformed_operation(
                provider=spec.provider,
                model=payload["model"],
                latency_ms=latency_ms,
                reason="missing_embedding_vector",
            )
        return {
            "status": "success",
            "checked_live": True,
            "execution_path": "gateway_http",
            "latency_ms": latency_ms,
            "provider": body.get("provider", spec.provider),
            "model": body.get("model", payload["model"]),
            "dimensions": body.get("dimensions", payload["dimensions"]),
            "data_count": len(data),
            "first_vector_dimensions": len(vector) if isinstance(vector, list) else None,
            "usage": numeric_usage(body.get("usage")),
        }
    except Exception as exc:
        latency_ms = int(round((perf_counter() - started) * 1000))
        return {
            "status": "failed",
            "checked_live": True,
            "latency_ms": latency_ms,
            "provider": spec.provider,
            "model": payload["model"],
            "error": safe_error(exc),
        }


def run_rerank_probe(
    spec: ProviderProbeSpec,
    args: argparse.Namespace,
    *,
    gateway_url: str | None,
) -> dict[str, Any]:
    if not spec.supports_rerank:
        return {"status": "skipped", "checked_live": False, "reason": "operation_not_supported_by_default"}
    if spec.provider not in set(parse_csv(args.rerank_providers)):
        return {"status": "skipped", "checked_live": False, "reason": "provider_not_in_rerank_probe_set"}
    if not gateway_url:
        return {
            "status": "skipped",
            "checked_live": False,
            "provider": spec.provider,
            "model": args.rerank_model or spec.rerank_model,
            "reason": "gateway_url_required_for_live_provider_call",
        }
    payload = rerank_payload(spec, args)
    started = perf_counter()
    try:
        body = post_gateway_json(gateway_url, "/internal/models/rerank", payload, args.timeout_seconds)
        latency_ms = int(round((perf_counter() - started) * 1000))
        results = body.get("results") or []
        valid_results = [
            item for item in results
            if isinstance(item, Mapping) and isinstance(item.get("index"), int) and isinstance(item.get("relevance_score"), (int, float))
        ]
        if not valid_results:
            return malformed_operation(
                provider=spec.provider,
                model=payload["model"],
                latency_ms=latency_ms,
                reason="missing_rerank_results",
            )
        return {
            "status": "success",
            "checked_live": True,
            "execution_path": "gateway_http",
            "latency_ms": latency_ms,
            "provider": body.get("provider", spec.provider),
            "model": body.get("model", payload["model"]),
            "result_count": len(valid_results),
        }
    except Exception as exc:
        latency_ms = int(round((perf_counter() - started) * 1000))
        return {
            "status": "failed",
            "checked_live": True,
            "latency_ms": latency_ms,
            "provider": spec.provider,
            "model": payload["model"],
            "error": safe_error(exc),
        }


def run_gateway_cost_probe(
    spec: ProviderProbeSpec,
    args: argparse.Namespace,
    gateway_url: str | None,
) -> dict[str, Any]:
    if not gateway_url:
        return cost_metadata(spec, args)
    try:
        return post_gateway_json(gateway_url, "/internal/models/estimate-cost", embedding_payload(spec, args), args.timeout_seconds)
    except Exception as exc:
        metadata = cost_metadata(spec, args)
        metadata["gateway_error"] = safe_error(exc)
        return metadata


def provider_status_from_operations(provider: dict[str, Any]) -> str:
    if provider.get("approval", {}).get("allowed") is False:
        reason = provider["approval"].get("reason")
        return "unapproved" if reason == "provider_not_approved" else "policy_denied"
    if provider.get("missing_required_env"):
        return "skipped_missing_inputs"
    health = provider.get("health_probe") or {}
    if health.get("checked_live") and health.get("healthy") is False:
        return "unavailable"
    embedding = provider.get("operations", {}).get("embedding", {})
    rerank = provider.get("operations", {}).get("rerank", {})
    if embedding.get("status") != "success":
        return "unavailable"
    if rerank.get("status") == "failed":
        return "partial"
    return "success"


def run_validation(args: argparse.Namespace, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    env_values = merged_env(args, env)
    settings = settings_from_env(env_values)
    registry = model_registry()
    providers = parse_csv(args.providers) or list(DEFAULT_PROVIDERS)
    approved = set(parse_csv(args.approved_providers) or providers)
    gateway_url = args.gateway_url.strip() if args.gateway_url else None

    provider_reports: list[dict[str, Any]] = []
    for provider_name in providers:
        spec = PROVIDER_SPECS.get(provider_name)
        if spec is None:
            provider_reports.append(
                {
                    "provider": provider_name,
                    "status": "unavailable",
                    "approval": {"allowed": False, "reason": "unknown_provider"},
                    "provider_config_status": {
                        "configured": False,
                        "required_env": [],
                        "reason": "unknown_provider",
                    },
                    "operations": {},
                }
            )
            continue

        status = provider_config_status(spec.provider, settings=settings)
        approval = policy_decision(
            spec,
            approved_providers=approved,
            security_level=args.security_level,
            registry=registry,
        )
        missing = missing_required_inputs(env_values, spec)
        report: dict[str, Any] = {
            "provider": spec.provider,
            "privacy": spec.privacy,
            "approved_provider_set": sorted(approved),
            "approval": approval,
            "required_inputs": input_status(env_values, spec.required_env),
            "missing_required_env": missing,
            "provider_config_status": {
                "configured": status.configured,
                "required_env": list(status.required_env),
                "reason": status.reason,
                "health_status": status.health_status,
                "routing_state": status.routing_state,
                "auth_secret_ref": status.auth_secret_ref or secret_ref(env_values, spec.auth_env),
            },
            "endpoint_ref": f"envref://{spec.endpoint_env}" if spec.endpoint_env else None,
            "operations": {},
        }

        if approval["allowed"] is False:
            report["operations"] = {
                "embedding": {"status": "skipped", "checked_live": False, "reason": approval["reason"]},
                "rerank": {"status": "skipped", "checked_live": False, "reason": approval["reason"]},
            }
            report["status"] = provider_status_from_operations(report)
            provider_reports.append(report)
            continue

        if missing:
            report["operations"] = {
                "embedding": {"status": "skipped", "checked_live": False, "reason": "missing_required_env"},
                "rerank": {"status": "skipped", "checked_live": False, "reason": "missing_required_env"},
            }
            report["status"] = provider_status_from_operations(report)
            provider_reports.append(report)
            continue

        report["health_probe"] = probe_health(spec, env_values, args)
        health = report["health_probe"]
        if health.get("checked_live") and health.get("healthy") is False:
            report["operations"] = {
                "embedding": {"status": "skipped", "checked_live": False, "reason": "private_endpoint_health_failed"},
                "rerank": {"status": "skipped", "checked_live": False, "reason": "private_endpoint_health_failed"},
            }
            report["status"] = provider_status_from_operations(report)
            provider_reports.append(report)
            continue

        report["cost_metadata"] = run_gateway_cost_probe(spec, args, gateway_url)
        report["operations"]["embedding"] = run_embedding_probe(spec, args, gateway_url=gateway_url)
        report["operations"]["rerank"] = run_rerank_probe(spec, args, gateway_url=gateway_url)
        report["status"] = provider_status_from_operations(report)
        provider_reports.append(report)

    success_ops = [
        operation
        for provider in provider_reports
        for operation in provider.get("operations", {}).values()
        if operation.get("status") == "success"
    ]
    gateway_success_ops = [operation for operation in success_ops if operation.get("execution_path") == "gateway_http"]
    unavailable = [provider["provider"] for provider in provider_reports if provider.get("status") in {"unavailable", "skipped_missing_inputs"}]
    partial = [provider["provider"] for provider in provider_reports if provider.get("status") == "partial"]
    unapproved = [provider["provider"] for provider in provider_reports if provider.get("status") == "unapproved"]
    policy_denied = [provider["provider"] for provider in provider_reports if provider.get("status") == "policy_denied"]

    if not success_ops:
        proof_status = "skipped_no_live_provider_calls"
    elif unavailable or partial or unapproved or policy_denied:
        proof_status = "partial"
    else:
        proof_status = "passed"

    return {
        "proof": "rm-014-live-provider-validation",
        "proof_status": proof_status,
        "live_proof_claimed": bool(success_ops),
        "gateway_live_proof_claimed": bool(gateway_success_ops),
        "execution_path": "gateway_http" if gateway_url else "not_executed_gateway_url_missing",
        "gateway_url_ref": "cli://--gateway-url" if gateway_url else None,
        "security_level": args.security_level,
        "providers_requested": providers,
        "provider_count": len(provider_reports),
        "unavailable_or_unconfigured_providers": unavailable,
        "partial_providers": partial,
        "unapproved_providers": unapproved,
        "policy_denied_providers": policy_denied,
        "providers": provider_reports,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Secret-safe RM-014 live provider validation wrapper.")
    parser.add_argument("--env-file", help="Optional env file with endpoint references or runtime values. Values are never printed.")
    parser.add_argument("--providers", default=",".join(DEFAULT_PROVIDERS), help="Comma-separated provider list to validate.")
    parser.add_argument(
        "--approved-providers",
        help="Comma-separated provider allowlist. Defaults to --providers; providers outside this list are reported as unapproved and not called.",
    )
    parser.add_argument("--rerank-providers", default=",".join(DEFAULT_RERANK_PROVIDERS), help="Comma-separated providers to probe for rerank.")
    parser.add_argument("--gateway-url", help="Model gateway base URL. When supplied, probes call gateway HTTP routes.")
    parser.add_argument("--security-level", type=int, default=1)
    parser.add_argument("--embedding-text", default=DEFAULT_EMBEDDING_TEXT)
    parser.add_argument("--rerank-query", default=DEFAULT_RERANK_QUERY)
    parser.add_argument("--model", help="Override embedding model for all providers.")
    parser.add_argument("--dimensions", type=int, help="Override embedding dimensions for all providers.")
    parser.add_argument("--rerank-model", help="Override rerank model for providers that support rerank.")
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--skip-health-probe", action="store_true", help="Skip private endpoint /health checks before operation probes.")
    parser.add_argument("--require-live", action="store_true", help="Exit non-zero unless at least one live provider operation succeeds and no requested provider is unavailable/unapproved.")
    parser.add_argument("--output-file", help="Optional path for the JSON proof report.")
    return parser


def exit_code(report: Mapping[str, Any], *, require_live: bool) -> int:
    if not require_live:
        return 0
    if not report.get("live_proof_claimed"):
        return 2
    if (
        report.get("unavailable_or_unconfigured_providers")
        or report.get("partial_providers")
        or report.get("unapproved_providers")
        or report.get("policy_denied_providers")
    ):
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_validation(args)
    text = json.dumps(report, indent=2, sort_keys=True)
    print(text)
    if args.output_file:
        output_path = Path(args.output_file)
        if not output_path.is_absolute():
            output_path = ROOT / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(text + "\n", encoding="utf-8")
    return exit_code(report, require_live=args.require_live)


if __name__ == "__main__":
    raise SystemExit(main())
