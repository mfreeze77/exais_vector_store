from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_checker():
    spec = importlib.util.spec_from_file_location("migration_drift", ROOT / "scripts" / "check-migration-drift.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_discipline_check_passes():
    result = subprocess.run([sys.executable, "scripts/check-migration-drift.py"], cwd=ROOT, text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_baseline_covers_every_legacy_source_file():
    checker = _load_checker()
    declared = tuple(checker._literal("LEGACY_MIGRATION_FILES"))
    actual = tuple(path.name for path in sorted(checker.LEGACY.iterdir()) if path.suffix in {".sql", ".sh"})
    assert declared == actual


def test_migrate_script_has_no_raw_loop():
    script = (ROOT / "scripts" / "migrate.sh").read_text(encoding="utf-8")
    assert "python -m alembic -c alembic.ini upgrade head" in script
    assert "find db/migrations" not in script
    assert "psql \"$DATABASE_URL_SYNC\"" not in script
