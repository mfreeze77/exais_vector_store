from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from release_common import APP_IMAGES

MANIFEST_SCHEMA_VERSION = 1
IMAGE_SET_AUTHORITY = "scripts/release/release_common.py:APP_IMAGES"
DIGEST_RE = re.compile(r"^sha256:[a-fA-F0-9]{64}$")


@dataclass(frozen=True)
class ImageDigest:
    service: str
    image: str
    tag: str
    digest: str | None = None
    image_id: str | None = None
    size: int | None = None
    labels: Mapping[str, str] = field(default_factory=dict)
    provenance: Mapping[str, str] = field(default_factory=dict)

    def to_manifest(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "service": self.service,
            "image": self.image,
            "tag": self.tag,
        }
        if self.digest:
            data["digest"] = self.digest
        if self.image_id:
            data["image_id"] = self.image_id
        if self.size is not None:
            data["size"] = self.size
        if self.labels:
            data["labels"] = dict(sorted(self.labels.items()))
        if self.provenance:
            data["provenance"] = dict(sorted(self.provenance.items()))
        return data

    @classmethod
    def from_manifest(cls, value: Mapping[str, Any]) -> "ImageDigest":
        return cls(
            service=str(value.get("service", "")),
            image=str(value.get("image", "")),
            tag=str(value.get("tag", "")),
            digest=_optional_str(value.get("digest")),
            image_id=_optional_str(value.get("image_id")),
            size=_optional_int(value.get("size")),
            labels=_str_mapping(value.get("labels")),
            provenance=_str_mapping(value.get("provenance")),
        )


@dataclass(frozen=True)
class ManifestIssue:
    code: str
    message: str
    service: str | None = None


@dataclass(frozen=True)
class ReleaseManifestReport:
    manifest_path: Path
    images: tuple[ImageDigest, ...] = ()
    issues: tuple[ManifestIssue, ...] = ()
    product_version: str | None = None
    registry_prefix: str | None = None
    schema_version: int | None = None

    @property
    def ok(self) -> bool:
        return not self.issues


def write_release_manifest(images: list[ImageDigest], destination: Path) -> Path:
    ordered = sorted(images, key=lambda image: list(APP_IMAGES).index(image.service) if image.service in APP_IMAGES else len(APP_IMAGES))
    product_version = _common_value([image.tag for image in ordered if image.tag])
    registry_prefix = _common_value([_registry_prefix_from_image(image.image) for image in ordered if _registry_prefix_from_image(image.image)])
    payload = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "image_set_authority": IMAGE_SET_AUTHORITY,
        "product_version": product_version,
        "registry_prefix": registry_prefix,
        "services": list(APP_IMAGES),
        "images": [image.to_manifest() for image in ordered],
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination


def verify_release_manifest(manifest_path: Path, *, require_digests: bool = True) -> ReleaseManifestReport:
    issues: list[ManifestIssue] = []
    images: list[ImageDigest] = []
    product_version: str | None = None
    registry_prefix: str | None = None
    schema_version: int | None = None

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ReleaseManifestReport(manifest_path, issues=(ManifestIssue("MISSING_MANIFEST", f"release manifest not found: {manifest_path}"),))
    except json.JSONDecodeError as exc:
        return ReleaseManifestReport(manifest_path, issues=(ManifestIssue("BAD_JSON", f"release manifest is not valid JSON: {exc}"),))

    if not isinstance(data, dict):
        return ReleaseManifestReport(manifest_path, issues=(ManifestIssue("BAD_MANIFEST", "release manifest must be a JSON object"),))

    raw_schema_version = data.get("schema_version")
    if isinstance(raw_schema_version, int):
        schema_version = raw_schema_version
    else:
        issues.append(ManifestIssue("BAD_SCHEMA_VERSION", "schema_version must be an integer"))
    if schema_version != MANIFEST_SCHEMA_VERSION:
        issues.append(ManifestIssue("UNSUPPORTED_SCHEMA_VERSION", f"expected schema_version {MANIFEST_SCHEMA_VERSION}, got {raw_schema_version!r}"))

    if data.get("image_set_authority") != IMAGE_SET_AUTHORITY:
        issues.append(ManifestIssue("BAD_IMAGE_SET_AUTHORITY", f"image_set_authority must be {IMAGE_SET_AUTHORITY}"))

    raw_product_version = data.get("product_version")
    if isinstance(raw_product_version, str) and raw_product_version:
        product_version = raw_product_version
    else:
        issues.append(ManifestIssue("MISSING_PRODUCT_VERSION", "manifest must include a fixed product_version"))
    raw_registry_prefix = data.get("registry_prefix")
    if isinstance(raw_registry_prefix, str) and raw_registry_prefix:
        registry_prefix = raw_registry_prefix.rstrip("/")
    else:
        issues.append(ManifestIssue("MISSING_REGISTRY_PREFIX", "manifest must include a registry_prefix"))

    if data.get("services") != list(APP_IMAGES):
        issues.append(ManifestIssue("BAD_SERVICE_SET", f"services must match {IMAGE_SET_AUTHORITY}"))

    raw_images = data.get("images")
    if not isinstance(raw_images, list):
        issues.append(ManifestIssue("BAD_IMAGES", "images must be a list"))
        raw_images = []

    for raw in raw_images:
        if not isinstance(raw, dict):
            issues.append(ManifestIssue("BAD_IMAGE_ENTRY", "each image entry must be an object"))
            continue
        image = ImageDigest.from_manifest(raw)
        images.append(image)
        issues.extend(_verify_image_entry(image, product_version=product_version, registry_prefix=registry_prefix, require_digests=require_digests))

    services = [image.service for image in images]
    for service in APP_IMAGES:
        if service not in services:
            issues.append(ManifestIssue("MISSING_SERVICE", f"manifest is missing image metadata for {service}", service))
    for service in sorted(set(services) - set(APP_IMAGES)):
        issues.append(ManifestIssue("UNKNOWN_SERVICE", f"manifest includes unknown service {service}", service))
    for service in sorted({service for service in services if services.count(service) > 1}):
        issues.append(ManifestIssue("DUPLICATE_SERVICE", f"manifest includes duplicate image metadata for {service}", service))

    inferred_versions = {image.tag for image in images if image.tag}
    if len(inferred_versions) > 1:
        issues.append(ManifestIssue("MIXED_VERSION_TAGS", "manifest image tags do not agree on one product_version"))
    parsed_versions = {_split_image_tag(image.image)[1] for image in images if _split_image_tag(image.image)[1]}
    if len(parsed_versions) > 1:
        issues.append(ManifestIssue("MIXED_IMAGE_REFERENCE_TAGS", "manifest image references do not agree on one product_version"))
    if product_version in {"", "latest"}:
        issues.append(ManifestIssue("UNPINNED_VERSION", "product_version must be a fixed VERSION value, not latest"))

    inferred_prefixes = {_registry_prefix_from_image(image.image) for image in images if _registry_prefix_from_image(image.image)}
    if len(inferred_prefixes) > 1:
        issues.append(ManifestIssue("MIXED_REGISTRY_PREFIXES", "manifest image references do not agree on one registry_prefix"))

    return ReleaseManifestReport(
        manifest_path=manifest_path,
        images=tuple(images),
        issues=tuple(issues),
        product_version=product_version,
        registry_prefix=registry_prefix,
        schema_version=schema_version,
    )


def format_manifest_report(report: ReleaseManifestReport) -> str:
    if report.ok:
        return f"Release manifest verified: {report.manifest_path}"
    lines = [f"Release manifest verification failed: {report.manifest_path}"]
    for issue in report.issues:
        service = f" [{issue.service}]" if issue.service else ""
        lines.append(f"- {issue.code}{service}: {issue.message}")
    return "\n".join(lines)


def _verify_image_entry(
    image: ImageDigest,
    *,
    product_version: str | None,
    registry_prefix: str | None,
    require_digests: bool,
) -> list[ManifestIssue]:
    issues: list[ManifestIssue] = []
    service = image.service
    if service not in APP_IMAGES:
        return issues

    expected_name = APP_IMAGES[service][1]
    repository, parsed_tag = _split_image_tag(image.image)
    parsed_prefix = _registry_prefix_from_image(image.image)
    if not repository or not parsed_tag:
        issues.append(ManifestIssue("UNPINNED_IMAGE", f"{service} image must include an explicit version tag", service))
    elif parsed_tag == "latest":
        issues.append(ManifestIssue("LATEST_TAG", f"{service} image must not use latest", service))
    elif product_version and parsed_tag != product_version:
        issues.append(ManifestIssue("TAG_VERSION_MISMATCH", f"{service} image tag {parsed_tag!r} does not match manifest product_version {product_version!r}", service))

    if not image.tag:
        issues.append(ManifestIssue("MISSING_IMAGE_TAG", f"{service} image metadata must include the product version tag", service))
    if image.tag and parsed_tag and image.tag != parsed_tag:
        issues.append(ManifestIssue("IMAGE_TAG_MISMATCH", f"{service} tag field {image.tag!r} does not match image reference tag {parsed_tag!r}", service))

    if repository and repository.rsplit("/", 1)[-1] != expected_name:
        issues.append(ManifestIssue("IMAGE_NAME_MISMATCH", f"{service} image must end with {expected_name}", service))
    if registry_prefix and parsed_prefix and parsed_prefix != registry_prefix:
        issues.append(ManifestIssue("REGISTRY_PREFIX_MISMATCH", f"{service} image registry {parsed_prefix!r} does not match manifest registry_prefix {registry_prefix!r}", service))

    if require_digests and not _valid_digest(image.digest):
        issues.append(ManifestIssue("MISSING_DIGEST", f"{service} image must include a sha256 digest", service))
    if image.digest and not _valid_digest(image.digest):
        issues.append(ManifestIssue("BAD_DIGEST", f"{service} digest is not a sha256 digest", service))
    if image.image_id and not _valid_digest(image.image_id):
        issues.append(ManifestIssue("BAD_IMAGE_ID", f"{service} image_id is not a sha256 digest", service))

    label_version = image.labels.get("org.opencontainers.image.version")
    if label_version and product_version and label_version != product_version:
        issues.append(ManifestIssue("LABEL_VERSION_MISMATCH", f"{service} OCI version label {label_version!r} does not match {product_version!r}", service))
    label_service = image.labels.get("com.exais.service")
    if label_service and label_service != service:
        issues.append(ManifestIssue("LABEL_SERVICE_MISMATCH", f"{service} service label is {label_service!r}", service))
    if not image.provenance:
        issues.append(ManifestIssue("MISSING_PROVENANCE", f"{service} image must include provenance metadata", service))
    elif not image.provenance.get("source"):
        issues.append(ManifestIssue("MISSING_PROVENANCE_SOURCE", f"{service} provenance must include a source", service))
    return issues


def _split_image_tag(image: str) -> tuple[str | None, str | None]:
    if not image:
        return None, None
    tail = image.rsplit("/", 1)[-1]
    if ":" not in tail:
        return image, None
    repository, tag = image.rsplit(":", 1)
    return repository, tag or None


def _registry_prefix_from_image(image: str) -> str | None:
    repository, _tag = _split_image_tag(image)
    if not repository or "/" not in repository:
        return None
    return repository.rsplit("/", 1)[0].rstrip("/")


def _valid_digest(value: str | None) -> bool:
    return bool(value and DIGEST_RE.match(value))


def _common_value(values: Sequence[str]) -> str | None:
    unique = {value for value in values if value}
    if len(unique) == 1:
        return next(iter(unique))
    return None


def _optional_str(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _str_mapping(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(k): str(v) for k, v in value.items() if v is not None}


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify an ExAIS release image manifest.")
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--allow-missing-digests", action="store_true")
    args = parser.parse_args()
    report = verify_release_manifest(args.manifest, require_digests=not args.allow_missing_digests)
    print(format_manifest_report(report))
    if not report.ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
