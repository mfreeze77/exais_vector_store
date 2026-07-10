from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


RELEASE_DIR = Path(__file__).resolve().parents[1] / "scripts" / "release"
sys.path.insert(0, str(RELEASE_DIR))

import release_common  # noqa: E402
import provenance_common  # noqa: E402
from provenance_common import (  # noqa: E402
    ImageDigest,
    release_image_references,
    verify_release_manifest,
    write_release_manifest,
)
from release_common import APP_IMAGE_ENV_VARS, APP_IMAGES, all_image_tags  # noqa: E402


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
        image_digest = digest(index)
        images.append(
            ImageDigest(
                service=service,
                image=image,
                tag=version,
                digest=image_digest,
                image_id=digest(index + 20),
                size=1000 + index,
                labels={
                    "org.opencontainers.image.version": version,
                    "com.exais.service": service,
                },
                provenance={
                    "source": "unit-test",
                    "digest_source": "repository_digest",
                    "repository_digest": f"{image.rsplit(':', 1)[0]}@{image_digest}",
                },
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


def test_release_manifest_atomic_replace_preserves_previous_manifest_on_interruption(tmp_path, monkeypatch):
    path = tmp_path / "release-manifest.json"
    previous = b'{"approved":"previous"}\n'
    path.write_bytes(previous)

    def interrupted_replace(source, destination):
        raise OSError("simulated activation interruption")

    monkeypatch.setattr(provenance_common.os, "replace", interrupted_replace)

    with pytest.raises(OSError, match="simulated activation interruption"):
        write_release_manifest(manifest_images(), path)

    assert path.read_bytes() == previous
    assert not path.with_name(path.name + ".tmp").exists()


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
        provenance={
            "source": "unit-test",
            "digest_source": "repository_digest",
            "repository_digest": f"other.registry/exais/exai-vector-store-worker@{digest(2)}",
        },
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

    references = cell_up.validate_cell_release_manifest("unit", path)

    assert list(references) == list(APP_IMAGES)
    assert all("@sha256:" in reference for reference in references.values())
    assert all(":0.9.8-production-candidate" not in reference for reference in references.values())


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


def test_publish_writes_manifest_without_mutating_active_pins(tmp_path, monkeypatch):
    publish_images = load_release_script("publish_images_manifest_only_test", "publish-images.py")
    registry_prefix = "registry.internal/exais"
    product_version = "0.9.8-production-candidate"
    images = {image.service: image for image in manifest_images(registry_prefix, product_version)}
    manifest_path = tmp_path / "release-manifest.json"
    active_pins = tmp_path / ".env.images"
    previous = b"previous-active-pin-bytes\n"
    active_pins.write_bytes(previous)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "publish-images.py",
            "--registry-prefix",
            registry_prefix,
            "--version",
            product_version,
            "--manifest-output",
            str(manifest_path),
        ],
    )
    monkeypatch.setattr(publish_images, "run", lambda args, **kwargs: SimpleNamespace(returncode=0, stdout=""))
    monkeypatch.setattr(publish_images, "inspect_manifest", lambda tag, prefix: None)
    monkeypatch.setattr(
        publish_images,
        "inspect_published_image",
        lambda service, tag, selected_version, prefix: images[service],
    )

    publish_images.main()

    assert verify_release_manifest(manifest_path).ok
    assert active_pins.read_bytes() == previous


def test_cell_image_references_reject_bare_local_image_id_provenance(tmp_path):
    images = manifest_images()
    images[0] = ImageDigest(
        **{
            **images[0].__dict__,
            "provenance": {"source": "docker-build", "digest_source": "local_image_id"},
        }
    )
    report = verify_release_manifest(write_release_manifest(images, tmp_path / "release-manifest.json"))

    with pytest.raises(ValueError, match="local image IDs cannot pin cell startup"):
        release_image_references(report)


def test_cell_image_references_reject_mismatched_repository_digest(tmp_path):
    images = manifest_images()
    images[0] = ImageDigest(
        **{
            **images[0].__dict__,
            "provenance": {
                "source": "docker-build",
                "digest_source": "repository_digest",
                "repository_digest": f"registry.internal/exais/exai-vector-store-api@{digest(999)}",
            },
        }
    )
    report = verify_release_manifest(write_release_manifest(images, tmp_path / "release-manifest.json"))

    with pytest.raises(ValueError, match="does not match the manifest digest"):
        release_image_references(report)


def test_compose_base_requires_persistent_digest_pins(tmp_path, monkeypatch):
    monkeypatch.setattr(release_common, "release_dir", lambda cell: tmp_path / cell)
    monkeypatch.setattr(release_common, "compose_cmd", lambda: ["docker", "compose"])
    cell_env = release_common.env_file("unit")
    cell_env.parent.mkdir(parents=True)
    cell_env.write_text("SVS_REGISTRY_PREFIX=registry.internal/exais\n", encoding="utf-8")
    manifest_path = write_release_manifest(manifest_images(), tmp_path / "release-manifest.json")
    references = release_image_references(verify_release_manifest(manifest_path))

    pins_path = release_common.write_pinned_image_env("unit", references)
    base = release_common.compose_base("unit")

    assert pins_path == tmp_path / "unit" / ".env.images"
    assert base[:5] == [
        "docker",
        "compose",
        "--env-file",
        str(cell_env),
        "--env-file",
    ]
    assert base[5] == str(pins_path)
    values = {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in pins_path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    }
    assert values == {
        APP_IMAGE_ENV_VARS[service]: references[service]
        for service in APP_IMAGES
    }


def test_compose_base_rejects_mutable_process_override(tmp_path, monkeypatch):
    monkeypatch.setattr(release_common, "release_dir", lambda cell: tmp_path / cell)
    cell_env = release_common.env_file("unit")
    cell_env.parent.mkdir(parents=True)
    cell_env.write_text("SVS_REGISTRY_PREFIX=registry.internal/exais\n", encoding="utf-8")
    images = manifest_images()
    report = verify_release_manifest(write_release_manifest(images, tmp_path / "release-manifest.json"))
    release_common.write_pinned_image_env("unit", release_image_references(report))
    monkeypatch.setenv(APP_IMAGE_ENV_VARS["api"], images[0].image)

    with pytest.raises(RuntimeError, match="process environment override SVS_IMAGE_API"):
        release_common.compose_base("unit")


def test_cell_compose_consumes_only_required_digest_image_variables():
    body = release_common.COMPOSE_FILE.read_text(encoding="utf-8")

    for env_name in APP_IMAGE_ENV_VARS.values():
        assert f"image: ${{{env_name}:?{env_name} is required}}" in body
    for _dockerfile, image_name in APP_IMAGES.values():
        assert f"/{image_name}:${{SVS_VERSION" not in body


def test_cell_up_uses_matching_local_repo_digests_without_pull(monkeypatch, tmp_path):
    references = release_image_references(
        verify_release_manifest(write_release_manifest(manifest_images(), tmp_path / "release-manifest.json"))
    )
    monkeypatch.setattr(release_common, "inspect_local_repo_digests", lambda reference: (reference,))
    monkeypatch.setattr(release_common, "run", lambda args, **kwargs: pytest.fail(f"unexpected pull: {args}"))

    release_common.ensure_app_images_available(references)


def test_cell_up_pulls_missing_digest_then_verifies_repo_digest(monkeypatch, tmp_path):
    report = verify_release_manifest(write_release_manifest(manifest_images(), tmp_path / "release-manifest.json"))
    references = release_image_references(report)
    inspections: dict[str, int] = {}
    pulls: list[list[str]] = []

    def inspect(reference):
        inspections[reference] = inspections.get(reference, 0) + 1
        return None if inspections[reference] == 1 else (reference,)

    monkeypatch.setattr(release_common, "inspect_local_repo_digests", inspect)
    monkeypatch.setattr(release_common, "run", lambda args, **kwargs: pulls.append(args))

    release_common.ensure_app_images_available(references)

    assert pulls == [["docker", "pull", references[service]] for service in APP_IMAGES]


def test_cell_up_rejects_local_repo_digest_mismatch(monkeypatch, tmp_path):
    report = verify_release_manifest(write_release_manifest(manifest_images(), tmp_path / "release-manifest.json"))
    references = release_image_references(report)
    monkeypatch.setattr(
        release_common,
        "inspect_local_repo_digests",
        lambda reference: (f"other.invalid/repo@{digest(999)}",),
    )

    with pytest.raises(RuntimeError, match="local RepoDigests do not contain"):
        release_common.ensure_app_images_available(references)


def test_cell_up_rejects_repo_digest_mismatch_after_pull(monkeypatch, tmp_path):
    report = verify_release_manifest(write_release_manifest(manifest_images(), tmp_path / "release-manifest.json"))
    references = release_image_references(report)
    inspections = iter([None, (f"other.invalid/repo@{digest(999)}",)])
    pulls: list[list[str]] = []
    monkeypatch.setattr(release_common, "inspect_local_repo_digests", lambda reference: next(inspections))
    monkeypatch.setattr(release_common, "run", lambda args, **kwargs: pulls.append(args))

    with pytest.raises(RuntimeError, match="local RepoDigests do not contain"):
        release_common.ensure_app_images_available(references)

    assert pulls == [["docker", "pull", references["api"]]]


def test_cell_up_never_resolves_moved_tags_during_boot(monkeypatch, tmp_path):
    cell_up = load_release_script("cell_up_pull_never_test", "cell-up.py")
    report = verify_release_manifest(write_release_manifest(manifest_images(), tmp_path / "release-manifest.json"))
    references = release_image_references(report)
    calls: list[list[str]] = []
    base = ["docker", "compose", "--pinned-env"]

    monkeypatch.setattr(sys, "argv", ["cell-up.py", "--cell", "unit", "--worker-scale", "3", "--no-wait"])
    monkeypatch.setattr(cell_up, "ensure_env", lambda cell: None)
    monkeypatch.setattr(cell_up, "activate_cell_release", lambda cell, manifest: references)
    monkeypatch.setattr(cell_up, "compose_base", lambda cell: base)
    monkeypatch.setattr(cell_up, "run", lambda args, **kwargs: calls.append(args))

    cell_up.main()

    assert calls[0] == base + ["pull", *cell_up.INFRA_SERVICES]
    assert calls[1] == base + [
        "up",
        "-d",
        "--pull",
        "never",
        "--scale",
        "worker=3",
        *cell_up.CORE_SERVICES,
    ]
    assert calls[2] == base + ["ps"]


def test_cell_activation_preserves_previous_pins_when_candidate_pull_fails(tmp_path, monkeypatch):
    cell_up = load_release_script("cell_up_failure_atomic_test", "cell-up.py")
    monkeypatch.setattr(release_common, "release_dir", lambda cell: tmp_path / cell)
    cell_env = release_common.env_file("unit")
    cell_env.parent.mkdir(parents=True)
    cell_env.write_text("SVS_REGISTRY_PREFIX=registry.internal/exais\n", encoding="utf-8")
    previous_report = verify_release_manifest(
        write_release_manifest(manifest_images(), tmp_path / "previous-release-manifest.json")
    )
    previous_references = release_image_references(previous_report)
    active_path = release_common.write_pinned_image_env("unit", previous_references)
    previous_bytes = active_path.read_bytes()
    candidate_references = {
        service: reference.rsplit("sha256:", 1)[0] + f"sha256:{index + 100:064x}"
        for index, (service, reference) in enumerate(previous_references.items(), start=1)
    }

    monkeypatch.setattr(cell_up, "validate_cell_release_manifest", lambda cell, manifest: candidate_references)
    monkeypatch.setattr(
        cell_up,
        "ensure_app_images_available",
        lambda refs: (_ for _ in ()).throw(RuntimeError("simulated digest pull failure")),
    )

    with pytest.raises(RuntimeError, match="simulated digest pull failure"):
        cell_up.activate_cell_release("unit", tmp_path / "candidate-release-manifest.json")

    assert active_path.read_bytes() == previous_bytes


def test_cell_up_restores_previous_pins_on_post_activation_system_exit(tmp_path, monkeypatch):
    cell_up = load_release_script("cell_up_post_activation_rollback_test", "cell-up.py")
    monkeypatch.setattr(release_common, "release_dir", lambda cell: tmp_path / cell)
    active_path = release_common.pinned_image_env_file("unit")
    active_path.parent.mkdir(parents=True)
    previous = b"previous-active-pin-bytes\n"
    active_path.write_bytes(previous)

    def activate(cell, manifest):
        active_path.write_bytes(b"candidate-pin-bytes\n")
        return {"api": "candidate"}

    monkeypatch.setattr(sys, "argv", ["cell-up.py", "--cell", "unit", "--no-wait"])
    monkeypatch.setattr(cell_up, "ensure_env", lambda cell: None)
    monkeypatch.setattr(cell_up, "activate_cell_release", activate)
    monkeypatch.setattr(cell_up, "compose_base", lambda cell: ["docker", "compose"])
    monkeypatch.setattr(
        cell_up,
        "run",
        lambda args, **kwargs: (_ for _ in ()).throw(SystemExit("simulated compose interruption")),
    )

    with pytest.raises(SystemExit, match="simulated compose interruption"):
        cell_up.main()

    assert active_path.read_bytes() == previous
