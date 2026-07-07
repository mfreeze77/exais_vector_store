# SVS v0.9.6 Production-Wave Execution Report

This release executes the three audit waves against the v2 scaffold and turns the repo into a production-candidate baseline for micro-production cells.

## What changed

### Wave 1 — security and consistency

- FORCE RLS remains enabled on tenant-scoped tables, with v0.9.6 adding RLS policies for model endpoints, ingestion plans, bakeoff runs/results, idempotency keys, rate-limit counters, backup bundles, and deployment locks.
- API-key scopes are enforced across native, admin, maintenance, model, bakeoff, and OpenAI-compatible routes.
- CORS is no longer wildcard; allowed origins are environment-driven.
- Strict dense indexing stays default. Sparse backend now defaults to Postgres FTS for mini cells and can be switched to OpenSearch for standard/large cells.
- Object storage no longer silently discards writes: it uses S3 when available and a local filesystem object store fallback for micro cells; strict mode can fail closed.
- Request rate limiting and idempotency keys are implemented through Postgres tables.

### Wave 2 — ingestion correctness

- Large ingestions enqueue by default above `SVS_INGEST_INLINE_MAX_BYTES`.
- Worker uses `FOR UPDATE SKIP LOCKED`, retries non-terminal failures, and updates file-batch counts.
- Content hash dedupe and source/filename versioning are active in `IngestionService`.
- Chunks carry dense/sparse status and maintenance can repair pending/failed indexes.
- Original and parsed artifacts are persisted to object storage/local-object-store.
- Expiration sweeper marks vector stores expired and deactivates related chunks.
- Small micro-production cells can run without OpenSearch via Postgres generated `tsvector` sparse search.

### Wave 3 — compatibility, router, and ops

- OpenAI-compatible vector store APIs include create/list/get/update/delete, file attach/list/get/update/delete/content, search, file batches, batch cancel, and pagination metadata.
- Ingestion preview endpoint creates persisted ingestion plans and returns parser/chunker/model/retrieval choices with scored model candidates.
- Model endpoint registration APIs are implemented.
- Bakeoff run/result tables and API are implemented with a deterministic proxy runner ready for real provider fan-out.
- Additional chunkers are implemented: code symbols, structured JSON/CSV records, and logs/errors.
- Maintenance APIs support expiration sweeps and reindex jobs.
- `svsctl.py`, backup, restore, fleet-upgrade, and instance-agent deployment/backup/rollback commands are implemented beyond no-op stubs.
- `/metrics` exposes Prometheus-compatible build and queue/index counters.

## Production mode guidance

Use these cell modes deliberately:

| Cell mode | Dense | Sparse | Notes |
|---|---|---|---|
| mini/user vault | Qdrant | Postgres FTS | lowest footprint; no OpenSearch JVM |
| business micro cell | Qdrant | Postgres FTS or OpenSearch | default package supports both |
| standard business cell | Qdrant | OpenSearch | better keyword/code retrieval |
| large/HA cell | Qdrant cluster | OpenSearch cluster | externalize Postgres HA and object storage |

## Still deliberately left as integration work

These require customer/provider infrastructure and cannot be fully validated inside this offline repo build:

- Real provider credentials and production model quality bakeoffs.
- Full load testing against a live 2 TB corpus.
- Production DNS/TLS/secrets manager integration.
- Full HA Postgres/Qdrant/OpenSearch cluster validation.
- Legal/compliance review for regulated customer deployments.

## Validation run

```text
python -m compileall -q packages apps
pytest -q
21 passed, 1 skipped
```


## v0.9.6 security production gate

See `docs/V0_9_6_PATCH_REPORT.md` and `tickets/WAVE-004-v0.9.6-security-production-gate.md`.
