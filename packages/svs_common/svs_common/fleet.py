from __future__ import annotations

import importlib.util
import json
import re
import time
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text


DIGEST_RE = re.compile(r"^sha256:[a-fA-F0-9]{64}$")
CURRENT_DEPLOYMENT_STATUSES = {"completed", "deployed", "succeeded", "success", "rolled_back"}
_RELEASE_COMMON: Any | None = None


class FleetComponentVersion(BaseModel):
    model_config = ConfigDict(extra="allow")

    service: str
    status: Literal["current", "stale", "unverifiable"]
    declared_version: str | None = None
    running_version: str | None = None
    image: str | None = None
    expected_image: str | None = None
    digest: str | None = None
    image_id: str | None = None
    source: str
    reasons: list[str] = Field(default_factory=list)


class FleetDeploymentRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    instance_id: str | None = None
    business_instance_id: str | None = None
    from_version: str | None = None
    to_version: str | None = None
    status: str
    image_digests: dict[str, Any] = Field(default_factory=dict)
    manifest: dict[str, Any] = Field(default_factory=dict)
    started_at: int | None = None
    completed_at: int | None = None
    created_at: int | None = None


class FleetBusinessInstance(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    slug: str
    deployment_mode: str | None = None
    isolation_level: str | None = None
    status: str | None = None
    created_at: int | None = None
    vault: dict[str, Any] = Field(default_factory=dict)
    declared_product_version: str | None = None
    latest_deployment: FleetDeploymentRecord | None = None
    components: list[FleetComponentVersion] = Field(default_factory=list)
    verification_status: Literal["current", "stale", "unverifiable"]
    issues: list[str] = Field(default_factory=list)


class FleetVersionReport(BaseModel):
    model_config = ConfigDict(extra="allow")

    object: Literal["fleet.version_report"] = "fleet.version_report"
    tenant_id: str
    selected_business_instance_id: str | None = None
    product_version: str | None = None
    generated_at: int
    expected_services: list[str]
    business_instances: list[FleetBusinessInstance] = Field(default_factory=list)
    deployments: list[FleetDeploymentRecord] = Field(default_factory=list)
    evidence_note: str = (
        "Recorded control-plane state only; live instance-agent or VPS proof is not claimed."
    )


def release_app_images() -> Mapping[str, tuple[str, str]]:
    return dict(_release_common().APP_IMAGES)


def expected_services() -> list[str]:
    return list(release_app_images())


def build_fleet_version_report(
    *,
    tenant_id: str,
    product_version: str | None,
    business_rows: Sequence[Mapping[str, Any]],
    deployment_rows: Sequence[Mapping[str, Any]],
    selected_business_instance_id: str | None = None,
    generated_at: int | None = None,
) -> FleetVersionReport:
    deployments = [_deployment_from_row(row) for row in deployment_rows]
    latest_by_business = _latest_deployment_by_business(deployments)
    instances = [
        _business_instance_from_row(
            row,
            latest_by_business.get(_optional_str(row.get("id")) or ""),
            product_version=product_version,
        )
        for row in business_rows
    ]
    return FleetVersionReport(
        tenant_id=tenant_id,
        selected_business_instance_id=selected_business_instance_id,
        product_version=product_version,
        generated_at=generated_at or int(time.time()),
        expected_services=expected_services(),
        business_instances=instances,
        deployments=deployments,
    )


def record_fleet_version(report: FleetVersionReport, db: Any | None = None) -> FleetVersionReport:
    """Persist deployment records when a caller supplies a DB session.

    RM-009 only reads this contract. Later launch/proof flows can pass a session
    to reuse the same shape for recording deployment evidence.
    """
    if db is None:
        return report
    for deployment in report.deployments:
        db.execute(
            text(
                """
                INSERT INTO instance_deployments(
                    id, instance_id, tenant_id, business_instance_id, from_version, to_version,
                    image_digests, status, started_at, completed_at, manifest, created_at
                )
                VALUES (
                    :id, :instance_id, :tenant_id, :business_instance_id, :from_version, :to_version,
                    CAST(:image_digests AS jsonb), :status,
                    CASE WHEN :started_at IS NULL THEN NULL ELSE to_timestamp(:started_at) END,
                    CASE WHEN :completed_at IS NULL THEN NULL ELSE to_timestamp(:completed_at) END,
                    CAST(:manifest AS jsonb), to_timestamp(:created_at)
                )
                ON CONFLICT (id) DO UPDATE SET
                    from_version=EXCLUDED.from_version,
                    to_version=EXCLUDED.to_version,
                    image_digests=EXCLUDED.image_digests,
                    status=EXCLUDED.status,
                    started_at=EXCLUDED.started_at,
                    completed_at=EXCLUDED.completed_at,
                    manifest=EXCLUDED.manifest
                """
            ),
            {
                "id": deployment.id,
                "instance_id": deployment.instance_id or "",
                "tenant_id": report.tenant_id,
                "business_instance_id": deployment.business_instance_id,
                "from_version": deployment.from_version,
                "to_version": deployment.to_version or report.product_version or "",
                "image_digests": json.dumps(deployment.image_digests),
                "status": deployment.status,
                "started_at": deployment.started_at,
                "completed_at": deployment.completed_at,
                "manifest": json.dumps(deployment.manifest),
                "created_at": deployment.created_at or report.generated_at,
            },
        )
    return report


def _business_instance_from_row(
    row: Mapping[str, Any],
    deployment: FleetDeploymentRecord | None,
    *,
    product_version: str | None,
) -> FleetBusinessInstance:
    config = _json_mapping(row.get("config"))
    declared_product_version = _declared_product_version(config, deployment)
    components = _components_for_instance(config, deployment, product_version=product_version)
    issues = sorted({reason for component in components for reason in component.reasons})
    return FleetBusinessInstance(
        id=_required_str(row.get("id"), "business instance id"),
        name=_optional_str(row.get("name")) or _required_str(row.get("id"), "business instance id"),
        slug=_optional_str(row.get("slug")) or _required_str(row.get("id"), "business instance id"),
        deployment_mode=_optional_str(row.get("deployment_mode")),
        isolation_level=_optional_str(row.get("isolation_level")),
        status=_optional_str(row.get("status")),
        created_at=_optional_int(row.get("created_at")),
        vault=_vault_from_config(config),
        declared_product_version=declared_product_version,
        latest_deployment=deployment,
        components=components,
        verification_status=_aggregate_status(components),
        issues=issues,
    )


def _components_for_instance(
    config: Mapping[str, Any],
    deployment: FleetDeploymentRecord | None,
    *,
    product_version: str | None,
) -> list[FleetComponentVersion]:
    image_entries = _image_entries(deployment.image_digests, deployment.manifest) if deployment else {}
    declared_product_version = _declared_product_version(config, deployment)
    registry_prefix = _registry_prefix(config, deployment, image_entries)
    components: list[FleetComponentVersion] = []
    for service in expected_services():
        entry = image_entries.get(service, {})
        declared_version = (
            _optional_str(entry.get("tag"))
            or _version_from_image(_optional_str(entry.get("image")))
            or declared_product_version
        )
        running_version = _optional_str(entry.get("running_version")) or _optional_str(entry.get("runningVersion"))
        image = _optional_str(entry.get("image"))
        digest = _optional_str(entry.get("digest")) or _digest_from_image(image)
        image_id = _optional_str(entry.get("image_id")) or _optional_str(entry.get("imageId"))
        expected_image = _expected_image(service, registry_prefix, declared_version or product_version)
        reasons: list[str] = []
        stale = False

        if deployment is None:
            reasons.append("no_visible_deployment_record")
        elif deployment.status.lower() not in CURRENT_DEPLOYMENT_STATUSES:
            reasons.append(f"deployment_status_{deployment.status.lower()}")
        if not entry:
            reasons.append("missing_image_metadata")
        if digest:
            if not DIGEST_RE.match(digest):
                reasons.append("invalid_digest")
        else:
            reasons.append("missing_digest")
        if not declared_version:
            reasons.append("missing_declared_version")
        if product_version and declared_version and declared_version != product_version:
            reasons.append("declared_version_behind")
            stale = True
        if running_version and declared_version and running_version != declared_version:
            reasons.append("running_version_mismatch")
            stale = True

        status: Literal["current", "stale", "unverifiable"]
        if stale:
            status = "stale"
        elif reasons:
            status = "unverifiable"
        else:
            status = "current"

        components.append(
            FleetComponentVersion(
                service=service,
                status=status,
                declared_version=declared_version,
                running_version=running_version,
                image=image,
                expected_image=expected_image,
                digest=digest,
                image_id=image_id,
                source="instance_deployments" if deployment else "business_instances.config",
                reasons=reasons,
            )
        )
    return components


def _deployment_from_row(row: Mapping[str, Any]) -> FleetDeploymentRecord:
    return FleetDeploymentRecord(
        id=_required_str(row.get("id"), "deployment id"),
        instance_id=_optional_str(row.get("instance_id")),
        business_instance_id=_optional_str(row.get("business_instance_id")),
        from_version=_optional_str(row.get("from_version")),
        to_version=_optional_str(row.get("to_version")),
        image_digests=_json_mapping(row.get("image_digests")),
        status=_optional_str(row.get("status")) or "unknown",
        started_at=_optional_int(row.get("started_at")),
        completed_at=_optional_int(row.get("completed_at")),
        manifest=_json_mapping(row.get("manifest")),
        created_at=_optional_int(row.get("created_at")),
    )


def _latest_deployment_by_business(deployments: Sequence[FleetDeploymentRecord]) -> dict[str, FleetDeploymentRecord]:
    latest: dict[str, FleetDeploymentRecord] = {}
    for deployment in deployments:
        business_id = deployment.business_instance_id
        if not business_id:
            continue
        current = latest.get(business_id)
        if current is None or _deployment_sort_key(deployment) > _deployment_sort_key(current):
            latest[business_id] = deployment
    return latest


def _deployment_sort_key(deployment: FleetDeploymentRecord) -> tuple[int, str]:
    return (
        deployment.completed_at or deployment.started_at or deployment.created_at or 0,
        deployment.id,
    )


def _image_entries(image_digests: Mapping[str, Any], manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    entries: dict[str, dict[str, Any]] = {}
    for source in (manifest, image_digests):
        raw_images = source.get("images")
        if isinstance(raw_images, list):
            for raw in raw_images:
                if isinstance(raw, Mapping):
                    _add_image_entry(entries, dict(raw))
    for key, value in image_digests.items():
        if key in {"images", "schema_version", "generated_at", "services", "product_version", "registry_prefix"}:
            continue
        if isinstance(value, str):
            service = _service_name(key) or _service_from_image(key)
            if service:
                _add_image_entry(entries, {"service": service, "digest": value})
        elif isinstance(value, Mapping):
            raw = dict(value)
            raw.setdefault("service", _service_name(key) or _service_from_image(_optional_str(raw.get("image")) or key))
            _add_image_entry(entries, raw)
    return entries


def _add_image_entry(entries: dict[str, dict[str, Any]], raw: dict[str, Any]) -> None:
    service = _service_name(_optional_str(raw.get("service")) or "") or _service_from_image(_optional_str(raw.get("image")))
    if not service:
        return
    entries[service] = raw


def _declared_product_version(config: Mapping[str, Any], deployment: FleetDeploymentRecord | None) -> str | None:
    product = _json_mapping(config.get("product"))
    return (
        _optional_str(product.get("version"))
        or _optional_str(product.get("product_version"))
        or _optional_str(product.get("productVersion"))
        or (deployment.to_version if deployment else None)
    )


def _registry_prefix(
    config: Mapping[str, Any],
    deployment: FleetDeploymentRecord | None,
    image_entries: Mapping[str, Mapping[str, Any]],
) -> str | None:
    product = _json_mapping(config.get("product"))
    runtime = _json_mapping(config.get("runtime"))
    manifest = deployment.manifest if deployment else {}
    explicit = (
        _optional_str(product.get("registry_prefix"))
        or _optional_str(product.get("registryPrefix"))
        or _optional_str(runtime.get("registry_prefix"))
        or _optional_str(runtime.get("registryPrefix"))
        or _optional_str(manifest.get("registry_prefix"))
    )
    if explicit:
        return explicit.rstrip("/")
    for entry in image_entries.values():
        prefix = _registry_prefix_from_image(_optional_str(entry.get("image")))
        if prefix:
            return prefix
    return None


def _vault_from_config(config: Mapping[str, Any]) -> dict[str, Any]:
    for key in ("vault", "business_vault", "businessVault"):
        value = config.get(key)
        if isinstance(value, Mapping):
            return dict(value)
        if isinstance(value, str) and value:
            return {"id": value}
    return {}


def _expected_image(service: str, registry_prefix: str | None, product_version: str | None) -> str | None:
    if not registry_prefix or not product_version:
        return None
    try:
        return _release_common().image_tag(service, registry_prefix, product_version)
    except Exception:
        return None


def _service_name(value: str) -> str | None:
    return value if value in release_app_images() else None


def _service_from_image(image: str | None) -> str | None:
    if not image:
        return None
    name = image.rsplit("/", 1)[-1].split("@", 1)[0].split(":", 1)[0]
    for service, (_dockerfile, image_name) in release_app_images().items():
        if name == image_name:
            return service
    return None


def _version_from_image(image: str | None) -> str | None:
    if not image:
        return None
    tail = image.rsplit("/", 1)[-1]
    if ":" not in tail:
        return None
    return tail.rsplit(":", 1)[-1].split("@", 1)[0] or None


def _digest_from_image(image: str | None) -> str | None:
    if not image or "@sha256:" not in image:
        return None
    return "sha256:" + image.rsplit("@sha256:", 1)[-1]


def _registry_prefix_from_image(image: str | None) -> str | None:
    if not image or "/" not in image:
        return None
    repository = image.rsplit("/", 1)[0]
    return repository.rstrip("/") or None


def _aggregate_status(components: Sequence[FleetComponentVersion]) -> Literal["current", "stale", "unverifiable"]:
    statuses = {component.status for component in components}
    if "stale" in statuses:
        return "stale"
    if "unverifiable" in statuses:
        return "unverifiable"
    return "current"


def _json_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str) and value:
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(decoded) if isinstance(decoded, Mapping) else {}
    return {}


def _optional_str(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _required_str(value: Any, label: str) -> str:
    text_value = _optional_str(value)
    if not text_value:
        raise ValueError(f"missing {label}")
    return text_value


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _release_common() -> Any:
    global _RELEASE_COMMON
    if _RELEASE_COMMON is not None:
        return _RELEASE_COMMON
    path = Path(__file__).resolve().parents[3] / "scripts" / "release" / "release_common.py"
    spec = importlib.util.spec_from_file_location("_svs_release_common_for_fleet", path)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load release_common.py from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _RELEASE_COMMON = module
    return module
