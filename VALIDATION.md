# Validation

## Current Docker local-cell validation

```text
python -m compileall -f -q packages apps tests scripts
docker run --rm -v "${PWD}:/work" -w /work --network exais-vector-store-local_default \
  -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent \
  localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate \
  python -m pytest -q -rs --ignore=tests/integration

46 passed, 2 warnings
```

The current local-cell gate uses the registry-pulled API image with the repo
mounted into the running Docker cell network. Integration tests remain gated by
`SVS_RUN_INTEGRATION=1`.

## Wave 009 operation proofs

```text
python scripts/release/local-restore-drill.py --source-cell restore-src --restore-cell restore --documents 12 --headings-per-doc 3 --source-port-base 28080 --restore-port-base 28180 --timeout-seconds 300
restore_readyz_status=200
restore_reindex_response processed=48
restore_qdrant_count=48
restore_search_results=5
restore_sql_counts_final={"active_chunks": 48, "active_jobs": 0, "failed_jobs": 0, "indexed_chunks": 48}

python scripts/release/qdrant-repair-all.py --cell local --proof --documents 24 --headings-per-doc 3 --batch-size 25 --delete-count 55 --timeout-seconds 600
repair_all_deleted_points=55
repair_all_iterations=4
repair_all_total_processed=96
qdrant_total_after_repair_all=96
repair_all_search_results=5

python scripts/release/prod-env-preflight.py --env-file .release\preflight\good.env
Issue count: 0
PREFLIGHT PASS

python scripts/release/cell-access-proof.py --cell local --timeout-seconds 60
API_CELL_NETWORK_STATUS=200
ADMIN_UI_CELL_NETWORK_STATUS=200
ACCESS_PATH=cell-network-fallback
```

## v0.9.8 live integration gate

Run after applying the migration chain to a real Postgres instance:

```bash
SVS_RUN_INTEGRATION=1 \
DATABASE_URL_MIGRATIONS=postgresql://svs_owner:svs_owner_dev_password@localhost:5432/svs \
SVS_TEST_APP_DSN=postgresql://svs_app:svs_app_dev_password@localhost:5432/svs \
DATABASE_URL=postgresql+psycopg://svs_app:svs_app_dev_password@localhost:5432/svs \
PYTHONPATH=packages/svs_common:apps/api:apps/worker:apps/model_gateway:apps/instance_agent \
pytest -q tests/integration
```

This gate verifies runtime RLS, tenant isolation, JSONB writes through the real worker ingestion path, and strict Qdrant-outage retry-to-terminal failure behavior with zero ghost document/version/chunk rows.

## Not claimed by local proof

- external embedding providers
- 2 TB load tests
- DNS/TLS wiring
- Docker Hub push
- VPS backup/restore drills


## Historical v0.9.8 build-container validation

```text
python -m compileall -f -q packages apps tests
PYTHONPATH=packages/svs_common:apps/api:apps/worker:apps/model_gateway:apps/instance_agent pytest -q

25 passed, 1 skipped
FastAPI routes: 45
FastAPI version: 0.9.8-production-candidate
```

The historical build-container count is preserved for the original v0.9.8 patch
report. Use the current Docker local-cell validation above for present release
readiness work.
