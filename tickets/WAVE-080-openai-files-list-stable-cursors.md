# WAVE-080 OpenAI Files List Stable Cursors

## Summary

Make OpenAI-compatible `/v1/files` list pagination deterministic when uploaded
files share the same `created_at` timestamp by using `(created_at, public file
ID)` as the cursor and ordering key.

## Background

The current OpenAI `/v1/files` list reference exposes `purpose`, `limit`,
`order`, and `after` query parameters. ExAIS already supports those parameters,
but the `after` cursor only compared `documents.created_at`. When multiple
files shared the same timestamp, a page boundary could skip same-timestamp rows
instead of treating the cursor file ID as the caller's exact place in the list.

## Scope

- Project the OpenAI public file ID from the shared file-select SQL.
- Apply `(created_at, public file ID)` comparisons for `/v1/files` `after`
  cursors in ascending and descending order.
- Order `/v1/files` pages by `created_at` and public file ID.
- Add focused SQL-shape regressions for ascending and descending cursor clauses.
- Document stable file-list cursor behavior.

## Code Anchors

- `apps/api/svs_api/main.py`
- `tests/test_openai_files.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`
- `tickets/README.md`

## Out Of Scope

- Adding a `/v1/files` `before` parameter, which is not part of the current
  OpenAI files list reference.
- Changing list response shape.
- Changing vector-store, vector-store-file, file-batch, citation, retrieval,
  tenant, rate-limit, API-key, or indexing behavior.

## Acceptance Criteria

- [x] `/v1/files` `after` cursors compare both cursor timestamp and public file
  ID.
- [x] `/v1/files` ordering includes both `created_at` and public file ID.
- [x] Existing OpenAI file-list parameters remain `purpose`, `limit`, `order`,
  and `after`.
- [x] Existing tenant/business cursor scoping is preserved.
- [x] Focused and broad non-integration verification passes.

## Verification

Focused OpenAI file/list verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_files.py tests/test_openai_vector_store_object.py tests/test_openai_tenant_leakage_guards.py
86 passed, 2 warnings
```

Compile verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass
```

Broad non-integration verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
375 passed, 2 warnings
```

Whitespace verification:

```text
git diff --check
pass
```
