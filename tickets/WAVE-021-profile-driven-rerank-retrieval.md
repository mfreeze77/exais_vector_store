# WAVE-021 Profile-Driven Rerank Retrieval

## Summary

Add a post-fusion rerank stage to the retrieval pipeline so ExAIS can improve
final chunk ordering after dense+sparse reciprocal rank fusion while preserving
tenant ACL filtering and citation proof.

Official OpenAI reference checked on 2026-07-08:

- Retrieval guide ranking section: file search quality can be tuned with
  `ranking_options`, `ranker`, `score_threshold`, and hybrid RRF weights.

## Tickets

| Ticket | Status | Type | Outcome |
|---|---|---|---|
| W21-001 | Complete | Implementation/Test | Add profile-driven post-fusion reranking with deterministic local fallback and audit proof metadata. |

## Code Anchors

- `packages/svs_common/svs_common/retrieval.py`
- `configs/retrieval-profiles.yaml`
- `tests/test_retrieval_profile_resolution.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`

## W21-001 Acceptance Criteria

- [x] `RetrievalService.search` hydrates and ACL-filters candidate chunks before
  reranking, then reranks before applying final `top_k`.
- [x] Reranking is controlled by retrieval profile fields and can be disabled
  per profile with behavior-preserving original order.
- [x] The default `hybrid_rrf_secure_v2` profile enables a deterministic local
  reranker without requiring external provider credentials.
- [x] Reranked chunks expose updated scores/source and citation score metadata
  while preserving OpenAI-core annotation shape.
- [x] Retrieval audit metadata records whether rerank ran, the reranker ID, and
  candidate/result counts.
- [x] Focused tests prove reranking can promote a more query-relevant chunk,
  disabled profiles preserve order, and the default profile declares reranking.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_retrieval_profile_resolution.py
10 passed in 1.04s

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_openai_file_search_parity_eval.py
24 passed in 0.66s

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests scripts
<exit 0>

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
122 passed, 2 warnings in 3.94s

git diff --check
<exit 0>
```

Live API proof against `exais-vector-store-local_default` used a temporary
dev-header-created Bearer key, then exercised `/v1/files`, `/v1/vector_stores`,
`/api/v1/retrieval/search`, audit-row inspection, and file cleanup without
printing the key:

```text
{'api_key_prefix': 'svs_live_', 'vector_store_id': 'vs_7fc4bd9ed88847b394536d11', 'file_ids': ['file_ea865b53d07e4aee9403a521', 'file_87cbf1c133b146d8830c7f9f'], 'audit_event_id': 'aud_9c4f9f61a7fa458086842211', 'top_result_id': 'chk_71974876279e47c3bdc3535f', 'top_result_source': 'hybrid_rrf_rerank', 'top_result_score': 1.0, 'rerank': {'enabled': True, 'reranker': 'local_lexical_overlap_v1', 'result_count': 2, 'fusion_weight': 0.35, 'rerank_weight': 0.65, 'candidate_count': 3}}
```

## Notes

This ticket does not add external reranker provider calls, new API keys,
database migrations, or streaming Responses behavior.
