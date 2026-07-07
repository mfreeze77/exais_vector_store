#!/usr/bin/env bash
set -euo pipefail
: "${POSTGRES_DB:=svs}"
: "${POSTGRES_APP_USER:=svs_app}"
: "${POSTGRES_APP_PASSWORD:=svs_app_dev_password}"

if [[ -n "${DATABASE_URL_SYNC:-}" ]]; then
  PSQL=(psql "$DATABASE_URL_SYNC" -v ON_ERROR_STOP=1)
else
  : "${POSTGRES_USER:=svs_owner}"
  PSQL=(psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v ON_ERROR_STOP=1)
fi

"${PSQL[@]}" -v app_user="$POSTGRES_APP_USER" -v app_password="$POSTGRES_APP_PASSWORD" <<'SQL'
-- Portable path: do not specify SUPERUSER/NOSUPERUSER or BYPASSRLS/NOBYPASSRLS
-- during create/alter because managed Postgres and hardened owner roles often
-- cannot mention those attributes at all. Defaults are NOSUPERUSER/NOBYPASSRLS.
SELECT format(
  'CREATE ROLE %I LOGIN PASSWORD %L NOCREATEDB NOCREATEROLE NOINHERIT',
  :'app_user', :'app_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app_user') \gexec

SELECT format(
  'ALTER ROLE %I LOGIN PASSWORD %L NOCREATEDB NOCREATEROLE NOINHERIT',
  :'app_user', :'app_password'
) \gexec

-- Extra hardening only when the migration role is a true superuser. This keeps
-- compose safe while remaining portable to managed/hardened Postgres.
SELECT format('ALTER ROLE %I NOSUPERUSER NOBYPASSRLS', :'app_user')
WHERE (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) \gexec
SQL
