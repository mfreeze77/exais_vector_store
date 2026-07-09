# WAVE-034 Model-Gateway Reranker Adapter

## Summary

Advance `SVS-044` by allowing retrieval profiles to rerank through the internal
model-gateway rerank contract instead of only the in-process lexical fallback.
This gives production cells a stable adapter boundary for hosted or local
cross-encoder rerankers without requiring provider credentials in the API
process.

## Background

W21 added profile-driven reranking with a deterministic local fallback. The
model gateway already exposes `/internal/models/rerank`, but the retrieval
service cannot call it; any non-local reranker currently fails as unsupported.
For state-of-the-art retrieval, reranker provider deployment should sit behind
the model gateway while the API service preserves ACL hydration, citation shape,
and audit truth.

## Scope

- Add a retrieval-profile reranker ID for model-gateway reranking.
- Call `settings.model_gateway_url/internal/models/rerank` with query,
  candidate documents, model profile ID, and top-N.
- Combine returned relevance scores with fused scores using the existing
  rerank/fusion weighting logic.
- Preserve local lexical fallback behavior and unsupported-reranker fail-closed
  behavior.
- Record gateway model/provider details in rerank audit/citation metadata.
- Update `SVS-044` tracker status with proof.

## Code Anchors

- `packages/svs_common/svs_common/retrieval.py`
- `configs/retrieval-profiles.yaml`
- `tests/test_retrieval_profile_resolution.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`

## Out Of Scope

- Direct provider-specific reranker APIs in the API process.
- New API keys or secret handling.
- Model-gateway production provider routing beyond the existing contract.
- Streaming Responses behavior.
- Database migrations.

## Acceptance Criteria

- [x] Existing local reranker tests still pass.
- [x] A model-gateway reranker profile can reorder candidates from returned
  relevance scores.
- [x] The model-gateway request uses the configured URL, model profile ID, and
  top-N.
- [x] Unsupported reranker IDs still fail closed.
- [x] Rerank audit/citation metadata records the gateway reranker, provider,
  and model.
- [x] Broad non-integration verification passes.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_retrieval_profile_resolution.py
26 passed in 1.23s

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
<exit 0>

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
185 passed, 2 warnings in 4.29s

git diff --check
<exit 0>
```

## Notes

The model gateway can keep using its local fallback in development. Production
provider-specific reranking can be added behind the gateway without changing the
retrieval API contract introduced here.
