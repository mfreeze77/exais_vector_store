import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


RELEASE_DIR = Path(__file__).resolve().parents[1] / "scripts" / "release"
if not RELEASE_DIR.exists():
    pytest.skip("release scripts are not copied into runtime images", allow_module_level=True)

sys.path.insert(0, str(RELEASE_DIR))

from release_common import compose_network_name  # noqa: E402


def test_compose_network_name_uses_requested_cell():
    assert compose_network_name("customer-001") == "exais-vector-store-customer-001_default"
    assert compose_network_name("ACME.Cell") == "exais-vector-store-acme-cell_default"


def test_release_scripts_do_not_hardcode_local_cell_network():
    for script in ["cell-smoke.py", "scale_common.py", "search-bench.py"]:
        body = (RELEASE_DIR / script).read_text(encoding="utf-8")
        assert "exais-vector-store-local_default" not in body


def test_cell_smoke_restores_workers_from_local_image_when_registry_pull_fails(monkeypatch):
    path = RELEASE_DIR / "cell-smoke.py"
    spec = importlib.util.spec_from_file_location("cell_smoke_script", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(returncode=1 if len(calls) == 1 else 0)

    monkeypatch.setattr(module, "run", fake_run)

    module.restore_workers(["docker-compose", "-p", "cell"], 4)

    assert calls[0][0][-8:] == ["up", "-d", "--no-deps", "--pull", "always", "--scale", "worker=4", "worker"]
    assert calls[0][1] == {"check": False}
    assert calls[1][0][-8:] == ["up", "-d", "--no-deps", "--pull", "never", "--scale", "worker=4", "worker"]
    assert calls[1][1] == {}


def test_cell_smoke_recreates_workers_with_prepared_secret_env_and_cleans_up(monkeypatch, tmp_path):
    path = RELEASE_DIR / "cell-smoke.py"
    spec = importlib.util.spec_from_file_location("cell_smoke_secret_runtime_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    source = tmp_path / ".env.cell"
    source.write_text(
        "SVS_ENV=prod\nPOSTGRES_PASSWORD=envref://SMOKE_DB_PASSWORD\n",
        encoding="utf-8",
    )
    base = ["docker-compose", "-p", "customer"]
    prepared_paths = []
    restored = []
    actual_runtime_env_path = module.runtime_env_path

    monkeypatch.setattr(module, "env_file", lambda cell: source)
    monkeypatch.setattr(module, "runtime_env_path", lambda path: actual_runtime_env_path(path, temp_parent=tmp_path))
    monkeypatch.setenv("SMOKE_DB_PASSWORD", "resolved-smoke-password")
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

    def compose_with_prepared_env(cell, prepared_env_path=None):
        assert prepared_env_path is not None
        body = prepared_env_path.read_text(encoding="utf-8")
        assert "envref://" not in body
        assert 'POSTGRES_PASSWORD="resolved-smoke-password"' in body
        prepared_paths.append(prepared_env_path)
        return base

    monkeypatch.setattr(module, "compose_base", compose_with_prepared_env)
    monkeypatch.setattr(module, "api_base", lambda cell: "http://api.example.test")
    monkeypatch.setattr(module, "run", lambda args, **kwargs: SimpleNamespace(returncode=0, stdout=""))

    def capture_restore(selected_base, scale):
        assert prepared_paths[0].exists()
        restored.append((selected_base, scale))

    monkeypatch.setattr(module, "restore_workers", capture_restore)

    module.run_smoke("customer", 3)

    assert restored == [(base, 3)]
    assert len(prepared_paths) == 1
    assert not prepared_paths[0].parent.exists()


def test_qdrant_chaos_repair_selects_same_order_as_reindex_cursor():
    body = (RELEASE_DIR / "qdrant-chaos-repair.py").read_text(encoding="utf-8")
    assert "ORDER BY c.created_at ASC, c.id ASC" in body
