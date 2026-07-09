# WAVE-106 OpenAI Files OpenAPI Contract

## Goal

Close the generated OpenAPI contract gap for OpenAI-compatible `/v1/files`
routes. Runtime file upload/list/retrieve/content/delete parity already
existed; this ticket makes JSON routes advertise named response components and
advertises file content as raw text instead of anonymous JSON.

## OpenAI references

Official OpenAI references checked on 2026-07-09:

- Upload file:
  https://developers.openai.com/api/reference/resources/files/methods/create/
- List files:
  https://developers.openai.com/api/reference/resources/files/methods/list/
- Retrieve file:
  https://developers.openai.com/api/reference/resources/files/methods/retrieve/
- Delete file:
  https://developers.openai.com/api/reference/resources/files/methods/delete/
- Retrieve file content:
  https://developers.openai.com/api/reference/resources/files/methods/content/

## Scope

- Add typed schemas for OpenAI file objects, file list pages, and file delete
  responses.
- Attach named response models to existing `/v1/files` upload, list, retrieve,
  and delete routes.
- Advertise `GET /v1/files/{file_id}/content` as `text/plain`, matching the
  current raw content response behavior.
- Add OpenAPI regression coverage that route responses reference named
  components rather than anonymous objects.
- Preserve existing sparse runtime payloads and ExAIS-backed file behavior.

## Out of scope

- Changing upload decoding, PDF conversion, file expiration behavior,
  idempotency, rate limits, document storage, vector-store attachment, tenant
  policy, API-key behavior, ingestion, indexing, or retrieval ranking.
- Adding a JSON body to file-content responses.
- Removing ExAIS support for legacy document IDs on file routes.

## Acceptance criteria

- [x] `POST /v1/files` advertises `OpenAIFile`.
- [x] `GET /v1/files` advertises `OpenAIFileListResponse`.
- [x] `GET /v1/files/{file_id}` advertises `OpenAIFile`.
- [x] `DELETE /v1/files/{file_id}` advertises `OpenAIFileDeletedResponse`.
- [x] `GET /v1/files/{file_id}/content` advertises `text/plain` and not
  `application/json`.
- [x] Runtime payload-shape tests preserve existing file, list, expiring file,
  and delete response data.

## Changed files

- `apps/api/svs_api/main.py`
- `packages/svs_common/svs_common/schemas.py`
- `tests/test_openapi_contract.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`
- `tickets/README.md`
- `tickets/WAVE-106-openai-files-openapi-contract.md`

## Verification

Focused files/OpenAPI verification:

```powershell
$pwdPath = (Get-Location).Path; docker run --rm -v "${pwdPath}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_files.py tests/test_openapi_contract.py
```

Result: `67 passed, 2 warnings in 5.46s`.

Compile verification:

```powershell
$pwdPath = (Get-Location).Path; docker run --rm -v "${pwdPath}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
```

Result: pass.

Broad non-integration verification:

```powershell
$pwdPath = (Get-Location).Path; docker run --rm -v "${pwdPath}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
```

Result: `423 passed, 2 warnings in 7.12s`.

## Quality control

Acceptance criteria:

- [pass] Upload advertises `OpenAIFile`.
- [pass] List advertises `OpenAIFileListResponse`.
- [pass] Retrieve advertises `OpenAIFile`.
- [pass] Delete advertises `OpenAIFileDeletedResponse`.
- [pass] Content advertises `text/plain`, not `application/json`.
- [pass] Focused, compile, broad non-integration, and whitespace verification
  passed.

Findings:

- None.

Required fixes before next ticket:

- None.

Whitespace verification:

```powershell
git diff --check
```

Result: pass.
