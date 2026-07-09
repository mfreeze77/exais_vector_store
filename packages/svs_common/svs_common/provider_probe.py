from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Mapping

import httpx


PRIVATE_ENDPOINT_PROVIDERS = frozenset(
    {
        "runpod",
        "runpod_serverless",
        "runpod_serverless_or_local",
        "tei",
        "huggingface_tei",
        "infinity",
        "self_hosted",
        "openai_compatible_private",
        "jina",
    }
)

ENDPOINT_METADATA_FIELDS = (
    "supports",
    "health_status",
    "p95_latency_ms",
    "region",
    "model_revision",
    "auth_secret_ref",
    "last_health_check_at",
    "routing_state",
)

FAILED_HEALTH_STATUSES = frozenset({"unhealthy", "failed", "down", "error", "disabled"})
DISABLED_ENDPOINT_STATUSES = frozenset({"disabled", "inactive", "deleted", "retired"})


@dataclass(frozen=True)
class PrivateEndpointProbeResult:
    health_status: str
    healthy: bool | None
    checked_live: bool
    observed_latency_ms: int | None = None
    p95_latency_ms: int | None = None
    reason: str | None = None


def normalize_health_status(value: Any) -> str:
    status = str(value or "unknown").strip().lower().replace("-", "_")
    if status in {"ok", "ready"}:
        return "healthy"
    if status in {"unavailable", "failure"}:
        return "failed"
    return status or "unknown"


def health_allows_routing(health_status: Any) -> bool:
    return normalize_health_status(health_status) not in FAILED_HEALTH_STATUSES


def endpoint_routing_state(status: Any, health_status: Any) -> str:
    endpoint_status = str(status or "active").strip().lower()
    health = normalize_health_status(health_status)
    if endpoint_status in DISABLED_ENDPOINT_STATUSES:
        return "disabled"
    if health in FAILED_HEALTH_STATUSES:
        return "fallback"
    if endpoint_status == "fallback":
        return "fallback"
    if health == "healthy" and endpoint_status in {"active", "enabled"}:
        return "active"
    return "fallback"


def normalize_endpoint_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    config = dict(normalized.get("config") or {})
    for field in ENDPOINT_METADATA_FIELDS:
        if field in normalized and normalized[field] is not None:
            config[field] = normalized[field]

    health_status = normalize_health_status(config.get("health_status"))
    config["health_status"] = health_status
    config.setdefault("live_credential_proof", False)
    config["routing_state"] = endpoint_routing_state(normalized.get("status"), health_status)

    if str(normalized.get("status") or "active").strip().lower() == "active" and health_status in FAILED_HEALTH_STATUSES:
        normalized["status"] = "fallback"

    normalized["config"] = config
    return normalized


def endpoint_response_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(row)
    config = dict(payload.get("config") or {})
    for field in ENDPOINT_METADATA_FIELDS:
        if field in config:
            payload[field] = config[field]
    payload["health_status"] = normalize_health_status(payload.get("health_status"))
    payload["routing_state"] = config.get("routing_state") or endpoint_routing_state(
        payload.get("status"),
        payload["health_status"],
    )
    payload["config"] = config
    return payload


async def probe_private_endpoint(
    base_url: str,
    *,
    api_key: str | None = None,
    timeout: float = 5.0,
    live: bool = False,
) -> PrivateEndpointProbeResult:
    if not live:
        return PrivateEndpointProbeResult(
            health_status="unknown",
            healthy=None,
            checked_live=False,
            reason="live_probe_not_requested",
        )
    health_url = f"{base_url.rstrip('/')}/health"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    started = perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(health_url, headers=headers)
        observed_ms = int(round((perf_counter() - started) * 1000))
        healthy = response.status_code < 500
        return PrivateEndpointProbeResult(
            health_status="healthy" if healthy else "failed",
            healthy=healthy,
            checked_live=True,
            observed_latency_ms=observed_ms,
            p95_latency_ms=observed_ms,
            reason=None if healthy else f"health_http_{response.status_code}",
        )
    except httpx.HTTPError as exc:
        observed_ms = int(round((perf_counter() - started) * 1000))
        return PrivateEndpointProbeResult(
            health_status="failed",
            healthy=False,
            checked_live=True,
            observed_latency_ms=observed_ms,
            reason=exc.__class__.__name__,
        )
