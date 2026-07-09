# WAVE-037 Responses File Search Query Planning

## Summary

Make OpenAI-compatible Responses `file_search` use ExAIS query planning by
default. ExAIS already has a deterministic planner that rewrites simple user
request phrasing and decomposes compound queries; `/v1/responses` should use it
for file-search calls and report the executed subqueries in the
`file_search_call.queries` field.

## Background

Official OpenAI reference checked on 2026-07-08:

- Assistants/File Search "How it works" says file search rewrites user queries,
  breaks down complex user queries into multiple searches it can run in
  parallel, runs both keyword and semantic searches, and reranks results.

ExAIS already has dense + sparse retrieval, RRF, post-ACL checks, rerank, and a
query planner. Native vector-store search can opt into `rewrite_query`, but the
Responses route currently builds search requests without enabling query
planning and returns `file_search_call.queries` as the raw input query.

## Scope

- Enable deterministic query planning for Responses `file_search` searches.
- Run each planned subquery through the existing vector-store search path.
- Report the executed subqueries in `file_search_call.queries`.
- Preserve default direct vector-store search behavior where `rewrite_query`
  remains opt-in.
- Preserve citation markers, annotation indexes, result include gating, stored
  full-response behavior, and existing ranking/ACL behavior.
- Update docs and proof.

## Code Anchors

- `packages/svs_common/svs_common/query_planner.py`
- `packages/svs_common/svs_common/openai_compat.py`
- `apps/api/svs_api/main.py`
- `tests/test_query_planner.py`
- `tests/test_openai_compat_search.py`
- `tests/test_openai_responses_routes.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`

## Out Of Scope

- LLM-based query rewriting.
- New retrieval providers or rerankers.
- Changes to vector-store search default rewrite behavior.
- Streaming Responses output.
- Changes to tenant isolation, API keys, database schema, indexing semantics, or
  provider routing.

## Acceptance Criteria

- [x] Responses `file_search` enables deterministic query planning by default.
- [x] A compound user query runs multiple planned subqueries through the
  existing vector-store search path.
- [x] Returned `file_search_call.queries` contains the executed subqueries, not
  only the raw user input.
- [x] Stored full responses preserve the same executed-query list.
- [x] Included and default result behavior from W36 remains intact.
- [x] Citation annotations remain OpenAI-core shaped and marker indexes still
  point at visible `【n†source】` markers.
- [x] Focused and broad non-integration verification passes.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_query_planner.py tests/test_openai_compat_search.py tests/test_openai_responses_routes.py
36 passed, 2 warnings

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
193 passed, 2 warnings

git diff --check
pass
```

## Notes

This ticket uses deterministic local planning only. It intentionally does not
claim model-grade natural-language query rewriting.
