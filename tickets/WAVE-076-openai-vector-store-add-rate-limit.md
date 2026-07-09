# WAVE-076 OpenAI Vector Store Add Rate Limit

## Summary

Add OpenAI-compatible per-vector-store request limiting for file attach and
file-batch create routes, sharing one 300 requests/minute budget per vector
store ID.

## Background

The official OpenAI Retrieval guide states that adding files is rate limited per
vector store ID, and that requests to
`/vector_stores/{vector_store_id}/files` and
`/vector_stores/{vector_store_id}/file_batches` share a 300 requests/minute
limit. ExAIS already has per-principal route buckets, but these two write paths
do not share a per-vector-store budget yet.

Official reference checked on 2026-07-09:

- https://developers.openai.com/api/docs/guides/retrieval#vector-store-file-operations

## Scope

- Add a resource-scoped rate-limit helper using the existing
  `rate_limit_counters` table.
- Add a configurable `SVS_VECTOR_STORE_FILE_ADD_RATE_LIMIT_PER_MINUTE` setting
  defaulting to 300.
- Enforce the shared vector-store add budget on:
  - `POST /v1/vector_stores/{vector_store_id}/files`
  - `POST /v1/vector_stores/{vector_store_id}/file_batches`
- Keep existing per-principal route buckets in place.
- Add focused tests proving the shared budget blocks before idempotency,
  attachment, batch row creation, or enqueue.
- Update docs, env examples, ticket trail, ticket index, and proof.

## Out Of Scope

- Changing API-key resolution, scopes, RLS, database schema, retrieval ranking,
  indexing semantics, provider routing, deployment, or admin UI behavior.
- Changing OpenAI route response shapes.
- Adding distributed cache or Redis-backed rate limiting.
- Applying this limit to vector-store create-with-`file_ids`; the documented
  limit is for the vector-store file and file-batch subresource routes.

## Code Anchors

- `packages/svs_common/svs_common/request_controls.py`
- `packages/svs_common/svs_common/config.py`
- `apps/api/svs_api/main.py`
- `tests/test_openai_rate_limits.py`
- `.env.example`
- `.env.production.example`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`
- `tickets/README.md`

## Acceptance Criteria

- [x] Vector-store file attach consumes both the existing route bucket and a
  shared per-vector-store add-file bucket.
- [x] File-batch create consumes both the existing route bucket and the same
  shared per-vector-store add-file bucket.
- [x] Per-vector-store add limits fail before idempotency lookup, document
  attach, batch row insert, inline ingest enqueue, or commit.
- [x] System principals continue to bypass request-rate accounting.
- [x] Focused rate-limit tests pass.
- [x] Compile, broad non-integration, and whitespace verification pass.

## Verification

- `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_rate_limits.py tests/test_openai_files.py tests/test_openai_vector_store_object.py`
  - Result: 84 passed, 2 warnings.
- `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests`
  - Result: pass.
- `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration`
  - Result: 367 passed, 2 warnings.
- `git diff --check`
  - Result: pass.
