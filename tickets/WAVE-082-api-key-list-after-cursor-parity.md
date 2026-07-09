# WAVE-082 API Key List After Cursor Parity

## Objective

Bring the ExAIS admin API-key list closer to OpenAI project API-key list
behavior by adding an `after` object-ID cursor and OpenAI's default page size.

## Evidence Anchors

- Official OpenAI OpenAPI spec for
  `/organization/projects/{project_id}/api_keys`: list supports `limit` and
  `after`, with a default `limit` of 20 and a 1-100 range.
- Existing ExAIS file and vector-store list routes already use stable
  object-ID cursors for OpenAI-compatible list pages.

## Scope

- Add `after` support to `list_api_keys` and
  `GET /api/v1/admin/api-keys`.
- Keep API key responses metadata-only; never expose raw keys or hashes.
- Use `(created_at, id)` as the stable descending cursor ordering key.
- Update focused auth tests and docs.

## Non-Goals

- Adding `before` or `order`; OpenAI project API-key list does not expose those
  controls.
- Changing API-key create, revoke, bearer resolution, scopes, rate limits,
  vector stores, retrieval, or citation behavior.

## Acceptance

- [x] `GET /api/v1/admin/api-keys` defaults to `limit=20`.
- [x] `after` accepts a returned key ID and pages after that object.
- [x] Cursor filtering uses both `created_at` and key ID for stable pagination
  when keys share a timestamp.
- [x] List payloads still omit secret material.
- [x] Focused auth/rate-limit tests pass.
- [x] Compile, broad non-integration tests, and `git diff --check` pass.

## Proof

- Focused auth/rate-limit:
  `python -m pytest -q -rs tests/test_auth_scopes.py tests/test_openai_rate_limits.py`
  -> `23 passed, 2 warnings`
- Compile:
  `python -m compileall -f -q packages apps tests` -> passed
- Broad non-integration:
  `python -m pytest -q -rs tests --ignore=tests/integration` ->
  `379 passed, 2 warnings`
- Whitespace: `git diff --check` -> passed
