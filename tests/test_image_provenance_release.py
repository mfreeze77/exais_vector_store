from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


RELEASE_DIR = Path(__file__).resolve().parents[1] / "scripts" / "release"
sys.path.insert(0, str(RELEASE_DIR))

from provenance_common import ImageDigest, verify_release_manifest, write_release_manifest  # noqa: E402
from release_common import APP_IMAGES, all_image_tags  # noqa: E402


def load_release_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, RELEASE_DIR / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def digest(index: int) -> str:
    return f"sha256:{index:064x}"


def manifest_images(registry_prefix: str = "registry.internal/exais", version: str = "0.9.8-production-candidate") -> list[ImageDigest]:
    images: list[ImageDigest] = []
    for index, (service, image) in enumerate(zip(APP_IMAGES, all_image_tags(registry_prefix, version)), start=1):
        images.append(
            ImageDigest(
                service=service,
                image=image,
                tag=version,
                digest=digest(index),
                image_id=digest(index + 20),
                size=1000 + index,
                labels={
                    "org.opencontainers.image.version": version,
                    "com.exais.service": service,
                },
                provenance={"source": "unit-test", "digest_source": "unit-test"},
            )
        )
    return images


def issue_codes(report):
    return {issue.code for issue in report.issues}


def test_release_manifest_round_trips_full_app_image_set(tmp_path):
    path = write_release_manifest(manifest_images(), tmp_path / "release-manifest.json")

    report = verify_release_manifest(path)

    assert report.ok
    assert [image.service for image in report.images] == list(APP_IMAGES)
    assert report.product_version == "0.9.8-production-candidate"
    assert report.registry_prefix == "registry.internal/exais"


def test_release_manifest_rejects_unpinned_missing_and_unverifiable_images(tmp_path):
    images = manifest_images()
    images[0] = ImageDigest(
        service="api",
        image="registry.internal/exais/exai-vector-store-api:latest",
        tag="latest",
        labels={"com.exais.service": "api"},
    )
    path = write_release_manifest(images[:-1], tmp_path / "release-manifest.json")

    report = verify_release_manifest(path)

    assert {"LATEST_TAG", "MISSING_DIGEST", "MISSING_SERVICE", "MISSING_PROVENANCE"} <= issue_codes(report)


def test_release_manifest_rejects_mixed_version_and_registry(tmp_path):
    images = manifest_images()
    images[1] = ImageDigest(
        service="worker",
        image="other.registry/exais/exai-vector-store-worker:0.9.7-production-candidate",
        tag="0.9.7-production-candidate",
        digest=digest(2),
        image_id=digest(22),
        labels={
            "org.opencontainers.image.version": "0.9.7-production-candidate",
            "com.exais.service": "worker",
        },
        provenance={"source": "unit-test", "digest_source": "unit-test"},
    )
    path = write_release_manifest(images, tmp_path / "release-manifest.json")

    report = verify_release_manifest(path)

    assert {
        "MISSING_PRODUCT_VERSION",
        "MISSING_REGISTRY_PREFIX",
        "MIXED_VERSION_TAGS",
        "MIXED_IMAGE_REFERENCE_TAGS",
        "MIXED_REGISTRY_PREFIXES",
    } <= issue_codes(report)


def test_cell_up_validates_manifest_against_generated_cell_env(tmp_path, monkeypatch):
    cell_up = load_release_script("cell_up_for_provenance_test", "cell-up.py")
    path = write_release_manifest(manifest_images("localhost:5000/expertaiservices"), tmp_path / "release-manifest.json")
    monkeypatch.setattr(
        cell_up,
        "read_env",
        lambda cell: {
            "SVS_VERSION": "0.9.8-production-candidate",
            "SVS_REGISTRY_PREFIX": "localhost:5000/expertaiservices",
        },
    )

    cell_up.validate_cell_release_manifest("unit", path)


def test_cell_up_rejects_manifest_for_wrong_registry(tmp_path, monkeypatch):
    cell_up = load_release_script("cell_up_for_wrong_registry_test", "cell-up.py")
    path = write_release_manifest(manifest_images("registry.internal/exais"), tmp_path / "release-manifest.json")
    monkeypatch.setattr(
        cell_up,
        "read_env",
        lambda cell: {
            "SVS_VERSION": "0.9.8-production-candidate",
            "SVS_REGISTRY_PREFIX": "localhost:5000/expertaiservices",
        },
    )

    with pytest.raises(SystemExit):
        cell_up.validate_cell_release_manifest("unit", path)


def test_build_image_inspection_writes_local_digest_metadata(monkeypatch):
    build_images = load_release_script("build_images_for_provenance_test", "build-images.py")
    version = "0.9.8-production-candidate"
    image_id = digest(100)
    stdout = (
        f'{image_id}\t1234\t[]\t{{"org.opencontainers.image.version":"{version}",'
        '"com.exais.service":"api"}\n'
    )
    monkeypatch.setattr(build_images, "run", lambda args: SimpleNamespace(stdout=stdout))

    image = build_images.inspect_built_image("api", f"registry.internal/exais/exai-vector-store-api:{version}", version)

    assert image.digest == image_id
    assert image.provenance["digest_source"] == "local_image_id"
    assert image.labels["com.exais.service"] == "api"
