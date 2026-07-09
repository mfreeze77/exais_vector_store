# WAVE-061 OpenAI Update/Delete Idempotency

## Goal

Close the remaining OpenAI-compatible idempotency gap for retry-sensitive
update, delete, and cancel routes that can otherwise return different results
after a client retry.

## Scope

- Add `Idempotency-Key` handling for:
  - `POST/PATCH /v1/vector_stores/{vector_store_id}`
  - `DELETE /v1/vector_stores/{vector_store_id}`
  - `DELETE /v1/files/{file_id}`
  - `POST/PATCH /v1/vector_stores/{vector_store_id}/files/{file_id}`
  - `DELETE /v1/vector_stores/{vector_store_id}/files/{file_id}`
  - `POST /v1/vector_stores/{vector_store_id}/file_batches/{batch_id}/cancel`
  - `DELETE /v1/responses/{response_id}`
- Reuse the existing `idempotency_keys` table and helper behavior.
- Use stable route/path/body fingerprints.
- Return cached responses for matching retry keys.
- Preserve 409 mismatch behavior for same-key different requests.

## Non-Goals

- Native/admin route idempotency.
- Read-route idempotency.
- Database schema or migration changes.
- Changing object shapes, scopes, RLS, or rate-limit accounting.

## Acceptance Criteria

- [x] Cached matching retries for vector-store update/delete return the original
  payload without re-running the mutation.
- [x] Cached matching retries for OpenAI file delete return the original payload
  without re-running deletion cleanup.
- [x] Cached matching retries for vector-store file update/delete return the
  original payload without re-running the mutation.
- [x] Cached matching retries for file-batch cancel return the original payload
  without re-running queued-job cancellation.
- [x] Cached matching retries for Responses delete return the original payload
  without re-running the delete update.
- [x] Same key with changed route/path/body returns the existing 409 mismatch.
- [x] Existing behavior remains unchanged when `Idempotency-Key` is omitted.

## Verification

- Focused OpenAI file/vector-store/Responses route tests.
- Full non-integration suite.
- `python -m compileall -f -q packages apps tests`.
- `git diff --check`.

## Proof

- Focused OpenAI route tests:
  `python -m pytest -q -rs tests/test_openai_vector_store_object.py tests/test_openai_files.py tests/test_openai_responses_routes.py`
  - Result: 64 passed, 2 warnings.
- Compile:
  `python -m compileall -f -q packages apps tests`
  - Result: passed.
- Full non-integration suite:
  `python -m pytest -q -rs tests --ignore=tests/integration`
  - Result: 288 passed, 2 warnings.
- Whitespace:
  `git diff --check`
  - Result: passed.
- Implementation note: a focused run initially exposed that direct unit calls
  can pass FastAPI's `Header(None)` default as a truthy object. The shared
  OpenAI idempotency helpers now normalize non-string keys to omitted keys, so
  routes skip the idempotency table unless a real header value is supplied.
