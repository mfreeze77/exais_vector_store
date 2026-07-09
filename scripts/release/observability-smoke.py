from __future__ import annotations

import argparse
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


REQUIRED_OBSERVABILITY_METRICS: dict[str, tuple[str, ...]] = {
    "api": ("svs_api_build_info",),
    "ingestion": ("svs_ingestion_jobs_queued", "svs_ingestion_jobs_oldest_queued_age_seconds"),
    "worker": ("svs_worker_jobs_completed_total", "svs_worker_jobs_failed_total"),
    "index": ("svs_chunks_index_pending", "svs_chunks_indexed_total"),
    "storage": ("svs_object_store_documents_tracked_total", "svs_storage_vector_store_usage_bytes"),
    "security": ("svs_security_audit_events_denied_total", "svs_security_acl_denied_retrieval_total"),
    "cost": ("svs_usage_cost_estimate_usd_total", "svs_model_gateway_priced_embedding_profiles"),
    "backup": ("svs_backup_bundle_last_success_timestamp_seconds", "svs_backup_manifest_artifacts_total"),
}

PROMETHEUS_TEXT_METRIC_RE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{|[ \t])")


@dataclass(frozen=True)
class ObservabilityEvidence:
    cell: str
    api_base: str
    prometheus_url: str
    checked_at: str
    api_metrics_url: str
    required_metrics: dict[str, tuple[str, ...]]
    api_visible_metrics: tuple[str, ...]
    prometheus_visible_metrics: tuple[str, ...]
    api_visible_categories: tuple[str, ...]
    prometheus_visible_categories: tuple[str, ...]
    missing_api_categories: tuple[str, ...]
    missing_prometheus_categories: tuple[str, ...]
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.errors and not self.missing_api_categories and not self.missing_prometheus_categories

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "cell": self.cell,
            "api_base": self.api_base,
            "prometheus_url": self.prometheus_url,
            "checked_at": self.checked_at,
            "api_metrics_url": self.api_metrics_url,
            "required_metrics": {key: list(value) for key, value in self.required_metrics.items()},
            "api_visible_metrics": list(self.api_visible_metrics),
            "prometheus_visible_metrics": list(self.prometheus_visible_metrics),
            "api_visible_categories": list(self.api_visible_categories),
            "prometheus_visible_categories": list(self.prometheus_visible_categories),
            "missing_api_categories": list(self.missing_api_categories),
            "missing_prometheus_categories": list(self.missing_prometheus_categories),
            "errors": list(self.errors),
        }


def collect_observability_evidence(api_base: str, prometheus_url: str, *, cell: str) -> ObservabilityEvidence:
    normalized_api_base = api_base.rstrip("/")
    normalized_prometheus_url = prometheus_url.rstrip("/")
    api_metrics_url = f"{normalized_api_base}/metrics"
    errors: list[str] = []

    try:
        api_metrics_text = _http_get_text(api_metrics_url)
    except Exception as exc:
        api_metrics_text = ""
        errors.append(f"api_metrics_fetch_failed: {exc}")
    api_metric_names = parse_prometheus_text_metric_names(api_metrics_text)
    api_visible_categories = visible_categories(api_metric_names)

    prometheus_visible_metrics: set[str] = set()
    for metric_name in sorted(required_metric_names()):
        query_url = prometheus_query_url(normalized_prometheus_url, metric_name)
        try:
            if prometheus_query_has_series(_http_get_text(query_url)):
                prometheus_visible_metrics.add(metric_name)
        except Exception as exc:
            errors.append(f"prometheus_query_failed[{metric_name}]: {exc}")
    prometheus_visible_categories = visible_categories(prometheus_visible_metrics)

    return ObservabilityEvidence(
        cell=cell,
        api_base=normalized_api_base,
        prometheus_url=normalized_prometheus_url,
        checked_at=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        api_metrics_url=api_metrics_url,
        required_metrics=REQUIRED_OBSERVABILITY_METRICS,
        api_visible_metrics=tuple(sorted(api_metric_names.intersection(required_metric_names()))),
        prometheus_visible_metrics=tuple(sorted(prometheus_visible_metrics)),
        api_visible_categories=tuple(sorted(api_visible_categories)),
        prometheus_visible_categories=tuple(sorted(prometheus_visible_categories)),
        missing_api_categories=tuple(sorted(set(REQUIRED_OBSERVABILITY_METRICS) - api_visible_categories)),
        missing_prometheus_categories=tuple(sorted(set(REQUIRED_OBSERVABILITY_METRICS) - prometheus_visible_categories)),
        errors=tuple(errors),
    )


def required_metric_names() -> set[str]:
    return {metric for metrics in REQUIRED_OBSERVABILITY_METRICS.values() for metric in metrics}


def parse_prometheus_text_metric_names(metrics_text: str) -> set[str]:
    names: set[str] = set()
    for line in metrics_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = PROMETHEUS_TEXT_METRIC_RE.match(stripped)
        if match:
            names.add(match.group(1))
    return names


def visible_categories(metric_names: set[str]) -> set[str]:
    return {
        category
        for category, candidates in REQUIRED_OBSERVABILITY_METRICS.items()
        if any(candidate in metric_names for candidate in candidates)
    }


def prometheus_query_url(prometheus_url: str, metric_name: str) -> str:
    return f"{prometheus_url.rstrip('/')}/api/v1/query?{urllib.parse.urlencode({'query': metric_name})}"


def prometheus_query_has_series(response_text: str) -> bool:
    payload = json.loads(response_text)
    if payload.get("status") != "success":
        return False
    data = payload.get("data")
    return isinstance(data, dict) and bool(data.get("result"))


def _http_get_text(url: str, *, timeout: float = 10.0) -> str:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        raw = response.read()
    return raw.decode("utf-8", errors="replace")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Collect local-cell observability smoke evidence.")
    parser.add_argument("--api-base", default="http://localhost:18080")
    parser.add_argument("--prometheus-url", default="http://localhost:19090")
    parser.add_argument("--cell", default="local-cell")
    args = parser.parse_args(argv)

    evidence = collect_observability_evidence(args.api_base, args.prometheus_url, cell=args.cell)
    print(json.dumps(evidence.to_dict(), indent=2, sort_keys=True))
    if not evidence.ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
