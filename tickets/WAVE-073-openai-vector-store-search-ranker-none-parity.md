# WAVE-073 OpenAI Vector Store Search Ranker None Parity

## Summary

Honor OpenAI's direct vector-store search `ranking_options.ranker: "none"` by
disabling ExAIS request-scoped reranking and diversity while preserving the
state-of-art default retrieval profile for `auto`.

## Background

Official OpenAI reference checked on 2026-07-09:

- Direct vector-store search accepts `ranking_options.ranker` values `none`,
  `auto`, and `default-2024-11-15`; the reference describes `none` as disabling
  re-ranking to reduce latency.
  https://platform.openai.com/docs/api-reference/vector-stores/search

ExAIS already validates those documented ranker values and records the requested
ranker in OpenAI-compat search metadata, but the retrieval path still used the
selected retrieval profile's local/model reranker for all ranker values. That
made `ranker: "none"` a metadata-only field.

## Scope

- Derive an effective per-request retrieval profile from
  `SearchRequest.search_metadata`.
- When OpenAI-compatible metadata requests `ranker: "none"`, disable reranking
  and lexical MMR diversity for that request only.
- Keep `auto` and `default-2024-11-15` on the configured retrieval profile.
- Record the request-scoped ranker override in retrieval audit metadata.
- Add focused unit tests and update compatibility docs.

## Code Anchors

- `packages/svs_common/svs_common/retrieval.py`
- `packages/svs_common/svs_common/openai_compat.py`
- `tests/test_openai_compat_search.py`
- `tests/test_retrieval_profile_resolution.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`
- `tickets/README.md`

## Out Of Scope

- Changing dense/sparse retrieval, fusion, score normalization, score-threshold
  behavior, file filters, citations, output guards, API-key behavior, tenant
  isolation, database schema, indexing, provider routing, deployment, or admin
  UI behavior.
- Implementing a remote OpenAI ranker or making `default-2024-11-15` call an
  external provider. ExAIS continues to map `auto` and `default-2024-11-15` to
  configured retrieval profiles.

## Acceptance Criteria

- [x] `ranking_options.ranker: "none"` disables profile rerank and diversity for
  that direct OpenAI-compatible search request.
- [x] `ranking_options.ranker: "auto"` continues to use the configured
  retrieval profile's reranker.
- [x] Retrieval audit metadata records that `openai_ranking_options.ranker`
  disabled reranking when `none` is requested.
- [x] Docs describe the `none` behavior without weakening the default
  state-of-art retrieval profile.
- [x] Focused OpenAI compatibility/retrieval profile tests pass.
- [x] Compile, broad non-integration, and whitespace verification passes.

## Verification

Focused OpenAI compatibility/retrieval profile verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_retrieval_profile_resolution.py
115 passed
```

Compile verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass
```

Broad non-integration verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
323 passed, 2 warnings
```

Whitespace verification:

```text
git diff --check
pass
```
