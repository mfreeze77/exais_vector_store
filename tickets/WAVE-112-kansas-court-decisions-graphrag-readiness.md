# WAVE-112 Kansas Court Decisions GraphRAG Readiness

## Goal

Turn the WAVE-111 Kansas court decisions vector store into a GraphRAG-ready
legal corpus by extracting citation, authority, party, docket, court, date, and
case-relationship signals without replacing vector retrieval or committing to a
graph database before the data shape is proven.

## Background

The Kansas decisions corpus is a strong GraphRAG candidate because opinions
cite other opinions, statutes, rules, dockets, courts, dates, procedural posture,
and authority chains. WAVE-111 preserves the manifest metadata and original PDF
source identifiers needed to build that graph after the text-first vector store
pilot proves ingestion and search plumbing.

GraphRAG should be additive here:

- Vector search remains the default semantic recall layer.
- Graph signals should improve authority tracing, cited-by navigation,
  jurisdiction/status filtering, and related-case expansion.
- The first wave should produce auditable node/edge data and eval proof before
  standing up a graph service.

## Scope

- Build a citation/entity extraction prototype that reads WAVE-111 indexed
  Kansas decision text and metadata from the existing ExAIS store.
- Extract candidate nodes:
  `case`, `opinion`, `court`, `docket`, `party`, `statute`, `rule`,
  `publication_status`, and `year`.
- Extract candidate edges:
  `cites_case`, `cites_statute`, `same_docket`, `same_party`,
  `same_court`, `same_year`, `published_status`, and `source_document`.
- Normalize Kansas case citations and docket numbers with deterministic regex
  rules first; use an LLM fallback only for unresolved or ambiguous extraction
  spans.
- Preserve source provenance for every node and edge:
  vector store ID, document ID, vector store file ID, source PDF hash,
  filename, title, docket number, decision date, court, publication status,
  page marker when present, and text span when available.
- Write graph artifacts to a local export format first, such as JSONL or
  Parquet, plus an optional Postgres staging table if that better matches the
  existing ops model.
- Add pilot eval queries that compare vector-only retrieval against
  vector-plus-graph expansion for authority-trail questions, cited-by questions,
  same-docket questions, and related-case questions.
- Document the decision point for a later graph backend:
  Postgres tables, Neo4j, Memgraph, Kuzu, or another embedded graph option.

## Out Of Scope

- Replacing ExAIS vector retrieval.
- Standing up a production graph database.
- Building a public graph query API.
- Legal advice or legal validity guarantees.
- Full-corpus graph extraction before WAVE-111 has a real embedding provider
  and full ingestion proof.

## Acceptance Criteria

- [x] A prototype extractor can process a bounded WAVE-111 pilot sample without
  mutating source PDFs or vector-store text.
- [x] Extracted nodes and edges are written to a deterministic artifact with
  stable IDs and source provenance.
- [x] Citation extraction has unit tests for Kansas case citations, docket
  numbers, statutes, and ambiguous/no-citation text.
- [x] Every LLM-assisted extraction carries a confidence value and the original
  evidence span; deterministic regex results are labeled separately.
- [x] Pilot graph stats are reported: node counts by type, edge counts by type,
  unresolved citation count, duplicate/merged node count, and extraction error
  count.
- [x] Eval proof includes at least one authority-trail query, one cited-by
  query, one related-case query, and one filter-bound query.
- [x] The ticket ends with a backend recommendation and a no-go option if the
  graph signal is not worth production complexity.

## Verification

Proof commands:

```powershell
$img = docker inspect exais-vector-store-ks-state-civics-api-1 --format '{{.Config.Image}}'
docker run --rm -v "${PWD}:/work" -w /work $img sh -lc 'PYTHONPATH=packages/svs_common:apps/api:apps/worker:apps/model_gateway:apps/instance_agent python -m pytest -q tests/test_kscourts_graphrag_extraction.py'
docker run --rm -v "${PWD}:/work" -w /work $img sh -lc 'PYTHONPATH=packages/svs_common:apps/api:apps/worker:apps/model_gateway:apps/instance_agent python -m py_compile packages/svs_common/svs_common/kscourts_graphrag.py scripts/release/kscourts-graphrag-extract.py scripts/release/kscourts-graphrag-eval.py'
docker run --rm --network exais-vector-store-ks-state-civics_default -v "${PWD}:/work" -w /work $img python scripts/release/kscourts-graphrag-extract.py --vector-store-id vs_a0d3ac76893e4f6f83bf2992 --tenant-id ten_ks_state_civics --business-instance-id biz_ks_state_civics --document-limit 50 --max-chunks-per-document 8 --include-docket 116515 --output-dir /work/.release/cells/ks-state-civics/graphrag/ks-civics-graphrag-pilot-2026-08-08
docker run --rm -v "${PWD}:/work" -w /work $img python scripts/release/kscourts-graphrag-eval.py --graph-artifact /work/.release/cells/ks-state-civics/graphrag/ks-civics-graphrag-pilot-2026-08-08 --output /work/.release/cells/ks-state-civics/graphrag/ks-civics-graphrag-pilot-2026-08-08/eval.json
```

Observed proof:

- Tests: `7 passed in 0.39s`.
- Artifact path:
  `.release/cells/ks-state-civics/graphrag/ks-civics-graphrag-pilot-2026-08-08`.
- Pilot sample: 52 documents, 298 chunks, 1,188 nodes, 2,569 edges.
- Node counts:
  `case=338`, `citation=322`, `court=2`, `docket=85`, `opinion=52`,
  `party=65`, `publication_status=2`, `rule=15`, `statute=286`, `year=21`.
- Edge counts:
  `cites_case=404`, `cites_rule=30`, `cites_statute=735`,
  `has_citation=404`, `has_docket=52`, `mentions_docket=106`,
  `published_status=52`, `related_party=530`, `same_court=52`,
  `same_docket=1`, `same_party=99`, `same_year=52`,
  `source_document=52`.
- Quality counters:
  `unresolved_citation_count=0`, `duplicate_merged_node_count=903`,
  `duplicate_merged_edge_count=1`, `extraction_error_count=0`.
- Eval proof passed:
  authority trail `State v. Chastain -> State v. Witte`,
  cited-by inverse for `State v. Witte`, same-docket related case for
  docket `116515`, and filter-bound court/year/publication-status edges.
- No LLM-assisted extraction was used in this slice; all emitted extraction
  provenance is deterministic `regex` or `metadata` with confidence and source
  evidence when a text span exists.

## Notes

- This is a readiness wave, not a graph platform wave.
- Start with source-grounded extraction and evals. Pick a graph backend only
  after the artifact proves useful relationships that vector retrieval alone
  does not expose well.
- Backend recommendation after the pilot: keep the next step Postgres-first
  with JSONL staging. Do not add Neo4j/Memgraph/Kuzu yet. The no-go option is
  to leave this as an offline audit/export artifact if retrieval-integrated
  graph expansion does not improve legal answer quality.
