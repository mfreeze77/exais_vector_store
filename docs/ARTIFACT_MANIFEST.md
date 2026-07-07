# Artifact Manifest

Generated artifact: `exai_vector_store-v0.9.8-worker-attempt-atomicity.zip`

## Contents

- Project name: `exai_vector_store`
- Builder: `mfrieson@expertaiservices.com`
- Domain: `expertaiservices.com`
- File count: 159
- Approximate unpacked size: 785K
- Product version: `0.9.8-production-candidate`

## Validation performed in this build container

```text
python -m compileall -q packages apps tests
PYTHONPATH=packages/svs_common:apps/api:apps/worker:apps/model_gateway:apps/instance_agent pytest -q -rs

25 passed, 1 skipped
FastAPI routes: 45
OpenAPI paths: 34
```

The skipped suite is the live Postgres integration suite gated by `SVS_RUN_INTEGRATION=1`. It should be run against the migrated compose/hardened Postgres topologies before a customer cell deployment.

## Wave-006 contents

- Worker job attempts wrapped in a SAVEPOINT.
- Exact dedupe restricted to fully indexed current versions.
- Retry-aware Qdrant-outage integration test with zero-ghost-row assertion.
- v0.9.8 ticket trail, completion matrix, and patch report.

## External wiring still required

- Run live Postgres integration suite.
- Wire real embedding providers and/or RunPod/TEI/Infinity endpoints.
- Run backup/restore drills on the target VPS/dedicated cell.
- Run representative corpus ingestion/retrieval load tests.
- Configure DNS/TLS/secrets manager for production cells.
