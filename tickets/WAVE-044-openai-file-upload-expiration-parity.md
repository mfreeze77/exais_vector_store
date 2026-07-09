# WAVE-044 OpenAI File Upload Expiration Parity

## Summary

Honor OpenAI's `/v1/files` multipart `expires_after` upload policy so uploaded
file objects can return `expires_at` when callers request created-at anchored
file expiration.

## Background

Official OpenAI reference checked on 2026-07-08:

- `/v1/files` upload accepts multipart `expires_after[anchor]="created_at"` and
  `expires_after[seconds]=...`.
- OpenAI file objects include `expires_at` when an expiration is configured.
- `/v1/files` list supports `purpose`, `limit`, `order`, and `after`; no
  `before` parameter is part of the current files list reference.

ExAIS already projects `documents.expires_at` as OpenAI file-object
`expires_at`, but `/v1/files` upload currently has no way to set it from the
OpenAI upload request.

## Scope

- Parse `expires_after[anchor]` and `expires_after[seconds]` on
  `POST /v1/files`.
- Accept only `anchor: created_at` for file upload expiration.
- Reject invalid, missing, zero, negative, or non-integer seconds with HTTP 422.
- Persist the computed expiration on the uploaded document row.
- Preserve existing text/PDF upload behavior and file metadata.
- Update file-route tests, docs, and proof.

## Code Anchors

- `apps/api/svs_api/main.py`
- `tests/test_openai_files.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`

## Out Of Scope

- Vector-store `expires_after` behavior.
- Background deletion of expired uploaded files.
- Uploads API multipart session routes.
- Changes to API key behavior, RLS, or indexing semantics.

## Acceptance Criteria

- [x] `/v1/files` accepts `expires_after[anchor]=created_at` and
  `expires_after[seconds]`.
- [x] Uploaded file objects return `expires_at` when upload expiration is
  configured.
- [x] Invalid expiration upload policies fail with HTTP 422 before returning a
  successful file object.
- [x] Existing upload encoding and file-object metadata behavior remains intact.
- [x] Focused and broad non-integration verification passes.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_files.py
17 passed, 2 warnings

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
219 passed, 2 warnings

git diff --check
pass
```
