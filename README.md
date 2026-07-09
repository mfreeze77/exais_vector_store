# exai_vector_store v0.9.8 Production Candidate

Expert AI Services self-hosted, OpenAI-compatible, multi-tenant retrieval/vectorization platform for micro-production cells, business instances, and user vaults.

- Domain: `expertaiservices.com`
- Builder: `mfrieson@expertaiservices.com`
- Project: `exai_vector_store`

This repo is built from the conversation goal: one base product, many isolated instances, per-instance settings/security/model profiles, controllable Docker-image updates, and a mode router that chooses parsing/chunking/tokenization/embedding/retrieval behavior for Markdown, external PDF-to-Markdown bundles, code, structured data, and logs.

Internal package names, service IDs, headers, metrics, and environment variables currently retain the `svs` / `SVS_` prefix for compatibility with the existing code and deployment surface.

## What is implemented

- FastAPI API service with native `exai_vector_store` APIs and OpenAI-compatible vector-store APIs.
- PostgreSQL source-of-truth schema with FORCE RLS, API keys, tenants, users, groups, documents, versions, chunks, jobs, audit, usage, router plans, model endpoints, bakeoffs, idempotency, and rate limits.
- Qdrant dense vector indexing/search.
- Postgres FTS sparse backend for mini micro-production cells.
- Optional OpenSearch sparse backend for standard/large cells.
- Hybrid reciprocal-rank-fusion retrieval with post-retrieval ACL verification.
- Markdown, external PDF-to-Markdown, code-symbol, structured JSON/CSV, and logs/errors chunkers.
- Intelligent vectorization preview router with scored model candidates and security-aware provider filtering.
- Provider abstraction for OpenAI, Voyage, Cohere, TEI, Infinity, RunPod/local, and deterministic hash development embeddings.
- Durable ingestion jobs with async threshold, dedupe, versioning, per-chunk index status, and reindex repair.
- OpenAI-compatible files plus vector store CRUD, files, file content, file batches, batch cancel, search, Responses file-search citations, native context citation markers, update, delete, and pagination metadata.
- Maintenance APIs for expiration sweeps and reindex.
- Admin usage/audit APIs and Prometheus-compatible `/metrics`.
- Instance agent, `svsctl.py`, backup/restore/fleet-upgrade scripts.
- React admin UI with mode selection, ingestion preview, ingest, and search.

## Local quick start

```bash
cp .env.example .env
docker compose up -d postgres redis qdrant minio api worker model-gateway admin-ui
./scripts/migrate.sh
./scripts/smoke-test.sh
```

For the smallest micro-production cell, keep `SVS_SPARSE_BACKEND=postgres_fts`. For a standard business cell with stronger sparse/code retrieval, set `SVS_SPARSE_BACKEND=opensearch` and start the OpenSearch service.

## Key docs

- `docs/PRODUCTION_WAVE_EXECUTION_REPORT.md`
- `docs/DOCKER_LOCAL_CELL_RELEASE.md`
- `tickets/WAVE-009-local-restore-and-ops-preflight.md`
- `docs/TICKET_TRAIL_V0_9_5.md`
- `tickets/WAVE-006-v0.9.8-worker-attempt-atomicity.md`
- `docs/TICKET_TRAIL_V0_9_8.md`
- `docs/COMPLETION_MATRIX_V0_9_8.md`
- `docs/V0_9_8_PATCH_REPORT.md`
- `tickets/WAVE-005-v0.9.7-live-postgres-portability.md`
- `docs/TICKET_TRAIL_V0_9_7.md`
- `docs/COMPLETION_MATRIX_V0_9_7.md`
- `docs/V0_9_7_PATCH_REPORT.md`
- `tickets/WAVE-004-v0.9.6-security-production-gate.md`
- `docs/COMPLETION_MATRIX_V0_9_5.md`
- `docs/SECURITY.md`
- `docs/MICRO_PRODUCTION.md`
- `docs/VECTORIZATION_ROUTER.md`
- `docs/PDF_PIPELINE_STUB.md`

## Validation

```text
PYTHONPATH=packages/svs_common:apps/api:apps/worker:apps/model_gateway:apps/instance_agent \
  python -m compileall -f -q packages apps tests scripts
docker run --rm -v "${PWD}:/work" -w /work --network exais-vector-store-local_default \
  -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent \
  localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate \
  python -m pytest -q -rs --ignore=tests/integration
46 passed, 2 warnings
FastAPI routes: 45
OpenAPI paths: 34
```

Wave 009 local Docker proof also booted a registry-pulled cell, returned
`{"ready":true,"db":true,"qdrant":true}` plus HTTP `200`, passed focused
release tests (`20 passed, 2 warnings`), rebuilt the admin UI image, and proved
API/admin access through the Docker cell-network fallback on this Windows host.

The live Postgres RLS integration suite remains wired in `.github/workflows/ci.yml`
under `postgres-rls-integration` and requires a Docker Compose Postgres service
plus `SVS_RUN_INTEGRATION=1`.

## Remaining production integration

This is a Docker-proven local production candidate, not a Docker Hub or VPS
release claim. The remaining work is deployment-specific: provider credentials,
Expert AI Services corpus bakeoffs, load tests against the target corpus,
DNS/TLS/secrets manager wiring, Docker Hub or private-registry push, and restore
drills on the chosen VPS/dedicated-server topology.


## v0.9.8 worker attempt atomicity gate

See `docs/V0_9_8_PATCH_REPORT.md` and `tickets/WAVE-006-v0.9.8-worker-attempt-atomicity.md`. v0.9.8 closes the live multi-pass retry bug found after v0.9.7: failed strict-index attempts could commit partial rows, then a retry could complete through unsafe dedupe.

## v0.9.7 live-Postgres production gate

See `docs/V0_9_7_PATCH_REPORT.md` and `tickets/WAVE-005-v0.9.7-live-postgres-portability.md`. v0.9.7 closes the first live-Postgres blocker found after v0.9.6: raw dict/list values bound into JSONB columns through SQLAlchemy `text()` statements.


## Production environment template

Use `.env.example` for local developer cells. Use `.env.production.example` as
the starting point for customer/micro-production cells. Run
`python scripts/release/prod-env-preflight.py --env-file <cell-env>` before
booting a production cell; it prints variable names and issue classes only.
Production startup also fails closed if dev mode is enabled, the API-key pepper
is still the default, wildcard CORS is configured, or HTTPS OpenSearch
certificate verification is disabled.
