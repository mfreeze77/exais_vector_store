# WAVE-072 OpenAI Vector Store Search OpenAPI Response Contract

## Summary

Expose the direct OpenAI-compatible vector-store search response shape in
generated `/openapi.json` so clients can discover the page, result, content, and
citation annotation structure returned by `POST /v1/vector_stores/{id}/search`.

## Background

Official OpenAI references checked on 2026-07-09:

- OpenAI API endpoint index includes:
  `POST /v1/vector_stores/{vector_store_id}/search`.
  https://api.openai.com/v1/vector_stores/{vector_store_id}/search
- File search guide: Responses file-search result rows are opt-in through
  `include`, while annotations are visible in generated output text.
  https://developers.openai.com/api/docs/guides/tools-file-search#include-search-results-in-the-response

ExAIS already returns direct vector-store search pages with OpenAI-shaped result
rows, strict `file_citation` annotations, visible markers when content is
included, native citation proof, and output-guard metadata outside the
OpenAI-facing annotation object. WAVE-071 exposed the same strict citation
contract for Responses OpenAPI components; this ticket extends schema visibility
to the direct vector-store search surface.

## Scope

- Add typed Pydantic components for:
  - `OpenAIVectorStoreSearchResultsPage`
  - `OpenAIVectorStoreSearchResult`
  - `OpenAIVectorStoreSearchContent`
  - `OpenAIVectorStoreSearchCitation`
- Reuse the strict `OpenAIFileCitationAnnotation` component for result-level and
  content-level annotations.
- Wire `POST /v1/vector_stores/{vector_store_id}/search` to the named response
  model while preserving runtime payload shape with
  `response_model_exclude_unset=True`.
- Add OpenAPI and model-dump shape-preservation tests.
- Update docs, ticket trail, ticket index, and proof.

## Code Anchors

- `packages/svs_common/svs_common/schemas.py`
- `apps/api/svs_api/main.py`
- `tests/test_openapi_contract.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`
- `tickets/README.md`

## Out Of Scope

- Changing vector-store search ranking, query planning, retrieval execution, ACL
  checks, tenant isolation, API key behavior, database schema, indexing,
  provider routing, deployment, or admin UI behavior.
- Changing citation marker text, annotation indexes, output guard behavior, or
  native citation proof fields.
- Claiming exact upstream OpenAPI schema parity where the local OpenAI docs MCP
  endpoint spec fetcher did not resolve the templated search route.

## Acceptance Criteria

- [x] `/openapi.json` for `POST /v1/vector_stores/{vector_store_id}/search`
  references `OpenAIVectorStoreSearchResultsPage` as its JSON response schema.
- [x] The direct search page schema nests named result, content, and citation
  components.
- [x] Result-level and content-level `annotations` reference the strict
  `OpenAIFileCitationAnnotation` component.
- [x] The response model preserves the current direct search citation payload
  shape under `model_dump(..., exclude_unset=True)`.
- [x] Focused OpenAPI/vector-store search compatibility verification passes.
- [x] Compile, broad non-integration, and whitespace verification passes.

## Verification

Focused OpenAPI/vector-store search contract verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openapi_contract.py tests/test_openai_compat_search.py tests/test_openai_vector_store_object.py
91 passed, 2 warnings
```

Compile verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass
```

Broad non-integration verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
320 passed, 2 warnings
```

Whitespace verification:

```text
git diff --check
pass
```
