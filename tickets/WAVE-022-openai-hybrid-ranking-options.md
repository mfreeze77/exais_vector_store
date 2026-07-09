# WAVE-022 OpenAI Hybrid Ranking Options

## Summary

Support OpenAI-compatible `ranking_options.hybrid_search` weights on vector-store
search so callers can tune how ExAIS reciprocal rank fusion balances semantic
dense retrieval against sparse keyword retrieval.

Official OpenAI reference checked on 2026-07-08:

- Retrieval guide ranking section: `ranking_options.hybrid_search.embedding_weight`
  and `ranking_options.hybrid_search.text_weight` control RRF weighting, and at
  least one weight must be greater than zero.

## Tickets

| Ticket | Status | Type | Outcome |
|---|---|---|---|
| W22-001 | Complete | Implementation/Test | Accept OpenAI hybrid search ranking weights and apply them to ExAIS dense/sparse RRF. |

## Code Anchors

- `packages/svs_common/svs_common/schemas.py`
- `packages/svs_common/svs_common/openai_compat.py`
- `packages/svs_common/svs_common/retrieval.py`
- `tests/test_openai_compat_search.py`
- `tests/test_retrieval_profile_resolution.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`

## W22-001 Acceptance Criteria

- [x] `OpenAIVectorStoreSearchRequest` accepts
  `ranking_options.hybrid_search.embedding_weight` and `text_weight`.
- [x] Compatibility aliases `rrf_embedding_weight` and `rrf_text_weight` are
  accepted and normalized into the same internal metadata.
- [x] Hybrid search weights reject negative values and reject an object where
  both configured weights are zero or omitted.
- [x] OpenAI search mapping stores normalized hybrid weight metadata for audit
  and passes dense/sparse RRF overrides into retrieval.
- [x] `RetrievalService.search` uses OpenAI hybrid weight overrides for
  dense/sparse RRF when present, while preserving profile defaults otherwise.
- [x] Focused tests prove schema acceptance/rejection, metadata mapping, and
  retrieval fusion-weight override behavior.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_retrieval_profile_resolution.py
38 passed in 1.34s

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests scripts
<exit 0>

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_files.py tests/test_openai_vector_store_object.py tests/test_openai_compat_search.py tests/test_openai_file_search_parity_eval.py
37 passed, 2 warnings in 3.53s

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
129 passed, 2 warnings in 4.59s

git diff --check
<exit 0>
```

Live API proof against `exais-vector-store-local_default` used a temporary
dev-header-created Bearer key, then exercised `/v1/files`, `/v1/vector_stores`,
`/v1/vector_stores/{id}/search`, audit-row inspection, and file cleanup without
printing the key:

```text
{'api_key_prefix': 'svs_live_', 'vector_store_id': 'vs_07f20a27b33740a7b4c10728', 'file_id': 'file_e99d61dd620248a5842052ba', 'result_count': 1, 'hybrid_search': {'text_weight': 0.2, 'embedding_weight': 0.8}, 'fusion': {'source': 'openai_ranking_options.hybrid_search', 'dense_weight': 0.8, 'sparse_weight': 0.2}, 'file_cleanup': {'id': 'file_e99d61dd620248a5842052ba', 'object': 'file', 'deleted': True}}
```

## Notes

This ticket does not add provider credentials, external reranker calls,
database migrations, API-key changes, or changes to tenant/RLS boundaries.
