# WAVE-115 Kansas Civics GraphRAG Search Expansion

## Goal

Make the WAVE-112 Kansas court-decision graph artifact useful inside the
`ks-state-civics` search path by loading it into tenant-scoped Postgres staging
tables and adding opt-in graph expansion metadata/results for the Kansas legal
planner profile.

## Background

WAVE-112 proved deterministic graph extraction can produce source-grounded
nodes and edges without standing up a graph database. The next step is not a
new graph platform. The next step is to let the existing OpenAI-compatible
vector-store search route use the graph as an additive expansion layer when a
customer cell explicitly enables it.

## Scope

- Add Postgres staging tables for graph nodes and edges with tenant/business
  RLS and vector-store scoping.
- Add an idempotent loader that imports WAVE-112 `nodes.jsonl` and
  `edges.jsonl` artifacts into those tables.
- Add a profile-scoped, opt-in graph expansion path for
  `ks_civics_legal_v1`.
- Keep default/global search behavior unchanged when GraphRAG is not enabled.
- Expand from vector hits to graph-related Kansas opinions for same-docket,
  related-party, cited-by, and cited-authority signals.
- Preserve original vector scores and citation payload shape; graph additions
  must be explicitly labeled in citation metadata.
- Add focused tests for disabled behavior, opt-in behavior, and tenant-scoped
  graph loading.
- Run bounded live proof against the Kansas cell.

## Out Of Scope

- Neo4j, Memgraph, Kuzu, or another graph database.
- Replacing vector search or reranking.
- Public graph query APIs.
- Full GraphRAG answer generation.
- Legal advice or legal correctness guarantees.

## Acceptance Criteria

- [x] New graph staging tables are RLS-scoped by tenant and business instance.
- [x] The loader can import the WAVE-112 artifact idempotently.
- [x] OpenAI vector-store search behavior is unchanged when GraphRAG is not
  enabled.
- [x] With `SVS_KSCOURTS_GRAPHRAG_ENABLED=true` and
  `SVS_QUERY_PLANNER_PROFILE_ID=ks_civics_legal_v1`, graph expansion adds or
  annotates related results without replacing vector hits.
- [x] Graph-expanded chunks include citation metadata that identifies graph
  relation type, source document, edge ID, and extraction provenance.
- [x] Focused tests pass.
- [x] Live Kansas proof shows graph tables loaded and at least one
  graph-expanded search result for a known relationship.

## Verification

Expected focused proof:

```powershell
python -m pytest -q tests\test_kscourts_graphrag_extraction.py tests\test_openai_responses_routes.py
python -m py_compile packages\svs_common\svs_common\kscourts_graphrag.py scripts\release\kscourts-graphrag-load.py
```

Expected live proof:

```powershell
python scripts\release\kscourts-graphrag-load.py --graph-artifact <path> --vector-store-id <vs_id>
curl -s -X POST http://localhost:28080/v1/vector_stores/<vs_id>/search ...
```

Observed proof 2026-08-08:

- API image rebuilt and pushed to local registry:
  `localhost:5000/expertaiservices/exai-vector-store-api@sha256:197f120123d5a5738825730e5d0f0b85042f5a9ad298014401ef7a31675289e2`.
- `ks-state-civics` API container recreated only; worker, admin UI, model
  gateway, and infra services were not rebuilt.
- API health from inside the recreated container:
  `{"ready":true,"db":true,"qdrant":true}`.
- GraphRAG feature flag active in the API container:
  `SVS_KSCOURTS_GRAPHRAG_ENABLED=true`.
- Migration state:
  `alembic_version=002_graphrag_staging`.
- Graph table RLS:
  `graph_nodes` and `graph_edges` have row security and force row security
  enabled, with `tenant_scope_graph_nodes` and `tenant_scope_graph_edges`
  policies.
- Runtime-role RLS proof with `svs_app`:
  correct tenant/business sees `1188` nodes and `2569` edges; wrong business
  context sees `0` graph nodes.
- Loader result from WAVE-112 artifact:
  `loaded_nodes=1188`, `loaded_edges=2569`, `nodes=1188`, `edges=2569`,
  `skipped_edges=0`, `replaced=true`.
- Focused tests:
  `51 passed, 2 existing FastAPI deprecation warnings`.
- Compile proof:
  `py_compile` passed for GraphRAG extraction, loader/eval scripts, API route,
  and migration.
- Live search proof saved at:
  `.release/cells/ks-state-civics/graphrag/ks-civics-graphrag-live-search-2026-08-08.json`.
- Live graph search:
  `related cases for State v. Harris docket 116515` returned
  `graph_expansion.enabled=true`, `applied=true`, `candidate_count=12`,
  `inserted_chunk_count=3`, `annotated_result_count=5`, and relation types
  `cited_authority`, `related_party`, and `same_docket`.
- Legal recall smoke after API recreate saved at:
  `.release/cells/ks-state-civics/evals/ks-civics-graphrag-smoke-recall-2026-08-08.json`.
  Result: `20/20` recall at `@1`, `@3`, and `@10`.
- Host `curl` to `127.0.0.1:28080` failed from this shell even though Docker
  reports `0.0.0.0:28080->8080/tcp` and container-internal API health is good.
  Treat host reachability as an operator follow-up before advertising a local
  browser/client URL.

## Notes

This remains GraphRAG as an additive retrieval aid. If the live proof does not
surface useful relationships, keep the graph tables as offline audit/export
data and do not add graph infrastructure.
