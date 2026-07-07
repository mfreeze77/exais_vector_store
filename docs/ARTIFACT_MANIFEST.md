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

## Current local Docker proof

Wave 009 extends this historical artifact with local registry-pulled Docker
proof. Current local proof is recorded in
`tickets/WAVE-009-local-restore-and-ops-preflight.md` and
`docs/DOCKER_LOCAL_CELL_RELEASE.md`.

```text
python -m compileall -f -q packages apps tests scripts
docker run --rm -v "${PWD}:/work" -w /work --network exais-vector-store-local_default ... python -m pytest -q -rs --ignore=tests/integration
46 passed, 2 warnings in 5.56s
python scripts/release/local-restore-drill.py --source-cell restore-src --restore-cell restore --documents 12 --headings-per-doc 3 --source-port-base 28080 --restore-port-base 28180 --timeout-seconds 300
restore_readyz_status=200
restore_qdrant_count=48
restore_search_results=5
python scripts/release/qdrant-repair-all.py --cell local --proof --documents 24 --headings-per-doc 3 --batch-size 25 --delete-count 55 --timeout-seconds 600
repair_all_total_processed=96
qdrant_total_after_repair_all=96
python scripts/release/cell-access-proof.py --cell local --timeout-seconds 60
ACCESS_PATH=cell-network-fallback
```

## Wave-006 contents

- Worker job attempts wrapped in a SAVEPOINT.
- Exact dedupe restricted to fully indexed current versions.
- Retry-aware Qdrant-outage integration test with zero-ghost-row assertion.
- v0.9.8 ticket trail, completion matrix, and patch report.

## External wiring still required

- Run live Postgres integration suite.
- Wire real embedding providers and/or RunPod/TEI/Infinity endpoints.
- Run backup/restore drills on the target VPS/dedicated cell. The local restore
  drill now passes; this item is specifically for the chosen external host.
- Run representative corpus ingestion/retrieval load tests.
- Configure DNS/TLS/secrets manager for production cells.
