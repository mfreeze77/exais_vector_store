# WAVE-045 OpenAI Vector Store Expiration Policy Validation

## Summary

Tighten OpenAI-compatible vector-store `expires_after` handling so create and
update requests accept only the documented OpenAI expiration-policy object:
`{"anchor": "last_active_at", "days": N}`.

## Background

Official OpenAI references checked on 2026-07-08:

- File-search guide: vector-store expiration policies can be set when creating
  or updating a vector store, using `anchor: "last_active_at"` and `days`.

Prior expiration work refreshed `last_active_at`, slid `expires_at`, and failed
closed before retrieval for expired vector stores. The remaining parity gap was
request validation: malformed nested policies could be stored silently and then
behave as no expiration.

## Scope

- Validate `VectorStoreCreateRequest.expires_after`.
- Validate `VectorStoreUpdateRequest.expires_after`.
- Accept only `anchor` and `days` in OpenAI-compatible request bodies.
- Require `anchor == "last_active_at"` and positive integer `days` so inert
  policies fail fast.
- Keep the repo helper tolerant of legacy stored `duration_days` data only when
  the stored anchor is valid.
- Update docs, trail, ticket index, and focused proof.

## Code Anchors

- `packages/svs_common/svs_common/schemas.py`
- `packages/svs_common/svs_common/vector_store_repo.py`
- `tests/test_openai_vector_store_object.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`

## Out Of Scope

- New expiration sweeper behavior.
- New database columns or migrations.
- File upload `expires_after[seconds]` behavior.
- Citation shape changes.
- API key or retrieval ranking changes.

## Acceptance Criteria

- [x] Vector-store create rejects invalid `expires_after` anchors.
- [x] Vector-store create rejects missing, zero, negative, bool, or string
  `days`.
- [x] Vector-store update uses the same validation rules.
- [x] Legacy `duration_days` stored-data handling does not bypass the
  `last_active_at` anchor requirement.
- [x] Activity-refresh SQL ignores zero-day expiration policies.
- [x] Focused and broad non-integration verification passes.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_vector_store_object.py
11 passed, 2 warnings

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
221 passed, 2 warnings

git diff --check
pass
```
