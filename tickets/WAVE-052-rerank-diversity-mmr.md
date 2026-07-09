# WAVE-052 Rerank Diversity MMR

## Summary

Add a profile-controlled MMR-style diversity pass after post-fusion reranking so
final retrieval results are not dominated by near-duplicate chunks with the same
wording. The pass should keep relevance primary, but prefer additional chunks
that add distinct evidence when relevance scores are close.

## Background

WAVE-021 added dense+sparse RRF plus profile-driven reranking. That improves
ordering, but it can still return several highly similar chunks from the same
section when top candidates share nearly identical text. State-of-the-art RAG
systems commonly add a diversity selection step after relevance ranking to
increase evidence coverage within the final context budget.

This ticket adds a deterministic lexical MMR pass that does not require new
indexes, provider calls, migrations, API-key changes, or tenant/RLS changes.

## Scope

- Add profile fields for post-rerank diversity selection.
- Implement an MMR-style selector over reranked candidates using lexical token
  overlap as the similarity signal.
- Apply the selector only to the final `top_k` candidate window; keep unselected
  candidates and remainder available after the selected results.
- Preserve rerank scores, strict OpenAI citation annotation shape, and existing
  post-ACL behavior.
- Add diversity metadata to native citations and retrieval audit metadata.
- Enable deterministic diversity on the default secure profile.
- Update focused tests, docs, ticket trail, and proof.

## Code Anchors

- `packages/svs_common/svs_common/retrieval.py`
- `configs/retrieval-profiles.yaml`
- `tests/test_retrieval_profile_resolution.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`

## Out Of Scope

- Changing dense or sparse indexing semantics.
- Changing Qdrant/OpenSearch adapters.
- Adding provider-specific reranker calls or model-gateway contract changes.
- Changing tenant isolation, API-key behavior, database migrations, or
  deployment behavior.
- Changing Responses citation formatting or streaming.

## Acceptance Criteria

- [x] Default secure retrieval profile declares deterministic MMR diversity
  settings.
- [x] MMR diversity keeps the highest-relevance candidate first.
- [x] MMR diversity can promote a distinct lower-relevance chunk over a
  near-duplicate when profile settings call for it.
- [x] Diversity metadata appears in retrieval audit and native citation metadata
  without changing strict OpenAI annotation fields.
- [x] Disabled diversity preserves the existing reranked order and audit shape.
- [x] Focused and broad non-integration verification passes.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_retrieval_profile_resolution.py
36 passed

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_openai_responses_routes.py tests/test_openai_vector_store_object.py
84 passed, 2 warnings

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
252 passed, 2 warnings

git diff --check
pass
```
