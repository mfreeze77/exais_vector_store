# WAVE-001 Security and Correctness Hardening

## Goal
Close the gap between a working demo and a production-safe micro-production cell by enforcing database isolation, endpoint scopes, and strict index-write behavior.

## Subagent assignments

- Security agent: RLS, API key resolution, scopes, CORS/TLS defaults.
- Ingestion agent: dedupe, versioning, async queue, index statuses.
- Retrieval agent: strict adapter behavior, Postgres sparse fallback, usage events.
- Compatibility agent: OpenAI vector-store file/batch endpoints.
- QA agent: regression tests, migration tests, smoke tests.

## Acceptance criteria

- App table owner cannot bypass tenant RLS on protected tables.
- API key lookup works under FORCE RLS without exposing cross-tenant rows.
- Every protected endpoint rejects missing scopes with HTTP 403.
- Qdrant/OpenSearch write failures do not mark documents indexed.
- Large ingestion uses the queue by default.
- Duplicate content in the same scope returns deduplicated instead of duplicating vectors.
- Same source/filename with changed content advances document version.
- Vector-store files and file batches have list/get/content/update/delete surfaces.
- Micro-production cells can use Postgres FTS fallback when OpenSearch is disabled.

## Implemented in this patch

See `docs/AUDIT_RESPONSE_WAVE_PLAN.md`.

## Still open

- Reindex repair worker.
- Expiration sweeper.
- Idempotency keys.
- Alembic migration conversion.
- Full OpenAPI spec.
- Real tree-sitter chunker.
- Production Prometheus metrics and dashboards.
