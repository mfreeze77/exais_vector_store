# WAVE-120 GraphRAG Search Lenses

## Summary

Make GraphRAG capability explicit per vector store by adding discoverable search
lenses and allowing callers to request a lens with structured inputs on the
OpenAI-compatible vector-store search route.

## Background

WAVE-115 proved additive GraphRAG expansion for the Kansas court-decision store,
but the caller-facing caveat is still too informal: graph search works only for
the graph artifact currently loaded, and each legal corpus has different useful
relationships. Caller agents need a precise per-store contract that says which
lenses exist, which inputs they accept, whether the graph lens is available,
and what graph coverage backs the answer.

## Scope

- Add a typed search-lens registry for corpus-specific semantic and GraphRAG
  modes.
- Add `GET /v1/vector_stores/{vector_store_id}/search_lenses`.
- Allow `POST /v1/vector_stores/{vector_store_id}/search` to accept optional
  `lens` and `inputs` fields.
- Make explicit Kansas court lenses force GraphRAG expansion even when the raw
  query text does not contain graph-intent keywords.
- Add coverage and warning metadata to graph expansion summaries so callers do
  not confuse a loaded graph artifact with a complete legal citator.
- Preserve default search behavior when callers omit `lens`.
- Extend the Responses file-search facade to pass through lens metadata when a
  caller intentionally supplies it on the tool object.

## Out Of Scope

- Building a complete Kansas legal citator.
- Adding a graph database.
- Loading new graph artifacts.
- Implementing Topeka municipal-code graph search handlers.
- Changing API-key scope, tenant isolation, ingestion, vectorization, or
  deployment behavior.

## Deliverables

- Shared search-lens registry.
- Pydantic request/response contract updates.
- API discovery route and lens-aware search integration.
- Caller documentation update.
- Focused tests for discovery, explicit lens behavior, invalid lens handling,
  and OpenAPI shape.

## Acceptance Criteria

- [x] The search-lenses endpoint returns at least the default semantic lens for
  every vector store.
- [x] Kansas court-decision stores expose available court GraphRAG lenses when
  `SVS_KSCOURTS_GRAPHRAG_ENABLED=true`.
- [x] Explicit `lens="court_citator"` applies GraphRAG expansion without relying
  on graph-intent words in the query string.
- [x] Unsupported, disabled, empty, or planned graph lenses fail closed instead
  of silently returning plain semantic results as if graph search ran.
- [x] Graph expansion summaries include lens ID, coverage counts, relation
  types, and warnings when coverage is not a proven full-corpus citator.
- [x] Existing callers that omit `lens` keep existing search behavior.
- [x] Focused tests and OpenAPI contract checks pass.

## Verification

```powershell
python -m pytest -q tests\test_openai_compat_search.py tests\test_openai_responses_routes.py tests\test_openapi_contract.py
python -m py_compile packages\svs_common\svs_common\search_lenses.py apps\api\svs_api\main.py packages\svs_common\svs_common\schemas.py packages\svs_common\svs_common\openai_compat.py
```

## Notes

GraphRAG lenses are a caller contract, not a promise that every legal
relationship exists in the loaded graph. Each lens must report coverage so a
caller can distinguish strong graph-backed relationship evidence from ordinary
semantic retrieval.

## Implementation Proof

Completed on 2026-08-28.

Changed source:

- `packages/svs_common/svs_common/search_lenses.py`
- `packages/svs_common/svs_common/schemas.py`
- `packages/svs_common/svs_common/openai_compat.py`
- `apps/api/svs_api/main.py`
- `tests/test_openai_compat_search.py`
- `tests/test_openai_responses_routes.py`
- `tests/test_openapi_contract.py`
- `docs/API.md`
- `docs/CALLER_AGENT_INTEGRATION.md`
- `tickets/README.md`
- `tickets/WAVE-120-graphrag-search-lenses.md`

Verification:

- Host Python proof was blocked because this workstation's default Python
  environment does not have `pytest` installed:
  `C:\Users\mfrie\AppData\Local\Programs\Python\Python311\python.exe: No module named pytest`.
- Docker API-image focused tests:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q tests/test_openai_compat_search.py tests/test_openai_responses_routes.py tests/test_openapi_contract.py`
  -> `153 passed, 2 existing FastAPI deprecation warnings`.
- Docker API-image compile proof:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m py_compile packages/svs_common/svs_common/search_lenses.py apps/api/svs_api/main.py packages/svs_common/svs_common/schemas.py packages/svs_common/svs_common/openai_compat.py`
  -> passed.

Known limitations:

- Superseding local runtime proof on 2026-08-28: the running
  `exais-vector-store-ks-state-civics` API container was rebuilt/restarted in
  the local cell and `GET /v1/vector_stores/vs_d4185d1004604f08a55299fa/search_lenses`
  returned HTTP `200`.
- WAVE-120 originally left Topeka municipal-code graph handlers out of scope.
  WAVE-122 supersedes that limitation for the local KS Civics cell by loading
  the Topeka graph through the ExAIS graph API and verifying the structure,
  cross-reference, and ordinance-history lenses through
  `/v1/vector_stores/{vector_store_id}/search`.
