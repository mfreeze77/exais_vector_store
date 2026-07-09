# WAVE-088 OpenAI Vector Store Search Next Page Cursor

## Objective

Close the OpenAI direct vector-store search parity gap where
`POST /v1/vector_stores/{vector_store_id}/search` returned the page fields
`has_more` and `next_page` but did not accept a request `next_page` cursor or
produce a real follow-up cursor.

## Evidence Anchors

- OpenAI vector-store search reference: direct search accepts `next_page` and
  returns `vector_store.search_results.page` objects with `has_more` and
  `next_page`.
  https://developers.openai.com/api/reference/resources/vector_stores/methods/search/
- OpenAI API reference SDK examples note that vector-store search pages can be
  auto-fetched as additional pages are needed.
  https://developers.openai.com/api/reference/resources/vector_stores/methods/search/
- `packages/svs_common/svs_common/schemas.py`
- `packages/svs_common/svs_common/openai_compat.py`
- `apps/api/svs_api/main.py`
- `tests/test_openai_compat_search.py`
- `tests/test_openai_vector_store_object.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`

## Scope

- Add OpenAI-compatible `next_page` to the direct vector-store search request
  model.
- Emit opaque ExAIS direct-search cursor tokens when a ranked direct-search page
  has more results.
- Accept the opaque token on the next direct-search request and return the next
  ranked slice.
- Keep token handling bounded and fail closed for invalid or unsupported cursor
  tokens.
- Preserve existing query planning, filters, ranking options, citation shape,
  output guard, tenant checks, API-key behavior, and Responses file-search
  behavior.
- Add focused regression proof and docs.

## Non-Goals

- Changing list cursor behavior for vector stores, files, file batches, API
  keys, or Responses input-items.
- Adding persistent server-side search snapshots.
- Changing retrieval ranking, citation annotation shape, OpenAPI citation
  components, tenant isolation, API-key lifecycle behavior, database migrations,
  provider routing, deployment, or admin UI behavior.

## Acceptance

- [x] `OpenAIVectorStoreSearchRequest` accepts `next_page`.
- [x] Direct search over-fetches one ranked candidate to compute `has_more`.
- [x] Direct search returns an opaque `next_page` token when another ranked
  slice is available.
- [x] Supplying the token returns the next ranked slice.
- [x] Invalid or out-of-window cursor tokens fail closed.
- [x] Existing OpenAI citation shape and Responses file-search behavior remain
  unchanged.
- [x] Docs describe direct-search `next_page` cursor behavior.
- [x] Focused OpenAI compatibility/vector-store/OpenAPI tests pass.

## Proof

- Focused OpenAI/vector-store/OpenAPI:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_openai_vector_store_object.py tests/test_openapi_contract.py`
  passed with `124 passed, 2 warnings in 4.16s`.
- Compile:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests`
  passed.
- Broad non-integration:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration`
  passed with `389 passed, 2 warnings in 5.59s`.
- Whitespace:
  `git diff --check` passed.
