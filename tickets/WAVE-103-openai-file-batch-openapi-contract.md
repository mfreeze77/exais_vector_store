# WAVE-103 OpenAI File Batch OpenAPI Contract

## Goal

Close the generated OpenAPI contract gap for OpenAI-compatible vector-store file
batches. Runtime route parity already existed; this ticket makes those routes
advertise named, typed response components for SDK/client generation.

## OpenAI references

Official OpenAI references checked on 2026-07-09:

- Create vector store file batch:
  https://developers.openai.com/api/reference/resources/vector_stores/subresources/file_batches/methods/create/
- Retrieve vector store file batch:
  https://developers.openai.com/api/reference/resources/vector_stores/subresources/file_batches/methods/retrieve/
- List vector store files in a batch:
  https://developers.openai.com/api/reference/resources/vector_stores/subresources/file_batches/methods/list_files/
- Cancel vector store file batch:
  https://developers.openai.com/api/reference/resources/vector_stores/subresources/file_batches/methods/cancel/

## Scope

- Add typed schemas for OpenAI-compatible vector-store file-batch objects,
  file-batch counts, vector-store file objects, and batch file-list pages.
- Attach those schemas as `response_model`s to existing file-batch create,
  retrieve, cancel, and list-files routes.
- Add OpenAPI regression coverage that route responses reference named
  components rather than anonymous objects.
- Preserve existing runtime payloads and ExAIS-native extension fields.

## Out of scope

- Adding new OpenAI routes not present in the current official reference.
- Changing file-batch lifecycle behavior, idempotency, rate limits, ingestion,
  indexing, tenant policy, API-key behavior, or retrieval ranking.
- Removing ExAIS-native fields from existing runtime responses.

## Acceptance criteria

- [x] `POST /v1/vector_stores/{vector_store_id}/file_batches` advertises
  `OpenAIVectorStoreFileBatch`.
- [x] `GET /v1/vector_stores/{vector_store_id}/file_batches/{batch_id}`
  advertises `OpenAIVectorStoreFileBatch`.
- [x] `POST /v1/vector_stores/{vector_store_id}/file_batches/{batch_id}/cancel`
  advertises `OpenAIVectorStoreFileBatch`.
- [x] `GET /v1/vector_stores/{vector_store_id}/file_batches/{batch_id}/files`
  advertises `OpenAIVectorStoreFileBatchFilesPage`.
- [x] The file-list page schema nests `OpenAIVectorStoreFile`, and runtime
  payload-shape tests preserve existing batch/file response data.

## Changed files

- `apps/api/svs_api/main.py`
- `packages/svs_common/svs_common/schemas.py`
- `tests/test_openai_files.py`
- `tests/test_openapi_contract.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`
- `tickets/README.md`
- `tickets/WAVE-103-openai-file-batch-openapi-contract.md`

## Verification

Focused file-batch/OpenAPI verification:

```powershell
$pwdPath = (Get-Location).Path; docker run --rm -v "${pwdPath}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_files.py tests/test_openapi_contract.py
```

Result: `60 passed, 2 warnings in 4.96s`.

Compile verification:

```powershell
$pwdPath = (Get-Location).Path; docker run --rm -v "${pwdPath}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
```

Result: pass.

Broad non-integration verification:

```powershell
$pwdPath = (Get-Location).Path; docker run --rm -v "${pwdPath}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
```

Result: `416 passed, 2 warnings in 6.03s`.

## Quality control

Acceptance criteria:

- [pass] File-batch create advertises `OpenAIVectorStoreFileBatch`.
- [pass] File-batch retrieve advertises `OpenAIVectorStoreFileBatch`.
- [pass] File-batch cancel advertises `OpenAIVectorStoreFileBatch`.
- [pass] File-batch list-files advertises
  `OpenAIVectorStoreFileBatchFilesPage`.
- [pass] Batch file-list pages nest `OpenAIVectorStoreFile` and model tests
  preserve existing runtime payloads.
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
