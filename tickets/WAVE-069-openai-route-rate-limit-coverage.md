# WAVE-069 OpenAI Route Rate-Limit Coverage

## Summary

Close the remaining OpenAI-compatible API route coverage gap by applying the
existing per-principal Postgres rate limiter to OpenAI file, vector-store,
Responses, and API-key lifecycle routes that were still reachable without a
request-control bucket.

## Background

Repo references checked on 2026-07-09:

- `packages/svs_common/svs_common/request_controls.py` already implements
  `enforce_rate_limit` using `rate_limit_counters` with per-minute buckets.
- `db/migrations/005_production_waves.sql` already creates the
  `rate_limit_counters` table, index, FORCE RLS, and tenant/business policy.
- `docs/COMPLETION_MATRIX.md` still calls out API rate-limit coverage as a
  production hardening lane.
- Several native routes and `POST /v1/files`/`POST /v1/vector_stores` already
  call `enforce_rate_limit`, but OpenAI-compatible lifecycle/search routes do
  not apply it consistently.

## Scope

- Add explicit rate-limit buckets to uncovered OpenAI-compatible file,
  vector-store, vector-store file/batch, Responses, and API-key lifecycle
  route handlers.
- Keep the existing limit values, table, RLS policies, subject derivation, and
  `system` bypass behavior unchanged.
- Ensure rate-limit rejection happens before expensive retrieval, ingestion,
  mutation, or stored-response work on representative routes.
- Add focused regression tests for bucket coverage and fail-before-work
  behavior.
- Update OpenAI compatibility/API docs and ticket trail.

## Code Anchors

- `apps/api/svs_api/main.py`
- `tests/test_openai_rate_limits.py`
- `tests/test_openai_files.py`
- `tests/test_openai_responses_routes.py`
- `tests/test_openai_vector_store_object.py`
- `tests/test_auth_scopes.py`
- `tests/test_openai_tenant_leakage_guards.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/COMPLETION_MATRIX.md`
- `docs/TICKET_TRAIL.md`

## Out Of Scope

- Changing API-key hashing, lookup, scope semantics, or returned metadata.
- Changing default/admin rate-limit values.
- Adding Redis/Valkey distributed rate limiting.
- Changing database schema, RLS policies, retrieval ranking, indexing, provider
  routing, deployment, or admin UI behavior.

## Acceptance Criteria

- [x] OpenAI-compatible file, vector-store, vector-store file/batch,
  Responses, and admin API-key lifecycle routes call `enforce_rate_limit` with
  stable route-specific buckets after scope checks.
- [x] Representative create/search/response routes return 429 before expensive
  retrieval, ingestion, mutation, or stored-response lookup when the limiter
  rejects the request.
- [x] Existing idempotency, citation, tenant-scope, and vector-store parity
  tests continue to pass with rate-limit behavior isolated from their fake DB
  assumptions.
- [x] Docs describe the per-principal OpenAI-compatible route buckets and keep
  limit values tied to existing settings.
- [x] Focused and broad non-integration verification passes.

## Verification

Focused OpenAI route rate-limit and adjacent route verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_rate_limits.py tests/test_openai_responses_routes.py tests/test_openai_files.py tests/test_openai_vector_store_object.py tests/test_auth_scopes.py tests/test_openai_tenant_leakage_guards.py
97 passed, 2 warnings
```

Compile verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass
```

Broad non-integration verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
312 passed, 2 warnings
```

Whitespace verification:

```text
git diff --check
pass
```
