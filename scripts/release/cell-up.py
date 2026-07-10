from __future__ import annotations

import argparse
from pathlib import Path

from release_common import (
    DEFAULT_CELL,
    all_image_tags,
    compose_base,
    ensure_app_images_available,
    ensure_env,
    normalize_registry_prefix,
    pinned_image_env_file,
    read_env,
    release_manifest_path,
    restore_pinned_image_env_file,
    run,
    wait_for_services,
    write_pinned_image_env,
)
from provenance_common import format_manifest_report, release_image_references, verify_release_manifest

INFRA_SERVICES = ["postgres", "redis", "qdrant", "minio"]
CORE_SERVICES = [*INFRA_SERVICES, "model-gateway", "api", "worker", "admin-ui"]


def validate_cell_release_manifest(cell: str, manifest_path: Path | None = None) -> dict[str, str]:
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
    image_references: dict[str, str] = {}
    if report.ok:
        try:
            image_references = release_image_references(report)
        except ValueError as exc:
            issues.append(str(exc))
    if not report.ok or issues:
        print(format_manifest_report(report))
        for issue in issues:
            print(f"- CELL_IMAGE_SET: {issue}")
        raise SystemExit(1)
    print(format_manifest_report(report))
    return image_references


def activate_cell_release(cell: str, manifest_path: Path | None = None) -> dict[str, str]:
    image_references = validate_cell_release_manifest(cell, manifest_path)
    ensure_app_images_available(image_references)
    pins_path = write_pinned_image_env(cell, image_references)
    print(f"Activated immutable image pins: {pins_path}")
    return image_references


def main() -> None:
    parser = argparse.ArgumentParser(description="Pull and boot a clean local cell from registry images.")
    parser.add_argument("--cell", default=DEFAULT_CELL)
    parser.add_argument("--worker-scale", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--no-wait", action="store_true")
    parser.add_argument("--release-manifest", type=Path, default=None)
    args = parser.parse_args()
    ensure_env(args.cell)
    pins_path = pinned_image_env_file(args.cell)
    previous_pins = pins_path.read_bytes() if pins_path.exists() else None
    activated = False
    try:
        activate_cell_release(args.cell, args.release_manifest)
        activated = True
        base = compose_base(args.cell)
        run(base + ["pull", *INFRA_SERVICES])
        run(base + ["up", "-d", "--pull", "never", "--scale", f"worker={args.worker_scale}", *CORE_SERVICES])
        if not args.no_wait:
            wait_for_services(args.cell, ["postgres", "redis", "qdrant", "minio", "model-gateway", "api", "worker", "admin-ui"], args.timeout_seconds)
        run(base + ["ps"])
    except BaseException:
        if activated:
            restore_pinned_image_env_file(pins_path, previous_pins)
        raise


if __name__ == "__main__":
    main()
