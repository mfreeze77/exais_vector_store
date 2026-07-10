from __future__ import annotations

import argparse
import sys
from pathlib import Path

from release_common import (
    DEFAULT_CELL,
    all_image_tags,
    compose_base,
    ensure_app_images_available,
    ensure_env,
    env_file,
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
from secret_runtime import cleanup_runtime_secret_env, is_production_environment, runtime_env_path

INFRA_SERVICES = ["postgres", "redis", "qdrant", "minio"]
CORE_SERVICES = [*INFRA_SERVICES, "model-gateway", "api", "worker", "admin-ui"]
PRODUCTION_PREFLIGHT = Path(__file__).with_name("prod-env-preflight.py")


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


def prepare_cell_environment(cell: str, *, allow_local_registry: bool = False) -> Path:
    source_path = env_file(cell)
    values = read_env(cell)
    if is_production_environment(values):
        command = [sys.executable, str(PRODUCTION_PREFLIGHT), "--env-file", str(source_path)]
        if allow_local_registry:
            command.append("--allow-local-registry")
        run(command)
    return runtime_env_path(source_path)


def start_cell(
    *,
    cell: str,
    worker_scale: int,
    timeout_seconds: int,
    no_wait: bool,
    release_manifest: Path | None,
    allow_local_registry: bool,
) -> None:
    ensure_env(cell)
    pins_path = pinned_image_env_file(cell)
    previous_pins = pins_path.read_bytes() if pins_path.exists() else None
    activated = False
    try:
        prepared_env_path = prepare_cell_environment(
            cell,
            allow_local_registry=allow_local_registry,
        )
        activate_cell_release(cell, release_manifest)
        activated = True
        base = compose_base(cell, prepared_env_path=prepared_env_path)
        run(base + ["pull", *INFRA_SERVICES])
        run(base + ["up", "-d", "--pull", "never", "--scale", f"worker={worker_scale}", *CORE_SERVICES])
        if not no_wait:
            wait_for_services(cell, ["postgres", "redis", "qdrant", "minio", "model-gateway", "api", "worker", "admin-ui"], timeout_seconds)
        run(base + ["ps"])
    except BaseException:
        if activated:
            restore_pinned_image_env_file(pins_path, previous_pins)
        raise
    finally:
        cleanup_runtime_secret_env(env_file(cell))


def main() -> None:
    parser = argparse.ArgumentParser(description="Pull and boot a digest-pinned cell from registry images.")
    parser.add_argument("--cell", default=DEFAULT_CELL)
    parser.add_argument("--worker-scale", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--no-wait", action="store_true")
    parser.add_argument("--release-manifest", type=Path, default=None)
    parser.add_argument("--allow-local-registry", action="store_true")
    args = parser.parse_args()
    start_cell(
        cell=args.cell,
        worker_scale=args.worker_scale,
        timeout_seconds=args.timeout_seconds,
        no_wait=args.no_wait,
        release_manifest=args.release_manifest,
        allow_local_registry=args.allow_local_registry,
    )


if __name__ == "__main__":
    main()
