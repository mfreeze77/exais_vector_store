from __future__ import annotations

import argparse
from pathlib import Path

from release_common import (
    DEFAULT_CELL,
    all_image_tags,
    compose_base,
    ensure_env,
    normalize_registry_prefix,
    read_env,
    release_manifest_path,
    run,
    wait_for_services,
)
from provenance_common import format_manifest_report, verify_release_manifest

CORE_SERVICES = ["postgres", "redis", "qdrant", "minio", "model-gateway", "api", "worker", "admin-ui"]


def validate_cell_release_manifest(cell: str, manifest_path: Path | None = None) -> None:
    values = read_env(cell)
    product_version = values.get("SVS_VERSION") or values.get("SVS_PRODUCT_VERSION")
    registry_prefix = normalize_registry_prefix(values.get("SVS_REGISTRY_PREFIX"))
    path = manifest_path or release_manifest_path(cell)
    report = verify_release_manifest(path)
    issues: list[str] = []
    if not product_version or product_version == "latest":
        issues.append("SVS_VERSION/SVS_PRODUCT_VERSION must be a fixed VERSION value, not latest")
    if report.product_version and product_version and report.product_version != product_version:
        issues.append(f"manifest product_version {report.product_version!r} does not match cell version {product_version!r}")
    if report.registry_prefix and report.registry_prefix.rstrip("/") != registry_prefix:
        issues.append(f"manifest registry_prefix {report.registry_prefix!r} does not match cell registry {registry_prefix!r}")
    if product_version:
        expected = set(all_image_tags(registry_prefix, product_version))
        actual = {image.image for image in report.images}
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing:
            issues.append("manifest is missing expected cell images: " + ", ".join(missing))
        if extra:
            issues.append("manifest includes images outside the expected cell image set: " + ", ".join(extra))
    if not report.ok or issues:
        print(format_manifest_report(report))
        for issue in issues:
            print(f"- CELL_IMAGE_SET: {issue}")
        raise SystemExit(1)
    print(format_manifest_report(report))


def main() -> None:
    parser = argparse.ArgumentParser(description="Pull and boot a clean local cell from registry images.")
    parser.add_argument("--cell", default=DEFAULT_CELL)
    parser.add_argument("--worker-scale", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--no-wait", action="store_true")
    parser.add_argument("--release-manifest", type=Path, default=None)
    args = parser.parse_args()
    ensure_env(args.cell)
    validate_cell_release_manifest(args.cell, args.release_manifest)
    base = compose_base(args.cell)
    run(base + ["pull", *CORE_SERVICES])
    run(base + ["up", "-d", "--pull", "always", "--scale", f"worker={args.worker_scale}", *CORE_SERVICES])
    if not args.no_wait:
        wait_for_services(args.cell, ["postgres", "redis", "qdrant", "minio", "model-gateway", "api", "worker", "admin-ui"], args.timeout_seconds)
    run(base + ["ps"])


if __name__ == "__main__":
    main()
