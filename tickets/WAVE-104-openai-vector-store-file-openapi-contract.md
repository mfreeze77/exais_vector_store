# WAVE-104 OpenAI Vector Store File OpenAPI Contract

## Goal

Close the generated OpenAPI contract gap for standalone OpenAI-compatible
vector-store file routes. Runtime route parity already existed; this ticket
makes attach, list, retrieve, update, delete, and content routes advertise
named response components for SDK/client generation.

## OpenAI references

Official OpenAI references checked on 2026-07-09:

- Create vector store file:
  https://developers.openai.com/api/reference/resources/vector_stores/subresources/files/methods/create/
- List vector store files:
  https://developers.openai.com/api/reference/resources/vector_stores/subresources/files/methods/list/
- Retrieve vector store file:
  https://developers.openai.com/api/reference/resources/vector_stores/subresources/files/methods/retrieve/
- Update vector store file attributes:
  https://developers.openai.com/api/reference/resources/vector_stores/subresources/files/methods/update/
- Delete vector store file:
  https://developers.openai.com/api/reference/resources/vector_stores/subresources/files/methods/delete/
- Retrieve vector store file content:
  https://developers.openai.com/api/reference/resources/vector_stores/subresources/files/methods/content/

## Scope

- Add typed schemas for standalone vector-store file list, delete, and parsed
  content responses.
- Attach named response models to existing vector-store file attach, list,
  retrieve, update, delete, and content routes.
- Add OpenAPI regression coverage that route responses reference named
  components rather than anonymous objects.
- Preserve existing runtime payloads and ExAIS-native extension fields.

## Out of scope

- Changing vector-store file lifecycle behavior, idempotency, rate limits,
  ingestion, indexing, tenant policy, API-key behavior, or retrieval ranking.
- Removing ExAIS-native fields from existing runtime responses.
- Changing the current parsed-content payload shape beyond typing the existing
  response.

## Acceptance criteria

- [x] `POST /v1/vector_stores/{vector_store_id}/files` advertises
  `OpenAIVectorStoreFile`.
- [x] `GET /v1/vector_stores/{vector_store_id}/files` advertises
  `OpenAIVectorStoreFileListResponse`.
- [x] `GET|POST|PATCH /v1/vector_stores/{vector_store_id}/files/{file_id}`
  advertises `OpenAIVectorStoreFile`.
- [x] `DELETE /v1/vector_stores/{vector_store_id}/files/{file_id}` advertises
  `OpenAIVectorStoreFileDeletedResponse`.
- [x] `GET /v1/vector_stores/{vector_store_id}/files/{file_id}/content`
  advertises `OpenAIVectorStoreFileContentResponse`.
- [x] Runtime payload-shape tests preserve existing vector-store file list,
  delete, and content response data.

## Changed files

- `apps/api/svs_api/main.py`
- `packages/svs_common/svs_common/schemas.py`
- `tests/test_openai_files.py`
- `tests/test_openapi_contract.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`
- `tickets/README.md`
- `tickets/WAVE-104-openai-vector-store-file-openapi-contract.md`

## Verification

Focused vector-store file/OpenAPI verification:

```powershell
$pwdPath = (Get-Location).Path; docker run --rm -v "${pwdPath}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_files.py tests/test_openapi_contract.py
```

Result: `63 passed, 2 warnings in 5.19s`.

Compile verification:

```powershell
$pwdPath = (Get-Location).Path; docker run --rm -v "${pwdPath}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
```

Result: pass.

Broad non-integration verification:

```powershell
$pwdPath = (Get-Location).Path; docker run --rm -v "${pwdPath}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
```

Result: `419 passed, 2 warnings in 6.17s`.

## Quality control

Acceptance criteria:

- [pass] File attach advertises `OpenAIVectorStoreFile`.
- [pass] File list advertises `OpenAIVectorStoreFileListResponse`.
- [pass] File retrieve/update aliases advertise `OpenAIVectorStoreFile`.
- [pass] File delete advertises `OpenAIVectorStoreFileDeletedResponse`.
- [pass] File content advertises `OpenAIVectorStoreFileContentResponse`.
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
