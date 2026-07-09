# WAVE-105 OpenAI Vector Store CRUD OpenAPI Contract

## Goal

Close the generated OpenAPI contract gap for OpenAI-compatible vector-store
CRUD routes. Runtime route parity already existed; this ticket makes create,
list, retrieve, update, and delete routes advertise named response components
for SDK/client generation.

## OpenAI references

Official OpenAI references checked on 2026-07-09:

- Create vector store:
  https://developers.openai.com/api/reference/resources/vector_stores/methods/create/
- List vector stores:
  https://developers.openai.com/api/reference/resources/vector_stores/methods/list/
- Retrieve vector store:
  https://developers.openai.com/api/reference/resources/vector_stores/methods/retrieve/
- Update vector store:
  https://developers.openai.com/api/reference/resources/vector_stores/methods/update/
- Delete vector store:
  https://developers.openai.com/api/reference/resources/vector_stores/methods/delete/

## Scope

- Add typed schemas for vector-store list and delete responses.
- Attach named response models to existing vector-store create, list, retrieve,
  update, and delete routes.
- Add OpenAPI regression coverage that route responses reference named
  components rather than anonymous objects.
- Preserve existing runtime payloads and ExAIS-native extension fields.

## Out of scope

- Changing vector-store lifecycle behavior, idempotency, rate limits,
  expiration semantics, tenant policy, API-key behavior, file attachment,
  ingestion, indexing, or retrieval ranking.
- Removing ExAIS-native fields from existing runtime responses.
- Changing direct vector-store search, vector-store file, file-batch, or
  Responses behavior.

## Acceptance criteria

- [x] `POST /v1/vector_stores` advertises `VectorStoreResponse`.
- [x] `GET /v1/vector_stores` advertises `VectorStoreListResponse`.
- [x] `GET /v1/vector_stores/{vector_store_id}` advertises
  `VectorStoreResponse`.
- [x] `POST|PATCH /v1/vector_stores/{vector_store_id}` advertise
  `VectorStoreResponse`.
- [x] `DELETE /v1/vector_stores/{vector_store_id}` advertises
  `VectorStoreDeletedResponse`.
- [x] Runtime payload-shape tests preserve existing vector-store object, list,
  and delete response data.

## Changed files

- `apps/api/svs_api/main.py`
- `packages/svs_common/svs_common/schemas.py`
- `tests/test_openapi_contract.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`
- `tickets/README.md`
- `tickets/WAVE-105-openai-vector-store-crud-openapi-contract.md`

## Verification

Focused vector-store CRUD/OpenAPI verification:

```powershell
$pwdPath = (Get-Location).Path; docker run --rm -v "${pwdPath}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openapi_contract.py tests/test_openai_vector_store_object.py
```

Result: `60 passed, 2 warnings in 5.35s`.

Compile verification:

```powershell
$pwdPath = (Get-Location).Path; docker run --rm -v "${pwdPath}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
```

Result: pass.

Broad non-integration verification:

```powershell
$pwdPath = (Get-Location).Path; docker run --rm -v "${pwdPath}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
```

Result: `421 passed, 2 warnings in 6.54s`.

## Quality control

Acceptance criteria:

- [pass] Create advertises `VectorStoreResponse`.
- [pass] List advertises `VectorStoreListResponse`.
- [pass] Retrieve advertises `VectorStoreResponse`.
- [pass] Update aliases advertise `VectorStoreResponse`.
- [pass] Delete advertises `VectorStoreDeletedResponse`.
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
