# SVS v0.9.6 Wave-004 Patch Report

## Summary

v0.9.6 closes the four findings from the v0.9.5 independent audit:

1. Runtime app role is separate from the Postgres owner/superuser role, so RLS is no longer bypassed by the shipped compose configuration.
2. Production startup guardrails reject dev mode and weak/default security settings.
3. Superseded, deleted, and expired chunks now queue physical external-index cleanup and the worker can execute that cleanup.
4. CI includes a live Postgres RLS integration job.

## Code changes

- `docker-compose.yml`
  - `postgres` now creates `svs_owner` as init/migration owner and passes `POSTGRES_APP_USER` / `POSTGRES_APP_PASSWORD` to init scripts.
  - `api` and `worker` continue to use `DATABASE_URL`, now pointed at `svs_app` by `.env.example`.
- `db/migrations/000_create_runtime_role.sh`
  - Creates/updates `svs_app` as `NOSUPERUSER NOBYPASSRLS`.
- `db/migrations/999_grant_runtime_role.sh`
  - Grants runtime table/function/sequence privileges to `svs_app` after all schema migrations.
- `packages/svs_common/svs_common/config.py`
  - Adds unified production guardrails and defaults runtime DB access to the app role.
- `packages/svs_common/svs_common/index_cleanup.py`
  - Centralizes dense/sparse stale-index cleanup and queues purge jobs after logical deactivation.
- `packages/svs_common/svs_common/ingestion.py`
  - Marks superseded chunks `delete_queued` and queues purge by document-version ID after the new version indexes successfully.
- `packages/svs_common/svs_common/vector_store_repo.py`
  - Marks deleted store chunks `delete_queued` and queues purge.
- `packages/svs_common/svs_common/maintenance.py`
  - Adds `purge_stale_vectors` so queued jobs physically delete Qdrant/OpenSearch records and mark chunks `deleted`.
  - Expiration now deactivates chunks and queues purge rather than silently leaving stale vectors.
- `apps/api/svs_api/main.py`
  - Runs startup guardrails and queues purge on vector-store-file delete.
- `.github/workflows/ci.yml`
  - Adds compose-backed Postgres RLS integration tests.
- `tests/integration/test_postgres_rls_and_worker.py`
  - Verifies runtime role properties, forced RLS, cross-tenant SQL isolation, and strict worker failure on Qdrant outage.

## Local validation in this environment

```text
python -m compileall -f -q packages apps tests
pytest -q -rs
21 passed, 1 skipped
```

The skipped test is the live Postgres integration suite; GitHub Actions is configured to run it with a live compose Postgres service.

## Remaining v1.0 gates

- Run live Docker Compose full-stack smoke test.
- Run live Qdrant/OpenSearch cleanup tests for supersede, vector-store deletion, and expiration.
- Run provider integration tests for selected embedding/rerank backends.
- Run backup/restore drill for at least one micro-production instance.
- Run p95/p99 load validation for the target cell sizes.
