# WAVE-059 OpenAI Mutating Route Idempotency

## Goal

Extend `Idempotency-Key` handling from native ingest/vector-store create to the
OpenAI-compatible create surfaces that can otherwise duplicate user-visible
OpenAI-shaped objects during client retries.

## Scope

- Add route-level idempotency handling for:
  - `POST /v1/files`
  - `POST /v1/vector_stores/{vector_store_id}/files`
  - `POST /v1/vector_stores/{vector_store_id}/file_batches`
  - `POST /v1/responses`
- Reuse the existing `idempotency_keys` table and helper behavior.
- Use stable request fingerprints that include route identity, path IDs, request
  body, and uploaded file content hash where applicable.
- Return the cached response for matching retry keys.
- Return the existing 409 mismatch behavior when the same key is reused with a
  different request.
- Keep streaming Responses compatible by replaying cached response payloads as
  SSE when the original idempotent request was a stream request.

## Non-Goals

- Database schema or migration changes.
- Tenant/RLS/API-key resolution changes.
- Idempotency for deletes, reads, native retrieval, or update routes.
- Changing OpenAI response/file/vector-store object shapes.
- Changing rate-limit accounting.

## Acceptance Criteria

- [x] Repeating `POST /v1/files` with the same `Idempotency-Key` and identical
  upload metadata/content returns the cached file object and does not ingest a
  second file.
- [x] Repeating `POST /v1/vector_stores/{id}/files` with the same key and body
  returns the cached vector-store file object.
- [x] Repeating `POST /v1/vector_stores/{id}/file_batches` with the same key and
  body returns the cached file-batch object.
- [x] Repeating non-streaming `POST /v1/responses` with the same key and body
  returns the cached response without running retrieval again.
- [x] Repeating streaming `POST /v1/responses` with the same key and body
  returns a stream generated from the cached response payload.
- [x] Reusing the same key with a changed body/upload fingerprint returns 409.
- [x] Existing behavior remains unchanged when `Idempotency-Key` is omitted.

## Verification

- Focused OpenAI file/Responses route tests.
- Focused OpenAI compatibility tests if shared helper behavior changes.
- Full non-integration suite.
- `python -m compileall -f -q packages apps tests`.
- `git diff --check`.

## Proof

Focused OpenAI file/Responses idempotency verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_files.py tests/test_openai_responses_routes.py
45 passed, 2 warnings
```

Broader OpenAI compatibility/auth verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_openai_vector_store_object.py tests/test_auth_scopes.py
83 passed, 2 warnings
```

Compile proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass
```

Full non-integration proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
278 passed, 2 warnings
```

Whitespace proof:

```text
git diff --check
pass
```

Notes:

- The two warnings are existing FastAPI `on_event` deprecation warnings.
