import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "release" / "local-restore-drill.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("local_restore_drill", SCRIPT)
local_restore_drill = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(local_restore_drill)

import release_common  # noqa: E402
from backup_common import validate_backup_manifest  # noqa: E402
from provenance_common import ImageDigest, write_release_manifest  # noqa: E402
from release_common import APP_IMAGES, all_image_tags, version  # noqa: E402


def release_images(
    registry_prefix: str = "localhost:5000/expertaiservices",
    *,
    digest_source: str = "repository_digest",
) -> list[ImageDigest]:
    images = []
    for index, (service, image) in enumerate(zip(APP_IMAGES, all_image_tags(registry_prefix, version())), start=1):
        digest = f"sha256:{index:064x}"
        provenance = {"source": "unit-test", "digest_source": digest_source}
        if digest_source == "repository_digest":
            provenance["repository_digest"] = f"{image.rsplit(':', 1)[0]}@{digest}"
        images.append(
            ImageDigest(
                service=service,
                image=image,
                tag=version(),
                digest=digest,
                provenance=provenance,
            )
        )
    return images


def test_drill_env_values_assign_distinct_ports():
    values = local_restore_drill.drill_env_values("restore-src", "localhost:5000/expertaiservices", 28080)

    assert values["SVS_CELL_NAME"] == "restore-src"
    assert values["SVS_API_PORT"] == "28080"
    assert values["SVS_MODEL_GATEWAY_PORT"] == "28081"
    assert values["SVS_ADMIN_UI_PORT"] == "28082"
    assert values["SVS_POSTGRES_PORT"] == "28084"
    assert values["SVS_PUBLIC_API_BASE"] == "http://localhost:28080"
    assert values["SVS_ALLOWED_CORS_ORIGINS"] == "http://localhost:28082,http://localhost:28080"


def test_restore_doc_contains_token_in_each_section():
    doc = local_restore_drill.restore_doc(7, 3, "token-abc")

    assert doc["attributes"]["force_async"] is True
    assert doc["mode"] == "markdown_docs_v1"
    assert doc["content"].count("token-abc") == 3
    assert "restore-proof-7-2" in doc["content"]


def test_restore_drill_writes_shared_backup_manifest(tmp_path):
    (tmp_path / "svs.dump").write_text("dump\n", encoding="utf-8")

    local_restore_drill.write_backup_manifest(
        tmp_path,
        {
            "source_cell": "restore-src",
            "restore_cell": "restore",
            "vector_store_id": "vs_test",
            "source_sql_counts": {"active_chunks": 1, "indexed_chunks": 1},
            "source_qdrant_count": 1,
            "collections": ["chunks_default"],
        },
    )

    report = validate_backup_manifest(tmp_path / "manifest.json")

    assert report.ok
    assert "qdrant_vectors" in report.artifact_kinds
    assert (tmp_path / "restore-drill-manifest.json").is_file()


def test_restore_drill_persists_same_manifest_pins_for_both_cells(tmp_path, monkeypatch):
    registry_prefix = "localhost:5000/expertaiservices"
    manifest = write_release_manifest(release_images(), tmp_path / "release-manifest.json")
    monkeypatch.setattr(release_common, "release_dir", lambda cell: tmp_path / "cells" / cell)
    monkeypatch.setattr(local_restore_drill, "ensure_app_images_available", lambda references: None)

    references = local_restore_drill.preflight_drill_image_pins(
        manifest,
        registry_prefix,
    )
    local_restore_drill.activate_drill_image_pins(
        ("restore-src", "restore"),
        references,
        registry_prefix,
    )

    assert set(references) == set(APP_IMAGES)
    source_pins = (tmp_path / "cells" / "restore-src" / ".env.images").read_text(encoding="utf-8")
    restore_pins = (tmp_path / "cells" / "restore" / ".env.images").read_text(encoding="utf-8")
    assert source_pins == restore_pins
    assert f":{version()}" not in source_pins
    assert source_pins.count("@sha256:") == len(APP_IMAGES)


def test_restore_drill_requires_explicit_release_manifest(capsys):
    with pytest.raises(SystemExit):
        local_restore_drill.build_parser().parse_args([])

    assert "--release-manifest" in capsys.readouterr().err


def test_restore_drill_rejects_clean_build_local_image_ids(tmp_path, monkeypatch, capsys):
    manifest = write_release_manifest(
        release_images(digest_source="local_image_id"),
        tmp_path / "clean-build-manifest.json",
    )
    monkeypatch.setattr(
        local_restore_drill,
        "ensure_app_images_available",
        lambda references: pytest.fail("local image IDs must fail before Docker preflight"),
    )

    with pytest.raises(SystemExit):
        local_restore_drill.preflight_drill_image_pins(manifest, "localhost:5000/expertaiservices")

    assert "local image IDs cannot pin cell startup" in capsys.readouterr().out


def test_restore_preflight_failure_preserves_existing_pins(tmp_path, monkeypatch):
    registry_prefix = "localhost:5000/expertaiservices"
    manifest = write_release_manifest(release_images(), tmp_path / "release-manifest.json")
    monkeypatch.setattr(release_common, "release_dir", lambda cell: tmp_path / "cells" / cell)
    references = {
        service: f"{registry_prefix}/{APP_IMAGES[service][1]}@sha256:{index + 100:064x}"
        for index, service in enumerate(APP_IMAGES, start=1)
    }
    active_paths = [
        release_common.write_pinned_image_env(cell, references, registry_prefix=registry_prefix)
        for cell in ("restore-src", "restore")
    ]
    previous = [path.read_bytes() for path in active_paths]
    monkeypatch.setattr(
        local_restore_drill,
        "ensure_app_images_available",
        lambda candidate: (_ for _ in ()).throw(RuntimeError("simulated pull failure")),
    )

    with pytest.raises(RuntimeError, match="simulated pull failure"):
        local_restore_drill.preflight_drill_image_pins(manifest, registry_prefix)

    assert [path.read_bytes() for path in active_paths] == previous


def test_clean_restore_source_runs_digest_pinned_migration_before_apps(monkeypatch):
    base = ["docker", "compose", "--pinned"]
    events = []
    monkeypatch.setattr(local_restore_drill, "compose_base", lambda cell: base)
    monkeypatch.setattr(
        local_restore_drill,
        "run",
        lambda args, **kwargs: events.append(("run", args, kwargs)),
    )
    monkeypatch.setattr(
        local_restore_drill,
        "wait_for_services",
        lambda cell, services, timeout: events.append(("wait", list(services))),
    )

    local_restore_drill.boot_clean_cell("restore-src", 2, 300)

    commands = [event[1] for event in events if event[0] == "run"]
    infra_up = base + ["up", "-d", "--pull", "never", *local_restore_drill.INFRA_SERVICES]
    migration = base + [
        "run",
        "--rm",
        "--no-deps",
        "--pull",
        "never",
        "api",
        "bash",
        "scripts/migrate.sh",
    ]
    apps_up = base + [
        "up",
        "-d",
        "--pull",
        "never",
        "--scale",
        "worker=2",
        *local_restore_drill.APP_SERVICES,
    ]
    assert commands.index(infra_up) < commands.index(migration) < commands.index(apps_up)
    waits = [event[1] for event in events if event[0] == "wait"]
    assert waits == [local_restore_drill.INFRA_SERVICES, local_restore_drill.CORE_SERVICES]


def test_restore_target_migrates_infra_before_pg_restore_boundary(monkeypatch):
    base = ["docker", "compose", "--pinned"]
    events = []
    monkeypatch.setattr(local_restore_drill, "compose_base", lambda cell: base)
    monkeypatch.setattr(local_restore_drill, "run", lambda args, **kwargs: events.append(args))
    monkeypatch.setattr(local_restore_drill, "wait_for_services", lambda cell, services, timeout: None)

    local_restore_drill.boot_restore_infra("restore", 300)

    assert events[-1] == base + [
        "run",
        "--rm",
        "--no-deps",
        "--pull",
        "never",
        "api",
        "bash",
        "scripts/migrate.sh",
    ]
