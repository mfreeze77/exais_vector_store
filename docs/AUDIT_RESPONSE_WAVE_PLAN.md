# Audit Response and Production-Correctness Wave Plan

This document responds to the external audit that classified the scaffold as a working vertical slice with production gaps. The audit is accepted as accurate. The project now separates work into release-blocking hardening, ingestion correctness, OpenAI-compat completion, router expansion, and research-tier model work.

## Revised status

The scaffold is no longer described as "complete production." It is a production-oriented vertical slice plus a growing ticket trail. Wave 1 in this branch fixes several items that were previously understated as hardening but are actually correctness/security issues.

## Wave 1: Security and consistency blockers

Status in this patch: partially implemented.

- FORCE ROW LEVEL SECURITY added for core tenant tables, including previously missed `api_keys`, `sources`, `instance_deployments`, and `eval_runs`.
- API-key lookup now works with FORCE RLS by setting `svs.api_key_hash` for the lookup transaction and then setting tenant/business/security context after resolution.
- Worker queue polling now works with FORCE RLS via `svs.system_worker` plus tenant context after job claim.
- Endpoint-level scope enforcement added for document writes, retrieval reads, vector-store reads/writes/deletes, API-key creation, and admin tenant creation.
- Qdrant and OpenSearch adapters now raise in strict mode instead of silently returning empty results or ignoring writes.
- OpenSearch TLS verification is no longer hardcoded to `verify_certs=False`; it is controlled by `OPENSEARCH_VERIFY_CERTS`.
- Minimal `/metrics` endpoint added as an observability hook.

## Wave 2: Ingestion correctness

Status in this patch: partially implemented.

- Large ingest requests are queued by default above `SVS_INGEST_INLINE_MAX_BYTES`; inline processing remains available for small docs and forced sync dev cases.
- Content-hash dedupe prevents duplicate documents/vectors inside the same tenant/business/knowledge-base/vector-store scope.
- Basic source/filename versioning now advances `document_versions.version_number`, updates `current_version_id`, and deactivates old chunks.
- Chunk index status columns added: `dense_index_status`, `sparse_index_status`, `indexed_at`, and `last_index_error`.
- Ingestion now writes usage events for indexed chunks.

Remaining Wave 2 work:

- Add a repair/reindex job that picks up chunks where dense/sparse index status is not `indexed`.
- Add qdrant/opensearch cleanup for orphaned points/docs after transaction rollback or partial backend writes.
- Add idempotency keys at the API layer.
- Add migration toolchain through Alembic instead of raw SQL loops.

## Wave 3: OpenAI compatibility and micro-production choices

Status in this patch: partially implemented.

- Vector-store update endpoint added.
- Vector-store file list/get/update/delete/content endpoints added.
- File-batch create/get/list-files endpoints added with queued job integration.
- Basic pagination cursor support added for vector-store and file lists.
- Postgres FTS sparse fallback added for micro-production cells where OpenSearch is too heavy.
- A real dependency-free `code_repo_v1` symbol chunker added, while leaving tree-sitter as the production target.

Remaining Wave 3 work:

- OpenAI-compatible file upload object model, if you want full `/v1/files` behavior.
- Expiration sweeper for `expires_after` / `expires_at`.
- Blue/green per-instance deployments and signed release verification.
- Full OpenAPI spec generation/expansion.

## Deferred research tier

Still deferred intentionally:

- bakeoff runner
- fine-tuning lab
- multimodal PDF embedding
- external model endpoint registration UI/API
- production reranker integration

These remain valuable, but they should not block the security and ingestion-correctness path.
