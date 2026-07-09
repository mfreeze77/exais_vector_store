# WAVE-081 Phrase-Aware Sparse Retrieval

## Summary

Improve sparse keyword retrieval for OpenAI-compatible vector-store search by
making both local sparse backends phrase-aware while preserving existing
filters, ACL hydration, RRF fusion, reranking, and citation behavior.

## Background

Official OpenAI file-search guidance checked on 2026-07-09 describes retrieval
as using both keyword and semantic search, query rewriting, and reranking before
answer generation. ExAIS already runs dense semantic search, sparse keyword
search, RRF fusion, deterministic query planning, reranking, and citation
guards. The remaining local sparse weakness is phrase handling:

- The Postgres FTS fallback uses `plainto_tsquery`, which ignores web-search
  style phrase/operator intent.
- The OpenSearch backend sends a single `match` query, so exact phrase evidence
  is not explicitly boosted before RRF and rerank.

## Scope

- Use `websearch_to_tsquery('english', :query)` for Postgres sparse fallback
  matching and ranking.
- Make OpenSearch sparse search send a phrase-aware boolean text query with
  `match_phrase`, all-term `match`, and broad `match` alternatives.
- Preserve existing tenant/business/security filters and file-attribute filter
  clauses.
- Add focused SQL/body-shape regressions.
- Document phrase-aware sparse retrieval.

## Code Anchors

- `packages/svs_common/svs_common/retrieval.py`
- `packages/svs_common/svs_common/opensearch_adapter.py`
- `tests/test_retrieval_profile_resolution.py`
- `tests/test_opensearch_adapter.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`
- `tickets/README.md`

## Out Of Scope

- Changing public OpenAI request or response shapes.
- Changing dense vector indexing/search, RRF math, reranker selection, citation
  markers, API-key behavior, tenant isolation, migrations, or provider routing.
- Adding a new external reranker dependency.

## Acceptance Criteria

- [x] Postgres sparse search uses `websearch_to_tsquery` for match and rank.
- [x] OpenSearch sparse search includes a boosted exact phrase clause plus
  all-term and broad match alternatives.
- [x] Existing scope and file-attribute filters remain in the same filter
  branches.
- [x] Focused retrieval/OpenSearch tests cover the new sparse query shapes.
- [x] Focused and broad non-integration verification passes.

## Verification

Focused retrieval/OpenSearch verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_retrieval_profile_resolution.py tests/test_opensearch_adapter.py tests/test_openai_compat_search.py
125 passed
```

Compile verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass
```

Broad non-integration verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
377 passed, 2 warnings
```

Whitespace verification:

```text
git diff --check
pass
```
