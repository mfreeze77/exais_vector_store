# exai_vector_store v0.9.8 Patch Report

v0.9.8 closes WAVE-006, which was discovered by real multi-pass execution of the live Postgres integration suite after v0.9.7. The defect was not in RLS or JSONB anymore; it was in worker retry composition.

## Root cause

The worker claimed a job and executed `ingest_now()` inside the same outer database transaction. When strict Qdrant indexing raised a Python exception, the database transaction remained healthy. The worker caught the exception, updated the job row to `queued` or `failed`, and then the session context committed everything in the transaction — including partial document/version/chunk rows from the failed attempt.

On retry, content-hash dedupe saw the partial document and returned `deduplicated`, causing the job to complete even though no vectors existed.

## Fixes

### Attempt SAVEPOINT

Each worker job attempt now runs inside `db.begin_nested()`. Failed ingest work rolls back to the SAVEPOINT while the outer job claim and attempt counter remain intact.

### Indexed-only dedupe

Exact-dedupe now requires a current version whose active chunks are fully indexed in both dense and sparse backends. Pending, failed, partial, superseded, or delete-queued rows cannot satisfy dedupe.

### Retry-aware outage test

The live Qdrant-outage integration test now drains retries to terminal state, checks `attempts == max_attempts`, and verifies no ghost document/version/chunk rows survive.

## Validation in this build container

```text
python -m compileall -q packages apps tests
PYTHONPATH=packages/svs_common:apps/api:apps/worker:apps/model_gateway:apps/instance_agent pytest -q -rs

25 passed, 1 skipped
```

The skipped test is the live Postgres suite gated by `SVS_RUN_INTEGRATION=1`. This container did not run Postgres/Qdrant services.

## Wave 009 local Docker addendum

After the original v0.9.8 patch gate, Wave 009 proved the local Docker cell with
registry-pulled images and current repo tests:

```text
python -m pytest -q -rs --ignore=tests/integration
46 passed, 2 warnings in 5.56s
restore_readyz_status=200
restore_qdrant_count=48
repair_all_total_processed=96
qdrant_total_after_repair_all=96
API_CELL_NETWORK_STATUS=200
ADMIN_UI_CELL_NETWORK_STATUS=200
ACCESS_PATH=cell-network-fallback
```

This addendum is local Docker evidence only. Docker Hub push, DNS/TLS, real
provider credentials, and VPS launch remain external deployment work.

## Live validation required

Run the integration suite against both supported Postgres topologies before deploying a first customer cell:

```bash
SVS_RUN_INTEGRATION=1 \
DATABASE_URL_MIGRATIONS=postgresql://svs_owner:svs_owner_dev_password@localhost:5432/svs \
SVS_TEST_APP_DSN=postgresql://svs_app:svs_app_dev_password@localhost:5432/svs \
DATABASE_URL=postgresql+psycopg://svs_app:svs_app_dev_password@localhost:5432/svs \
PYTHONPATH=packages/svs_common:apps/api:apps/worker:apps/model_gateway:apps/instance_agent \
pytest -q tests/integration
```
