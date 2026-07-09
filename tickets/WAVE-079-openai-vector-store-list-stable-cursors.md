# WAVE-079 OpenAI Vector Store List Stable Cursors

## Summary

Make OpenAI-compatible vector-store list pagination deterministic when multiple
vector stores share the same `created_at` timestamp by using `(created_at, id)`
as the cursor and ordering key.

## Background

Vector-store file list pagination already uses a stable `(created_at, id)`
tie-breaker. The vector-store list repository only compared `created_at` for
`after`/`before` cursors and ordered only by `created_at`, so rows with the same
timestamp could be skipped or duplicated across pages.

## Scope

- Fetch cursor `id` and `created_at` for vector-store list `after`/`before`
  cursors.
- Apply `(created_at, id)` comparisons for both ascending and descending order.
- Order vector-store list pages by `created_at` and `id`.
- Add focused SQL-shape regressions for `after` and `before` cursor clauses.
- Document stable cursor behavior.

## Code Anchors

- `packages/svs_common/svs_common/vector_store_repo.py`
- `tests/test_openai_vector_store_object.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`

## Out Of Scope

- Changing list response shape.
- Changing vector-store file, file batch, Responses, API-key, retrieval,
  citation, ranking, tenant, or rate-limit behavior.
- Adding offset pagination or new cursor token formats.

## Acceptance Criteria

- [x] Vector-store list `after` cursors compare both cursor timestamp and ID.
- [x] Vector-store list `before` cursors compare both cursor timestamp and ID.
- [x] Vector-store list ordering includes both `created_at` and `id`.
- [x] Existing tenant/business cursor scoping is preserved.
- [x] Focused and broad non-integration verification passes.

## Verification

Focused vector-store/list verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_vector_store_object.py tests/test_openai_tenant_leakage_guards.py tests/test_openai_files.py
84 passed, 2 warnings
```

Compile verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass
```

Broad non-integration verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
373 passed, 2 warnings
```

Whitespace verification:

```text
git diff --check
pass
```
