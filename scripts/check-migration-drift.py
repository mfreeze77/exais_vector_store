#!/usr/bin/env python3
"""Reject legacy migration bypasses and changes outside Alembic coverage."""

from __future__ import annotations

import ast
import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVISION = ROOT / "migrations" / "versions" / "001_initial_schema.py"
LEGACY = ROOT / "db" / "migrations"


def _literal(name: str):
    source = REVISION.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise ValueError(f"{name} is missing from {REVISION}")


def main() -> int:
    errors: list[str] = []
    if not REVISION.is_file():
        errors.append("Alembic baseline revision is missing")
    else:
        declared = tuple(_literal("LEGACY_MIGRATION_FILES"))
        expected_hashes = dict(_literal("LEGACY_MIGRATION_SHA256"))
        actual_files = tuple(path.name for path in sorted(LEGACY.iterdir()) if path.suffix in {".sql", ".sh"})
        if actual_files != declared:
            errors.append(f"legacy migration manifest differs: expected {declared}, found {actual_files}")
        if tuple(expected_hashes) != declared:
            errors.append("legacy migration hashes do not cover the declared ordered manifest")
        for name, expected in expected_hashes.items():
            path = LEGACY / name
            if not path.is_file():
                continue
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected:
                errors.append(f"legacy migration changed without an Alembic revision: {name}")

    migrate = (ROOT / "scripts" / "migrate.sh").read_text(encoding="utf-8")
    if not re.search(r"(?:\balembic\b|\bpython\s+-m\s+alembic\b)\s+(?:-c\s+[^\s]+\s+)?upgrade\s+head\b", migrate):
        errors.append("scripts/migrate.sh must invoke alembic upgrade head")
    if "find db/migrations" in migrate or "docker-entrypoint-initdb" in migrate or re.search(r"psql .* -f", migrate):
        errors.append("scripts/migrate.sh contains a raw migration loop or psql file execution")

    for compose in (ROOT / "docker-compose.yml", ROOT / "infra" / "docker" / "compose.cell.yml"):
        if compose.is_file() and "docker-entrypoint-initdb" in compose.read_text(encoding="utf-8"):
            errors.append(f"{compose.relative_to(ROOT)} mounts legacy migrations as Postgres init scripts")

    if errors:
        print("Migration discipline check failed:")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print("Migration discipline check passed: Alembic owns the frozen legacy baseline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
