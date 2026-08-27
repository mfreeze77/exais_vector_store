# KS State Civics Graph Citation Backlinks

Generated against the existing Docker cell `exais-vector-store-ks-state-civics` on 2026-08-13.

- API/container stack used as-is; no rebuild or recreate.
- Graph tables used: `graph_nodes`, `graph_edges`
- Citation edge used: `edge_type = 'cites_case'`
- Direction: `opinion -> case`, meaning the source opinion cites the target case node.
- Current loaded graph size: 52 opinion nodes, 338 case nodes, 404 `cites_case` edges.

Important boundary:

> These are all inbound citing cases currently present in the loaded graph, not all Kansas cases in the full 16,728-PDF corpus. Several demo search results are in the vector store but do not yet have exact case nodes in the loaded graph.

## Backlinks Found

### Cited Case: `Gannon v. State`

The graph found one distinct citing opinion:

1. `Black Jack Hills, Inc. v. Webster`
   - Docket: `127767`
   - Court: Court of Appeals
   - Decision date: `2025-07-18`
   - Status: Unpublished
   - Source PDF: `https://searchdro.kscourts.gov/documents/pdf/caseDecisions/8cc75198-41d8-4340-99a0-3127d12fee5b_127767.pdf`
   - Graph evidence:
     - `Gannon v. State, 298 Kan. 1107, 1175, 319 P.3d 1196 (2014)`
     - `Gannon v. State, 305 Kan. 850, 881, 390 P.3d 461 (2017)`
   - Evidence chunks:
     - `chk_a381048bdc3d4c0d883abc8d`
     - `chk_859945a341704d64805cbc8e`

### Cited Case: `State v. Harris`

The graph found one distinct citing opinion:

1. `State v. Robinson`
   - Docket: `122559`
   - Court: Court of Appeals
   - Decision date: `2021-12-17`
   - Status: Unpublished
   - Source PDF: `https://searchdro.kscourts.gov/documents/pdf/caseDecisions/e80180b7-e1b1-42a8-bb36-ac1eb7c22910_122559.pdf`
   - Graph evidence:
     - `State v. Harris, 311 Kan. 816, 821, 467 P.3d 504 (2020)`
   - Evidence chunk:
     - `chk_41c48e7f09654ef9aace2392`

## Demo Cases Not Present As Exact Graph Targets

The following demo cases from `KS_STATE_CIVICS_LIVE_DEMO_OUTPUT.md` did not have exact `case` nodes in the currently loaded graph:

- `Denney v. State`
- `Elliott v. State`
- `Conley v. State`
- `Seck v. City of Overland Park`
- `Wichita Eagle & Beacon Publishing Co. v. Simmons, Secretary of Corrections`
- `Hunter Health Clinic v. Wichita State University`
- `In re P.B.`
- `In re C.H.`
- `In re L.B.`

That does not mean no Kansas decision cites them. It means the currently loaded GraphRAG artifact cannot prove those backlinks yet.

## SQL Shape Used

```sql
SELECT
  target.label AS cited_case,
  src.label AS citing_case,
  src.attributes->>'docket_number' AS citing_docket,
  src.attributes->>'court' AS citing_court,
  src.attributes->>'decision_date' AS citing_decision_date,
  e.attributes AS cited_reporter_metadata,
  e.provenance->>'chunk_id' AS evidence_chunk_id,
  e.provenance->>'evidence' AS evidence
FROM graph_edges e
JOIN graph_nodes target
  ON target.id = e.target_node_id
JOIN graph_nodes src
  ON src.id = e.source_node_id
WHERE e.edge_type = 'cites_case'
  AND target.node_type = 'case'
  AND target.node_key IN ('gannon v state', 'state v harris');
```

