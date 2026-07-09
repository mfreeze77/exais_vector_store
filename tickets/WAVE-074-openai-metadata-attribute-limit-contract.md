# WAVE-074 OpenAI Metadata Attribute Limit Contract

## Summary

Enforce OpenAI-compatible metadata and vector-store-file attribute limits at
write time so searchable file attributes and vector-store metadata cannot drift
from the documented OpenAI contract or overwrite ExAIS internal state.

## Background

Official OpenAI references checked on 2026-07-09:

- Vector-store create metadata is documented as 16 key-value pairs, with keys up
  to 64 characters and string values up to 512 characters.
  https://developers.openai.com/api/reference/resources/vector_stores/methods/create
- Vector-store file update attributes are documented as 16 key-value pairs, with
  keys up to 64 characters and values limited to strings, numbers, or booleans;
  string values are capped at 512 characters.
  https://developers.openai.com/api/reference/resources/vector_stores/subresources/files/methods/update
- File-batch request attributes and per-file `files[].attributes` use the same
  scalar attribute contract and a 2000-file batch cap.
  https://developers.openai.com/api/reference/resources/vector_stores/subresources/file_batches/methods/create

ExAIS already enforces safe filtering at query time, but vector-store metadata
and vector-store-file attributes could still be written with nested values,
oversized maps, oversized strings, sensitive searchable keys, or reserved
internal keys.

## Scope

- Add a shared OpenAI metadata/attribute contract helper.
- Validate vector-store create/update `metadata` and legacy `attributes`.
- Validate vector-store file attach/update attributes and file-batch global and
  per-file attributes.
- Reject ExAIS reserved internal attribute names on public write paths.
- Preserve existing internal `description`, `chunking_strategy`, attachment,
  and batch bookkeeping fields.
- Update docs, ticket trail, ticket index, and proof.

## Code Anchors

- `packages/svs_common/svs_common/openai_metadata.py`
- `packages/svs_common/svs_common/openai_compat.py`
- `packages/svs_common/svs_common/schemas.py`
- `packages/svs_common/svs_common/vector_store_repo.py`
- `apps/api/svs_api/main.py`
- `tests/test_openai_files.py`
- `tests/test_openai_vector_store_object.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`
- `tickets/README.md`

## Out Of Scope

- Changing search ranking, retrieval execution, citations, filters, API-key
  behavior, tenant isolation, database schema, indexing, provider routing,
  deployment, or admin UI behavior.
- Backfilling or mutating old persisted metadata rows.
- Changing native document-ingest attributes outside the OpenAI-compatible
  vector-store/file write surfaces.

## Acceptance Criteria

- [x] Vector-store metadata accepts documented string maps and rejects maps over
  16 entries, empty/oversized keys, oversized strings, non-string values, and
  reserved internal keys.
- [x] Vector-store-file attributes accept documented scalar maps and reject maps
  over 16 entries, empty/oversized/unsafe keys, oversized strings, nested values,
  sensitive searchable keys, non-finite numbers, and reserved internal keys.
- [x] File attach, file update, file-batch global attributes, and file-batch
  per-file attributes share the same validation contract.
- [x] Existing internal ExAIS attributes for attachment pointers, file batches,
  chunking strategy, vector-store description, and vector-store chunking
  strategy remain internal and preserved.
- [x] Focused OpenAI metadata/file/vector-store compatibility tests pass.
- [x] Compile, broad non-integration, and whitespace verification passes.

## Verification

- `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_files.py tests/test_openai_vector_store_object.py tests/test_openai_compat_search.py`
  - Result: 146 passed, 2 warnings.
- `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests`
  - Result: pass.
- `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration`
  - Result: 360 passed, 2 warnings.
- `git diff --check`
  - Result: pass.
