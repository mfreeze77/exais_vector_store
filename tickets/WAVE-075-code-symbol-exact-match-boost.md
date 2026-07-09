# WAVE-075 Code Symbol Exact Match Boost

## Summary

Implement profile-driven exact symbol boosting in retrieval so code-oriented
profiles can promote chunks that contain identifier, path, or config-key terms
from the query after dense+sparse fusion and before final result selection.

## Background

`configs/retrieval-profiles.yaml` already declares
`hybrid_code_symbol_rrf_v2` with `exact_symbol_boost: 2.0`, but the retrieval
pipeline does not currently consume that profile field. That leaves code and
configuration searches dependent on dense/sparse RRF alone, even when a query
contains exact symbols such as function names, route paths, environment
variables, or config keys.

## Scope

- Add a profile-driven exact symbol boost stage for `RetrievalService.search`.
- Extract symbol-like query terms conservatively without changing generic
  retrieval behavior.
- Apply boosts only when the effective retrieval profile declares a positive
  `exact_symbol_boost`.
- Annotate boosted chunk citation metadata and audit metadata.
- Add focused tests for boost ordering, disabled behavior, and audit/citation
  metadata.
- Update docs, ticket trail, ticket index, and proof.

## Out Of Scope

- Changing dense or sparse indexing semantics.
- Changing tenant isolation, API keys, RLS, database schema, provider routing,
  deployment, admin UI, or OpenAI route request/response contracts.
- Adding a learned reranker or external model dependency.
- Changing behavior for profiles that do not opt into exact symbol boosting.

## Code Anchors

- `packages/svs_common/svs_common/retrieval.py`
- `configs/retrieval-profiles.yaml`
- `tests/test_retrieval_profile_resolution.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`
- `tickets/README.md`

## Acceptance Criteria

- [x] Code-oriented retrieval profiles with positive `exact_symbol_boost`
  promote chunks containing exact symbol-like query terms before final `top_k`.
- [x] Profiles without `exact_symbol_boost` or with zero/negative boost preserve
  existing ordering.
- [x] Boosted chunks include audit-visible score, matched symbols, and boost
  multiplier metadata without changing the strict OpenAI citation annotation
  shape.
- [x] Retrieval audit metadata records whether exact symbol boosting ran.
- [x] Focused retrieval tests pass.
- [x] Compile, broad non-integration, and whitespace verification pass.

## Verification

- `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_retrieval_profile_resolution.py tests/test_openai_compat_search.py`
  - Result: 119 passed.
- `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests`
  - Result: pass.
- `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration`
  - Result: 364 passed, 2 warnings.
- `git diff --check`
  - Result: pass.
