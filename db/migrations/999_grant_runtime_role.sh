#!/usr/bin/env bash
set -euo pipefail
: "${POSTGRES_DB:=svs}"
: "${POSTGRES_APP_USER:=svs_app}"

if [[ -n "${DATABASE_URL_SYNC:-}" ]]; then
  PSQL=(psql "$DATABASE_URL_SYNC" -v ON_ERROR_STOP=1)
else
  : "${POSTGRES_USER:=svs_owner}"
  PSQL=(psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v ON_ERROR_STOP=1)
fi

"${PSQL[@]}" -v app_user="$POSTGRES_APP_USER" -v db_name="$POSTGRES_DB" <<'SQL'
GRANT CONNECT ON DATABASE :"db_name" TO :"app_user";
GRANT USAGE ON SCHEMA public TO :"app_user";
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO :"app_user";
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO :"app_user";
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO :"app_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO :"app_user";
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO :"app_user";

-- Only true superusers can mention SUPERUSER/BYPASSRLS attributes. Keep this as
-- a conditional compose hardening step, not a requirement for managed Postgres.
SELECT format('ALTER ROLE %I NOSUPERUSER NOBYPASSRLS', :'app_user')
WHERE (SELECT rolsuper FROM pg_roles WHERE rolname = current_user) \gexec
SQL
