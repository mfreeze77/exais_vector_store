#!/usr/bin/env bash
set -euo pipefail
: "${POSTGRES_USER:=svs_owner}"
: "${POSTGRES_PASSWORD:=svs_owner_dev_password}"
: "${POSTGRES_DB:=svs}"
: "${POSTGRES_APP_USER:=svs_app}"
: "${POSTGRES_APP_PASSWORD:=svs_app_dev_password}"
: "${DATABASE_URL_SYNC:=postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:5432/${POSTGRES_DB}}"
export DATABASE_URL_SYNC POSTGRES_DB POSTGRES_APP_USER POSTGRES_APP_PASSWORD

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"
python scripts/check-migration-drift.py
python -m alembic -c alembic.ini upgrade head
