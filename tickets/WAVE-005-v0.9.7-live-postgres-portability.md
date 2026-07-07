# WAVE-005 — v0.9.7 Live Postgres JSONB + Portability

## Trigger

Independent live-Postgres validation of v0.9.6 confirmed RLS/runtime-role fixes,
but found SQLAlchemy 2 + psycopg3 JSONB adaptation failures across the data plane.
It also found portability assumptions in role scripts and fixtures.

## Tickets

### W5-001 JSONB parameter sweep

Replace raw Python dict/list JSONB binds in text SQL with serialized JSON text and
`CAST(:param AS jsonb)`.

### W5-002 Role-script portability

Remove unconditional `NOSUPERUSER` / `NOBYPASSRLS` ALTERs. Apply those only when
the migration connection is a true superuser.

### W5-003 GUC-aware integration fixtures

Set tenant/business/security GUCs before fixture writes so FORCE RLS is tested
honestly for non-superuser owner roles.

### W5-004 End-to-end live ingestion proof

Add a worker-ingest success test against live Postgres and Postgres FTS, plus keep
the strict Qdrant-outage failure test.

## Exit criteria

- Unit suite remains green.
- Compileall remains green.
- Integration suite is runnable with `SVS_RUN_INTEGRATION=1`.
- Live Postgres no longer raises `cannot adapt type 'dict'` on ingest/search/control-plane JSONB writes.
