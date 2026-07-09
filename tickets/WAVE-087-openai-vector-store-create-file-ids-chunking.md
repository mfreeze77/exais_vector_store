# WAVE-087 OpenAI Vector Store Create File IDs Chunking

## Objective

Close the OpenAI vector-store create parity gap where `POST /v1/vector_stores`
accepted `file_ids` and `chunking_strategy` but did not apply the request-level
chunking strategy to the files attached during the create call.

## Evidence Anchors

- OpenAI vector-store create reference: `chunking_strategy` is the chunking
  strategy for the file(s), defaults to auto when unset, and is applicable only
  when `file_ids` is non-empty.
  https://developers.openai.com/api/reference/resources/vector_stores/methods/create
- OpenAI file-batch reference: request-level `chunking_strategy` applies to all
  `file_ids` when that list form is used.
  https://developers.openai.com/api/reference/resources/vector_stores/subresources/file_batches/methods/create
- `apps/api/svs_api/main.py`
- `tests/test_openai_vector_store_object.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`

## Scope

- Preserve vector-store create validation and idempotency behavior.
- For create requests with `file_ids` and `chunking_strategy`, pass the
  normalized chunking strategy into `_attach_existing_document_ids_to_vector_store`
  as vector-store file attachment metadata.
- Do not copy vector-store `metadata` into file attributes.
- Add focused regression proof and docs.

## Non-Goals

- Changing chunking strategy validation rules.
- Changing file-batch, standalone file-attach, retrieval, citation, API-key,
  tenant isolation, database, indexing, provider, deployment, or admin UI
  behavior.

## Acceptance

- [x] `POST /v1/vector_stores` with `file_ids` and valid `chunking_strategy`
  passes normalized `_openai_chunking_strategy` to attached vector-store files.
- [x] Store-level vector-store `metadata` is not copied to file attributes.
- [x] Existing invalid chunking strategy validation remains unchanged.
- [x] Docs describe create-with-`file_ids` chunking propagation.
- [x] Focused vector-store/file/OpenAPI tests pass.
- [x] Compile, broad non-integration tests, and `git diff --check` pass.

## Proof

- Focused vector-store/file/OpenAPI:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_vector_store_object.py tests/test_openai_files.py tests/test_openapi_contract.py`
  passed with `92 passed, 2 warnings in 3.86s`.
- Compile:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests`
  passed.
- Broad non-integration:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration`
  passed with `385 passed, 2 warnings in 4.93s`.
- Whitespace:
  `git diff --check` passed.
