# WAVE-053 OpenAI Vector Store Search Multi-Query

## Status

Complete.

## Context

The official OpenAI vector-store search reference lists
`POST /vector_stores/{vector_store_id}/search` with `query` typed as
`string or array of string`. ExAIS currently accepts only a single string for
direct OpenAI-compatible vector-store search, even though the route already has
deterministic query planning and result merging for internally planned
subqueries.

This ticket closes that direct-search request-shape gap without changing
Responses behavior, pagination, tenant isolation, indexing, provider routing,
or API-key behavior.

## Scope

- Allow `OpenAIVectorStoreSearchRequest.query` to be a string or an array of
  strings.
- Normalize direct-search query arrays into non-empty string subqueries.
- Preserve existing single-string behavior, including deterministic planning
  when `rewrite_query=true`.
- For query arrays, plan each supplied query when `rewrite_query=true`, merge
  all resulting subqueries through the existing retrieval merge path, and return
  an OpenAI-compatible `search_query` value.
- Keep existing strict OpenAI-style citation annotations and direct-search
  visible citation markers intact.
- Document the supported request shape and proof.

## Out of Scope

- Search pagination/token implementation.
- New filter operators.
- Responses route behavior changes.
- Tenant isolation, API key behavior, indexing semantics, provider routing, and
  deployment changes.

## Acceptance Criteria

- [x] Direct vector-store search accepts a JSON string `query` exactly as before.
- [x] Direct vector-store search accepts a non-empty JSON array of non-empty
  string queries.
- [x] Invalid array forms, including empty arrays or blank query entries, are
  rejected by validation.
- [x] Query arrays execute each normalized query through the existing retrieval
  path and merge results with existing ranking/citation formatting.
- [x] `search_query` preserves the existing string value for single-string
  requests and returns the effective query list for array requests.
- [x] Focused OpenAI compatibility tests cover schema validation, route
  execution, metadata, and response shape.
- [x] Documentation and ticket index are updated.

## Proof

- Official reference checked:
  `https://developers.openai.com/api/reference/resources/vector_stores/methods/search`
  documents `query` as `string or array of string` for vector-store search.
- Focused OpenAI/vector-store compatibility:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_openai_responses_routes.py tests/test_openai_vector_store_object.py`
  - Result: `87 passed, 2 warnings`.
- Compile:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests`
  - Result: pass.
- Full non-integration:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration`
  - Result: `255 passed, 2 warnings`.
- Whitespace:
  `git diff --check`
  - Result: pass.
