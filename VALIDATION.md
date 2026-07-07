# Validation

## v0.9.8 build-container validation

```text
python -m compileall -f -q packages apps tests
pytest -q

25 passed, 1 skipped
```

The skipped test is the live Postgres integration suite. It is intentionally gated by `SVS_RUN_INTEGRATION=1` because this build container does not run a Postgres service.

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

## Not run in this environment

- live Docker Compose stack
- live Qdrant/OpenSearch services
- external embedding providers
- 2 TB load tests
- DNS/TLS wiring
- VPS backup/restore drills


## v0.9.8 local validation

```text
python -m compileall -f -q packages apps tests
PYTHONPATH=packages/svs_common:apps/api:apps/worker:apps/model_gateway:apps/instance_agent pytest -q

25 passed, 1 skipped
FastAPI routes: 45
FastAPI version: 0.9.8-production-candidate
```

The live Postgres integration suite is present but was not run in this offline build container. Run it with `SVS_RUN_INTEGRATION=1 pytest -q tests/integration` against a migrated Postgres instance.
