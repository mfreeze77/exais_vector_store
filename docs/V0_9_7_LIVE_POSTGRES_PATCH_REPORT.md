# SVS v0.9.7 Live-Postgres Patch Report

v0.9.7 is the follow-up patch opened by the first real Postgres execution of the v0.9.6 integration suite. The suite proved the v0.9.6 RLS topology, then exposed that untyped SQLAlchemy `text()` statements with raw Python dict/list parameters were not safely executable against JSONB columns under SQLAlchemy 2 + psycopg3.

## Blockers closed

### W5-001 JSONB parameter sweep

- Added a cast-based JSONB write contract:
  - `jsonb_param(value)` serializes Python values to JSON text.
  - SQL statements use `CAST(:param AS jsonb)` for JSONB columns.
  - `jsonb_text(sql, *param_names)` documents the call-site contract without binding already-serialized values as JSONB scalars.
- Swept live write paths for JSONB columns:
  - ingestion job payloads
  - vector-store attributes and expiration policy JSON
  - vector-store-file attributes
  - document-version metadata
  - chunk metadata
  - audit metadata
  - usage metadata
  - ingestion-plan request/plan JSON
  - idempotency responses
  - bakeoff queries/results/metrics
  - model-endpoint config
  - file-batch counts
  - stale-vector purge job payloads
- Fixed non-DB payload regressions while sweeping:
  - Qdrant point payloads remain Python dicts, not JSON strings.
  - file-batch API responses return JSON objects, not serialized JSON strings.

### W5-002 Managed-Postgres role portability

- Removed unconditional `ALTER ROLE ... NOSUPERUSER` / `NOBYPASSRLS` from runtime-role scripts.
- Runtime role creation/alteration now avoids SUPERUSER/BYPASSRLS attributes, which can fail on managed Postgres or hardened owner roles.
- Scripts now verify that `POSTGRES_APP_USER` is not `rolsuper` and not `rolbypassrls`, failing clearly if an unsafe preexisting role is supplied.

### W5-003 GUC-aware integration fixtures

- Integration fixtures now set RLS GUCs before owner-DSN test writes.
- Cross-tenant test inserts are honest under FORCE RLS even when the owner role is not a true superuser.
- Job cleanup uses `svs.system_worker=true` so it remains valid under system-worker RLS policy.

### W5-004 Live worker proof extension

- Added an integration test that enqueues a real document through the SQLAlchemy app path, then runs `svs_worker.process_once()` against live Postgres.
- The test verifies:
  - job completed
  - document row was created
  - chunk row with JSONB metadata was created
  - usage ledger write succeeded
- Existing Qdrant outage integration test now also uses the real enqueue path and still expects terminal `failed` under strict indexing.

## Validation performed in this build environment

```text
python -m compileall -f -q packages apps tests
PYTHONPATH=packages/svs_common:apps/api:apps/worker:apps/model_gateway:apps/instance_agent pytest -q

23 passed, 1 skipped
FastAPI routes: 45
FastAPI version: 0.9.7-production-candidate
```

The live Postgres integration suite is included and wired, but it was not executed in this offline build container because no local Postgres server/client or Docker daemon was available here. The integration command remains:

```bash
SVS_RUN_INTEGRATION=1 \
DATABASE_URL_MIGRATIONS=postgresql://svs_owner:svs_owner_dev_password@localhost:5432/svs \
DATABASE_URL=postgresql+psycopg://svs_app:svs_app_dev_password@localhost:5432/svs \
SVS_TEST_APP_DSN=postgresql://svs_app:svs_app_dev_password@localhost:5432/svs \
PYTHONPATH=packages/svs_common:apps/api:apps/worker:apps/model_gateway:apps/instance_agent \
pytest -q tests/integration
```

## Remaining v1.0 gates

- Run the compose-backed integration job on CI and keep it required.
- Run at least one VPS/cell deployment drill.
- Run provider integration tests for OpenAI/RunPod/TEI/Infinity as configured per instance.
- Run Qdrant/OpenSearch live-path tests where those backends are enabled.
- Run load/restore drills before customer data enters the system.
