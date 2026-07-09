from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml

from svs_api import main as api_main
from svs_model_gateway import main as gateway_main


ROOT = Path(__file__).resolve().parents[1]
METRIC_RE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{|[ \t])")
SVS_METRIC_REF_RE = re.compile(r"\b(svs_[a-zA-Z0-9_:]+)\b")


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class FakeDb:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.sql: list[str] = []

    def execute(self, sql):
        sql_text = str(sql)
        self.sql.append(sql_text)
        if self.fail:
            raise RuntimeError("db unavailable")
        return ScalarResult(7)


def load_smoke_module():
    module_name = "observability_smoke_for_tests"
    script_path = ROOT / "scripts" / "release" / "observability-smoke.py"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def metric_names(metrics_text: str) -> set[str]:
    names: set[str] = set()
    for line in metrics_text.splitlines():
        match = METRIC_RE.match(line)
        if match:
            names.add(match.group(1))
    return names


def dashboard_expressions(value) -> list[str]:
    if isinstance(value, dict):
        expressions: list[str] = []
        for key, nested in value.items():
            if key == "expr" and isinstance(nested, str):
                expressions.append(nested)
            else:
                expressions.extend(dashboard_expressions(nested))
        return expressions
    if isinstance(value, list):
        expressions: list[str] = []
        for nested in value:
            expressions.extend(dashboard_expressions(nested))
        return expressions
    return []


def rule_expressions(rules_doc: dict) -> list[str]:
    expressions: list[str] = []
    for group in rules_doc.get("groups", []):
        for rule in group.get("rules", []):
            expr = rule.get("expr")
            if isinstance(expr, str):
                expressions.append(expr)
    return expressions


def referenced_svs_metrics(expressions: list[str]) -> set[str]:
    return {match.group(1) for expr in expressions for match in SVS_METRIC_REF_RE.finditer(expr)}


def test_api_metrics_expose_local_cell_observability_categories():
    db = FakeDb()

    body = api_main.metrics(db)
    names = metric_names(body)

    assert {
        "svs_api_build_info",
        "svs_ingestion_jobs_queued",
        "svs_worker_jobs_completed_total",
        "svs_chunks_index_pending",
        "svs_object_store_documents_tracked_total",
        "svs_security_audit_events_denied_total",
        "svs_usage_cost_estimate_usd_total",
        "svs_backup_bundle_last_success_timestamp_seconds",
        "svs_backup_manifest_artifacts_total",
    } <= names
    joined_sql = "\n".join(db.sql)
    assert "ingestion_jobs" in joined_sql
    assert "chunks" in joined_sql
    assert "backup_bundles" in joined_sql


def test_api_metrics_fail_database_queries_to_zero():
    body = api_main.metrics(FakeDb(fail=True))

    assert "svs_ingestion_jobs_queued 0" in body
    assert "svs_backup_manifest_artifacts_total 0" in body
    assert "svs_api_build_info" in body


def test_model_gateway_metrics_expose_provider_and_cost_surface():
    body = gateway_main.metrics()
    names = metric_names(body)

    assert {
        "svs_model_gateway_build_info",
        "svs_model_gateway_embedding_profiles",
        "svs_model_gateway_priced_embedding_profiles",
        "svs_model_gateway_unpriced_embedding_profiles",
        "svs_model_gateway_embedding_profiles_by_provider",
    } <= names


def test_observability_dashboard_and_alert_rules_reference_defined_metrics():
    smoke = load_smoke_module()
    emitted = metric_names(api_main.metrics(FakeDb())) | metric_names(gateway_main.metrics())
    allowed = emitted | smoke.required_metric_names()

    dashboard = json.loads((ROOT / "charts" / "exais-observability" / "dashboards" / "exais-production.json").read_text(encoding="utf-8"))
    rules = yaml.safe_load((ROOT / "charts" / "exais-observability" / "rules" / "exais-alerts.yaml").read_text(encoding="utf-8"))
    refs = referenced_svs_metrics(dashboard_expressions(dashboard) + rule_expressions(rules))

    assert dashboard["title"] == "ExAIS Local Cell Observability"
    assert refs
    assert refs <= allowed


def test_observability_compose_wires_prometheus_grafana_and_alertmanager():
    compose_path = ROOT / "infra" / "docker" / "compose.observability.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

    assert {"prometheus", "grafana", "alertmanager"} <= set(compose["services"])
    prometheus_volumes = compose["services"]["prometheus"]["volumes"]
    grafana_volumes = compose["services"]["grafana"]["volumes"]
    assert any("prometheus.yml:/etc/prometheus/prometheus.yml:ro" in volume for volume in prometheus_volumes)
    assert any("rules:/etc/prometheus/rules:ro" in volume for volume in prometheus_volumes)
    assert any("dashboards:/var/lib/grafana/dashboards/exais:ro" in volume for volume in grafana_volumes)

    for volume in prometheus_volumes + grafana_volumes + compose["services"]["alertmanager"]["volumes"]:
        source = volume.split(":", 1)[0]
        if source.startswith("../../"):
            assert (compose_path.parent / source).resolve().exists(), source

    prometheus_config = yaml.safe_load((ROOT / "charts" / "exais-observability" / "prometheus.yml").read_text(encoding="utf-8"))
    jobs = {job["job_name"]: job for job in prometheus_config["scrape_configs"]}
    assert {"exais-api", "exais-model-gateway"} <= set(jobs)
    assert jobs["exais-api"]["static_configs"][0]["targets"] == ["api:8080"]
    assert jobs["exais-model-gateway"]["static_configs"][0]["targets"] == ["model-gateway:8081"]


def test_observability_smoke_collects_mocked_api_and_prometheus_evidence(monkeypatch):
    smoke = load_smoke_module()
    required = smoke.required_metric_names()
    api_metric_names = required - {"svs_model_gateway_priced_embedding_profiles"}
    api_metrics_text = "\n".join(f"{name} 1" for name in sorted(api_metric_names)) + "\n"

    def fake_http_get(url: str, *, timeout: float = 10.0) -> str:
        parsed = urlparse(url)
        if parsed.path == "/metrics":
            return api_metrics_text
        if parsed.path == "/api/v1/query":
            query = parse_qs(parsed.query).get("query", [""])[0]
            result = [{"metric": {"__name__": query}, "value": [123, "1"]}] if query in required else []
            return json.dumps({"status": "success", "data": {"resultType": "vector", "result": result}})
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(smoke, "_http_get_text", fake_http_get)

    evidence = smoke.collect_observability_evidence("http://api.local/", "http://prom.local/", cell="unit-cell")

    assert evidence.ok
    assert evidence.cell == "unit-cell"
    assert evidence.api_base == "http://api.local"
    assert set(evidence.api_visible_categories) == set(smoke.REQUIRED_OBSERVABILITY_METRICS)
    assert set(evidence.prometheus_visible_categories) == set(smoke.REQUIRED_OBSERVABILITY_METRICS)
