from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from svs_api import main as api_main
from svs_common.fleet import build_fleet_version_report, expected_services, release_app_images


class _Rows:
    def __init__(self, rows=None, row=None):
        self.rows = rows or []
        self.row = row

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.row


class _FleetDb:
    def __init__(self, *, scopes=None):
        self.scopes = list(scopes or ["admin:read"])
        self.calls = []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        params = params or {}
        self.calls.append((sql, params))
        if "FROM api_keys" in sql and "WHERE key_hash=:key_hash" in sql:
            return _Rows(row={
                "id": "key_admin",
                "tenant_id": "tenant",
                "business_instance_id": "biz_live",
                "user_id": None,
                "scopes": self.scopes,
                "max_security_level": 5,
            })
        if "FROM group_memberships" in sql:
            return _Rows(rows=[])
        if "FROM business_instances" in sql:
            return _Rows(rows=[
                {
                    "id": "biz_live",
                    "name": "Live Business",
                    "slug": "live-business",
                    "deployment_mode": "dedicated_micro_cell",
                    "isolation_level": "business_instance",
                    "config": {"product": {"version": "0.9.8-production-candidate", "registry_prefix": "registry.internal/exais"}},
                    "status": "active",
                    "created_at": 1710000000,
                },
                {
                    "id": "biz_other",
                    "name": "Other Business",
                    "slug": "other-business",
                    "deployment_mode": "shared_micro_cell",
                    "isolation_level": "business_instance",
                    "config": {"product": {"version": "0.9.7-production-candidate"}},
                    "status": "active",
                    "created_at": 1710000100,
                },
            ])
        if "FROM instance_deployments" in sql:
            assert params["tenant_id"] == "tenant"
            assert params["selected_business_id"] == "biz_live"
            return _Rows(rows=[_deployment_row("dep_live", "biz_live")])
        return _Rows()


@pytest.fixture(autouse=True)
def _reset_app_overrides():
    api_main.app.dependency_overrides.clear()
    yield
    api_main.app.dependency_overrides.clear()


def _client(monkeypatch, db):
    monkeypatch.setattr(api_main.settings, "svs_dev_mode", False)
    api_main.app.dependency_overrides[api_main.get_session] = lambda: db
    return TestClient(api_main.app)


def _digest(index: int) -> str:
    return f"sha256:{index:064x}"


def _image_entries(version: str, *, include_digests: bool = True) -> list[dict]:
    entries = []
    for index, (service, (_dockerfile, image_name)) in enumerate(release_app_images().items(), start=1):
        entry = {
            "service": service,
            "image": f"registry.internal/exais/{image_name}:{version}",
            "tag": version,
        }
        if include_digests:
            entry["digest"] = _digest(index)
        entries.append(entry)
    return entries


def _deployment_row(deployment_id: str, business_instance_id: str, *, version: str = "0.9.8-production-candidate", include_digests: bool = True):
    return {
        "id": deployment_id,
        "instance_id": f"inst_{business_instance_id}",
        "business_instance_id": business_instance_id,
        "from_version": "0.9.7-production-candidate",
        "to_version": version,
        "image_digests": {
            "schema_version": 1,
            "product_version": version,
            "registry_prefix": "registry.internal/exais",
            "images": _image_entries(version, include_digests=include_digests),
        },
        "status": "completed",
        "started_at": 1710000200,
        "completed_at": 1710000300,
        "manifest": {"product_version": version, "registry_prefix": "registry.internal/exais"},
        "created_at": 1710000100,
    }


def test_fleet_report_marks_current_stale_and_unverifiable_cells():
    business_rows = [
        {
            "id": "biz_current",
            "name": "Current",
            "slug": "current",
            "deployment_mode": "dedicated_micro_cell",
            "isolation_level": "business_instance",
            "config": {"product": {"version": "0.9.8-production-candidate", "registry_prefix": "registry.internal/exais"}},
            "status": "active",
            "created_at": 1710000000,
        },
        {
            "id": "biz_stale",
            "name": "Stale",
            "slug": "stale",
            "deployment_mode": "dedicated_micro_cell",
            "isolation_level": "business_instance",
            "config": {"product": {"version": "0.9.7-production-candidate", "registry_prefix": "registry.internal/exais"}},
            "status": "active",
            "created_at": 1710000001,
        },
        {
            "id": "biz_unverifiable",
            "name": "Unverifiable",
            "slug": "unverifiable",
            "deployment_mode": "dedicated_micro_cell",
            "isolation_level": "business_instance",
            "config": {"product": {"version": "0.9.8-production-candidate", "registry_prefix": "registry.internal/exais"}},
            "status": "active",
            "created_at": 1710000002,
        },
    ]
    report = build_fleet_version_report(
        tenant_id="tenant",
        product_version="0.9.8-production-candidate",
        business_rows=business_rows,
        deployment_rows=[
            _deployment_row("dep_current", "biz_current"),
            _deployment_row("dep_stale", "biz_stale", version="0.9.7-production-candidate"),
            _deployment_row("dep_unverifiable", "biz_unverifiable", include_digests=False),
        ],
        selected_business_instance_id="biz_current",
        generated_at=1710000400,
    )

    by_id = {instance.id: instance for instance in report.business_instances}
    assert report.expected_services == expected_services()
    assert by_id["biz_current"].verification_status == "current"
    assert by_id["biz_stale"].verification_status == "stale"
    assert "declared_version_behind" in by_id["biz_stale"].issues
    assert by_id["biz_unverifiable"].verification_status == "unverifiable"
    assert "missing_digest" in by_id["biz_unverifiable"].issues
    assert report.evidence_note.endswith("live instance-agent or VPS proof is not claimed.")


def test_admin_fleet_versions_uses_principal_scope_and_rls_queries(monkeypatch):
    db = _FleetDb(scopes=["admin:read"])
    response = _client(monkeypatch, db).get(
        "/api/v1/admin/fleet/versions?business_instance_id=biz_live",
        headers={"Authorization": "Bearer svs_live_admin"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "fleet.version_report"
    assert payload["tenant_id"] == "tenant"
    assert payload["selected_business_instance_id"] == "biz_live"
    assert payload["business_instances"][0]["components"][0]["status"] == "current"
    executed_sql = "\n".join(sql for sql, _params in db.calls)
    assert "FROM business_instances" in executed_sql
    assert "FROM instance_deployments" in executed_sql
    assert "tenant_id=:tenant_id" in executed_sql
    assert "business_instance_id=:selected_business_id" in executed_sql


def test_admin_fleet_versions_requires_admin_or_fleet_scope(monkeypatch):
    response = _client(monkeypatch, _FleetDb(scopes=["documents:read"])).get(
        "/api/v1/admin/fleet/versions",
        headers={"Authorization": "Bearer svs_live_read_only"},
    )

    assert response.status_code == 403
    assert response.json()["detail"]["required"] == ["admin:read", "fleet:read"]
    assert response.json()["detail"]["any_of"] is True


def test_admin_fleet_route_has_named_openapi_response_component():
    api_main.app.openapi_schema = None
    spec = api_main.app.openapi()

    schema = spec["paths"]["/api/v1/admin/fleet/versions"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["$ref"].rsplit("/", 1)[-1] == "FleetVersionReport"


def test_admin_ui_sources_expose_fleet_without_dev_identity_headers():
    root = Path(__file__).resolve().parents[1]
    main_source = (root / "apps/admin_ui/src/main.tsx").read_text()
    fleet_source = (root / "apps/admin_ui/src/fleet.ts").read_text()

    assert "/api/v1/admin/fleet/versions" in main_source
    assert "decorateAdminRequest" in main_source
    assert "FleetVersionReport" in fleet_source
    assert "'unverifiable'" in fleet_source
    assert "x-svs-tenant-id" not in main_source
    assert "localStorage.getItem('svs_tenant')" not in main_source
