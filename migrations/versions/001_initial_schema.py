"""Baseline the schema previously applied by db/migrations."""

from __future__ import annotations

import os
from pathlib import Path

from alembic import op
from sqlalchemy import text

revision = "001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None

LEGACY_MIGRATION_FILES = (
    "000_create_runtime_role.sh",
    "001_initial.sql",
    "002_rls.sql",
    "003_seed_dev.sql",
    "004_hardening_wave1.sql",
    "005_production_waves.sql",
    "006_wave004_runtime_rls_cleanup.sql",
    "007_brand_exai_vector_store.sql",
    "008_openai_responses_lifecycle.sql",
    "999_grant_runtime_role.sh",
)

LEGACY_MIGRATION_SHA256 = {
    "000_create_runtime_role.sh": "27b0e6e84671ce86c5bce3ccb9c1b2caece54e85cbeca5e2ee404b49d2d93c41",
    "001_initial.sql": "55b130536886e815436af61b008040caa1486b24deba5b94e571dda2e760bc5d",
    "002_rls.sql": "90d41cdf2f0dd4ce68b8074e8aeb776691117d6871ff45f935b8993d391cb786",
    "003_seed_dev.sql": "51e5b58a57d2aca4d2c4138da79b54bd6a270fb2a743b9fc9ad9e46e8d4c407e",
    "004_hardening_wave1.sql": "50990e916523d3bfc3d9af006c75592f6498ef05209ab21046ba7035fbd55abb",
    "005_production_waves.sql": "bfb9bdd91e9fc7159a7dc7b0aec766395cc2b657066306b76176c45d63c1b3d2",
    "006_wave004_runtime_rls_cleanup.sql": "525b6f98b25047e4ace8690ea38a11f88958b7e9e87e6e326acf30b6614ecdf3",
    "007_brand_exai_vector_store.sql": "ef65f3995cfb7e90c24c53981e6bcda4216190a9f6444c9233e068bb943827ad",
    "008_openai_responses_lifecycle.sql": "0481cba3b2188bb98bc2da1056be145ba285016a07998e9ea473003c1aa374ad",
    "999_grant_runtime_role.sh": "391b4dcf9038caaa7ca8bab7df0ad6e1adb4b77cb30f5b0012b66355db4fe9b2",
}


def _legacy_root() -> Path:
    return Path(__file__).resolve().parents[2] / "db" / "migrations"


def _run_sql_file(connection, path: Path) -> None:
    connection.exec_driver_sql(path.read_text(encoding="utf-8"))


def _formatted(connection, template: str, *values: str) -> str:
    params = {f"value_{index}": value for index, value in enumerate(values)}
    placeholders = ", ".join(f"CAST(:value_{index} AS text)" for index in range(len(values)))
    return connection.execute(
        text(f"SELECT format(:template, {placeholders})"),
        {"template": template, **params},
    ).scalar_one()


def _create_runtime_role(connection) -> None:
    user = os.getenv("POSTGRES_APP_USER", "svs_app")
    password = os.getenv("POSTGRES_APP_PASSWORD", "svs_app_dev_password")
    exists = connection.execute(
        text("SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :user)"), {"user": user}
    ).scalar_one()
    if not exists:
        connection.exec_driver_sql(
            _formatted(
                connection,
                "CREATE ROLE %I LOGIN PASSWORD %L NOCREATEDB NOCREATEROLE NOINHERIT",
                user,
                password,
            )
        )
    connection.exec_driver_sql(
        _formatted(connection, "ALTER ROLE %I LOGIN PASSWORD %L NOCREATEDB NOCREATEROLE NOINHERIT", user, password)
    )
    if connection.execute(text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")).scalar_one():
        connection.exec_driver_sql(_formatted(connection, "ALTER ROLE %I NOSUPERUSER NOBYPASSRLS", user))


def _grant_runtime_role(connection) -> None:
    user = os.getenv("POSTGRES_APP_USER", "svs_app")
    database = connection.execute(text("SELECT current_database()")).scalar_one()
    commands = (
        _formatted(connection, "GRANT CONNECT ON DATABASE %I TO %I", database, user),
        _formatted(connection, "GRANT USAGE ON SCHEMA public TO %I", user),
    )
    for command in commands:
        connection.exec_driver_sql(command)
    for command in (
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO %I",
        "GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO %I",
        "GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO %I",
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO %I",
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO %I",
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO %I",
    ):
        connection.exec_driver_sql(_formatted(connection, command, user))
    if connection.execute(text("SELECT rolsuper FROM pg_roles WHERE rolname = current_user")).scalar_one():
        connection.exec_driver_sql(_formatted(connection, "ALTER ROLE %I NOSUPERUSER NOBYPASSRLS", user))


def upgrade() -> None:
    connection = op.get_bind()
    root = _legacy_root()
    _create_runtime_role(connection)
    for filename in LEGACY_MIGRATION_FILES[1:-1]:
        _run_sql_file(connection, root / filename)
    _grant_runtime_role(connection)


def downgrade() -> None:
    raise RuntimeError("The initial schema baseline is not destructively reversible; use a backup or a forward-fix revision.")
