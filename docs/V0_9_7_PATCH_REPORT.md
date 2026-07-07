# exai_vector_store v0.9.7 Patch Report

## Purpose

v0.9.7 fixes the first live-Postgres execution blocker found after the v0.9.6 Wave-004 gate: SQLAlchemy 2 + psycopg3 cannot adapt raw Python `dict` / `list` values passed through untyped `text()` statements into JSONB columns.

The fix standardizes JSONB writes on this pattern:

```sql
CAST(:payload AS jsonb)
```

with application parameters serialized through `jsonb_param(value)` before execution. This is intentionally simple and portable across compose, psycopg3, and managed Postgres deployments.

## Fixed

### W5-001 JSONB parameter sweep

JSONB write paths now serialize and cast payloads instead of passing raw dict/list values to untyped `text()` statements.

Covered paths include:

- ingestion job payloads
- vector-store attributes and expiration policy
- vector-store-file attributes
- document-version metadata
- chunk metadata
- audit-event metadata
- usage-event metadata
- idempotency cached responses
- ingestion plans
- bakeoff query sets and metrics
- model-endpoint config
- file-batch counters
- stale-vector cleanup jobs

A dedicated SQL helper was added:

- `packages/svs_common/svs_common/sql.py`
- `packages/svs_common/svs_common/db.jsonb_param()`

### W5-002 Qdrant payload regression guard

The JSONB helper is now used only for SQL parameters. Qdrant point payloads remain Python dictionaries so Qdrant payload filtering still works.

### W5-003 Portable role scripts

The runtime role scripts no longer unconditionally specify `NOSUPERUSER` / `NOBYPASSRLS`. New roles default to those attributes; compose superuser bootstraps still normalize them conditionally.

Updated files:

- `db/migrations/000_create_runtime_role.sh`
- `db/migrations/999_grant_runtime_role.sh`

### W5-004 GUC-aware integration fixtures

The live Postgres integration tests now set the tenant/business/max-security GUCs before fixture writes. This makes the tests honest under `FORCE ROW LEVEL SECURITY`, including hardened non-superuser owner roles.

### W5-005 Live data-plane proof test

The integration suite includes a worker-backed live Postgres ingest proof that exercises JSONB writes through the actual enqueue/worker/ingestion path.

## Validation performed in this build container

```text
python -m compileall -f -q packages apps tests
pytest -q

23 passed, 1 skipped
```

The skipped test is the live Postgres integration suite unless `SVS_RUN_INTEGRATION=1` is set and Postgres is available.

## Validation still required before v1.0

Run the integration suite against a real migrated Postgres instance:

```bash
SVS_RUN_INTEGRATION=1 \
DATABASE_URL_MIGRATIONS=postgresql://svs_owner:svs_owner_dev_password@localhost:5432/svs \
SVS_TEST_APP_DSN=postgresql://svs_app:svs_app_dev_password@localhost:5432/svs \
DATABASE_URL=postgresql+psycopg://svs_app:svs_app_dev_password@localhost:5432/svs \
PYTHONPATH=packages/svs_common:apps/api:apps/worker:apps/model_gateway:apps/instance_agent \
pytest -q tests/integration
```

This is the gate that proves:

- `svs_app` is `NOSUPERUSER` / `NOBYPASSRLS`
- all protected tables force RLS
- plain SQL cannot cross tenants
- a real JSONB-heavy ingest completes against live Postgres
- a Qdrant outage fails the job instead of silently completing
