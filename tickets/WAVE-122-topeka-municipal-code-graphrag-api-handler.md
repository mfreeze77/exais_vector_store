# WAVE-122 Topeka Municipal Code GraphRAG API Handler

## Summary

Wire the Topeka municipal-code graph artifact into the ExAIS API so source
packages can load graph nodes/edges through a supported route and caller agents
can request Topeka-specific graph lenses through direct vector-store search.

## Background

WAVE-118 completed the Topeka codified-code and ordinance PDF corpus in the
local KS Civics cell, but graph load/search was intentionally blocked because no
municipal-code graph API handler existed. Direct Postgres writes are not allowed
for Topeka source packages. WAVE-120 added the generic search-lens contract and
left Topeka handlers out of scope.

## Scope

- Add an OpenAI-compatible graph-load route:
  `POST /v1/vector_stores/{vector_store_id}/graph`.
- Accept Topeka graph artifacts with `nodes`, `edges`, `replace`, and `dry_run`.
- Normalize artifact `properties`/`attributes` into existing `graph_nodes` and
  `graph_edges` rows under the request principal's tenant/business instance.
- Reject dangling graph edges before any write.
- Expose Topeka municipal-code graph lenses as available when
  `SVS_TOPEKA_GRAPHRAG_ENABLED=true` and the store has graph coverage.
- Route explicit Topeka lens search through the municipal-code graph handler.
- Support hierarchy, reference, definition, and ordinance-history graph
  expansion without changing default semantic search behavior.
- Preserve result-level public citation URLs and graph metadata URLs for caller
  rendering.

## Out Of Scope

- Public `https://topks.statecivics.ai/local` deployment or DNS wiring.
- Direct writes from source packages to Postgres, Qdrant, MinIO, or OpenSearch.
- Re-scraping, re-vectorizing, or changing the Topeka source artifacts.
- Adding a separate graph database.
- Making a complete external legal citator claim.

## Acceptance Criteria

- [x] `POST /v1/vector_stores/{vector_store_id}/graph` has named OpenAPI request
  and response components.
- [x] Graph load uses existing principal scoping and requires
  `vector_stores:write`.
- [x] Dangling graph edges fail closed with `422`/validation error semantics.
- [x] `municipal_code_structure`, `municipal_code_cross_reference`, and
  `municipal_code_history` are available for Topeka stores when graph is
  enabled and loaded.
- [x] Explicit Topeka lenses force graph expansion and do not use the Kansas
  court-decision graph handler.
- [x] Structure searches walk `CONTAINS` descendants so chapter/article
  container nodes hydrate real section chunks.
- [x] Graph-expanded citations expose result-level `citation.url` plus
  `citation.graph_expansion` relation metadata.
- [x] Existing callers that omit `lens` keep semantic search behavior.
- [x] Local Docker cell is rebuilt/restarted on the final API digest and live
  graph load/search proof passes.

## Implementation Proof

Completed on 2026-08-28.

Changed source:

- `apps/api/svs_api/main.py`
- `packages/svs_common/svs_common/schemas.py`
- `packages/svs_common/svs_common/search_lenses.py`
- `scripts/release/topeka-code-graphrag-load.py`
- `tests/test_openai_responses_routes.py`
- `tests/test_openapi_contract.py`
- `tests/test_topeka_graphrag.py`
- `docs/API.md`
- `docs/CALLER_AGENT_INTEGRATION.md`
- `docs/TOPEKA_MUNICIPAL_CODE_SEEDING_SPEC.md`
- `instances/ks-state-civics/vector-stores/topeka-municipal-code/README.md`
- `instances/ks-state-civics/vector-stores/topeka-municipal-code/store.yaml`
- `instances/ks-state-civics/vector-stores/topeka-municipal-code/sources/topeka-codified-code/source.yaml`
- `instances/ks-state-civics/vector-stores/topeka-municipal-code/sources/topeka-codified-code/source.lock.json`
- `instances/ks-state-civics/vector-stores/topeka-municipal-code/sources/topeka-ordinances/source.yaml`
- `instances/ks-state-civics/vector-stores/topeka-municipal-code/sources/topeka-ordinances/source.lock.json`
- `tickets/WAVE-118-topeka-municipal-code-source-seeding.md`
- `tickets/WAVE-120-graphrag-search-lenses.md`
- `tickets/WAVE-122-topeka-municipal-code-graphrag-api-handler.md`
- `tickets/README.md`

Verification:

- Host Python pytest was blocked because the workstation Python environment has
  no `pytest` module installed.
- Docker targeted tests:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q tests/test_openai_responses_routes.py -k "topeka or graph_load or search_lenses"`
  -> `9 passed, 43 deselected`.
- Docker OpenAPI and Topeka GraphRAG tests:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q tests/test_openapi_contract.py tests/test_topeka_graphrag.py`
  -> `34 passed`.
- Docker full test suite:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q`
  -> `674 passed, 5 skipped`.
- Generated OpenAPI count:
  `53` paths, `70` operations, `124` schema components.
- Image build/publish/cell restart completed; the current local API digest is
  `sha256:a0c1509efe4efdd2f134349aa7df89908f06f1ff1bba1df037340617177c1556`
  and is recorded in the instance source descriptors.
- Local graph load proof:
  `POST http://api:8080/v1/vector_stores/vs_d4185d1004604f08a55299fa/graph`
  returned HTTP `200`, `loaded_nodes=4969`, `loaded_edges=10167`, and
  `dangling_edges=0`.
- Local caller-style search proof through
  `/v1/vector_stores/vs_d4185d1004604f08a55299fa/search`:
  `municipal_code_structure` returned `applied=true`,
  `inserted_chunk_count=6`, `annotated_result_count=6`, with sample public URL
  `https://topeka.municipal.codes/TMC/14.40.055`;
  `municipal_code_history` returned `applied=true`,
  `inserted_chunk_count=6`, `annotated_result_count=9`, with sample public URL
  `https://files.topeka.gov/community/ordinances/2022/Ordinance20340.pdf`;
  `municipal_code_cross_reference` returned `applied=true`,
  `inserted_chunk_count=6`, `annotated_result_count=9`, with sample public URL
  `https://topeka.municipal.codes/TMC/1.10.020`.

## Remaining Gates

- VPS deployment must repeat health, graph-load, search-lens discovery, and
  three explicit Topeka graph-lens searches over the production HTTPS route.
- Windows host `127.0.0.1:28080` still refused connections from this machine
  even while Docker reported the port mapping and the Compose-network API route
  was healthy. Treat that as a local Docker Desktop host-port issue, not as VPS
  proof.
- `https://topks.statecivics.ai/local` is still an intended consumer route; it
  has not been wired or DNS-verified from this machine.
