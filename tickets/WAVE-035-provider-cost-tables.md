# WAVE-035 Provider Cost Tables

## Summary

Implement `SVS-045` by adding provider/model cost metadata to the shared model
registry and consuming it in cost estimation and vectorization planning. This
lets ExAIS compare model candidates with quality, privacy, configuration, and
estimated cost signals instead of returning placeholder cost data.

## Background

The intelligent vectorization router spec calls for cost/latency policy as part
of model selection. The model gateway currently exposes
`/internal/models/estimate-cost`, but it returns `estimated_cost_usd: null`.
The ingestion preview returns candidates and token/chunk estimates, but no cost
hints.

## Scope

- Add narrow cost metadata for configured embedding profiles in
  `configs/model-registry.yaml`.
- Add shared helpers that resolve embedding profiles and estimate cost from
  token counts.
- Wire `/internal/models/estimate-cost` to return a deterministic estimate for
  known profiles and a clear unavailable reason for unknown/unpriced profiles.
- Add candidate cost hints to ingestion preview candidates without changing
  provider selection, credential handling, or security policy.
- Update `SVS-045` tracker status with proof.

## Code Anchors

- `configs/model-registry.yaml`
- `packages/svs_common/svs_common/model_registry.py`
- `packages/svs_common/svs_common/vectorization_router.py`
- `packages/svs_common/svs_common/schemas.py`
- `apps/model_gateway/svs_model_gateway/main.py`
- `tests/test_vectorization_plan.py`

## Out Of Scope

- Fetching live provider pricing.
- Billing ledger writes.
- Provider-specific request metering changes.
- UI cost display.
- Changing candidate ordering or security/provider allowance rules.

## Acceptance Criteria

- [x] Known embedding profiles expose normalized per-1M-token cost metadata.
- [x] The model-gateway estimate-cost route returns token count, model profile,
  provider/model, cost estimate, and currency for priced profiles.
- [x] Unknown or unpriced profiles return `estimated_cost_usd: null` with a
  reason instead of guessing.
- [x] Ingestion plan candidates include estimated cost hints while preserving
  existing allowed/score ordering.
- [x] Focused tests cover priced, unpriced, unknown, and plan-candidate cost
  behavior.
- [x] Broad non-integration verification passes.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_vectorization_plan.py
13 passed in 1.26s

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
191 passed, 2 warnings in 4.44s

git diff --check
pass
```

## Notes

Cost values are static registry hints, not live billing claims. They are used
for planning and comparison only.
