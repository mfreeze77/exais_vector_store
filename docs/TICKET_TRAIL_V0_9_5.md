# Ticket Trail — v0.9.5 Production Waves

## Wave 1: Security and consistency baseline

- SEC-001 FORCE RLS coverage — done for new and existing production tables.
- SEC-002 API-key scopes — done across route surfaces.
- SEC-003 CORS/env guardrails — done.
- SEC-004 Strict adapter behavior — done; Qdrant strict remains default.
- SEC-005 Object store fail-closed/local fallback — done.
- SEC-006 Rate limits — done through `rate_limit_counters`.
- SEC-007 Idempotency keys — done through `idempotency_keys`.

## Wave 2: Ingestion correctness

- ING-001 Async-by-default large ingestion — done.
- ING-002 Durable job polling — done with retries and terminal failure handling.
- ING-003 Content-hash dedupe — done.
- ING-004 Real versioning — done by `source_uri`/filename target and `document_versions`.
- ING-005 Per-chunk index status — done.
- ING-006 Reindex repair job — done.
- ING-007 Artifact persistence — done with S3/local object store.
- ING-008 Expiration sweeper — done.
- ING-009 Postgres FTS small-cell backend — done.

## Wave 3: Compat, router, ops

- OAI-001 Vector store CRUD — done.
- OAI-002 File APIs — done.
- OAI-003 File content retrieval — done.
- OAI-004 File batches + cancel — done.
- OAI-005 Pagination metadata — done.
- RTR-001 Ingestion preview endpoint — done.
- RTR-002 Model endpoint registry — done.
- RTR-003 Candidate scorer — done.
- RTR-004 Structured/log chunkers — done.
- EVAL-001 Bakeoff tables/API — done, with proxy runner.
- OPS-001 Metrics endpoint — done.
- OPS-002 svsctl deploy/backup/restore/fleet-upgrade — done.
- OPS-003 Instance agent backup/rollback — done.

## Release gate

v0.9.5 is a production-candidate micro-cell release. Before customer production, run a live restore drill, live provider bakeoff, and tenant-isolation test against the target infrastructure.
