# WAVE-132 Fiscal law-and-money GraphRAG runtime

Status: reopened — owner requires real fiscal data to govern design and acceptance.
The prior synthetic/runtime QC remains historical mechanics proof and does not
establish product acceptance or answer quality.
Owner direction: implement ExAIS GraphRAG for **enacted provision → appropriation
→ agency/fund/account → supporting budget documents**, rather than stopping at
the design contract. Initial reference: SB 125 Supplemental State Aid.

## Corrected ownership and acceptance — 2026-09-10

The [unified StateCivics handoff](../docs/STATECIVICS_LAW_MONEY_ALIGNMENT.md)
supersedes the v1 assumptions below. This ticket remains the integrated parent;
its historical mechanics proof is retained and does not close product acceptance.

Follow-up tickets: [WAVE-133](WAVE-133-fiscal-canonical-projection-contract.md),
[WAVE-134](WAVE-134-fiscal-projection-ingestion-lifecycle.md),
[WAVE-135](WAVE-135-fiscal-hybrid-retrieval-and-typed-traversal.md), and
[WAVE-136](WAVE-136-fiscal-real-source-generalization-evaluation.md).
The owner has also unblocked [WAVE-137](WAVE-137-kansas-statute-document-ingestion.md),
the separate retained-statute document path. It reuses the existing document
export and does not wait on provision/attestation contracts to implement parsing
and ingestion; actual eligible custody/export records still gate a live run.
The gated [build contract](../.tranche/statecivics-semantic-graph/aligned/build-contract.json)
and [file/symbol index](../.tranche/statecivics-semantic-graph/aligned/stack.index.json)
provide shared owners and sequential edit order.

- KS-600 defines the missing provision reference, preserving identity separately
  from numbering, evidence location and effective time. KS-595 owns span
  infrastructure; KS-597 owns fiscal-field span population. ExAIS must not use a
  SourceSpan ID as the legal provision's canonical identity.
- Use existing typed derivation inputs/outputs and set hashes for action/fact
  lineage. KS-600 owns classification, snapshots and authority arithmetic;
  KS-601 owns reviewed account crosswalks. No duplicate canonical model, link
  field or vector-derived legal/account join belongs in ExAIS.
- KS-650 extends the existing KS-595 exporter with a second versioned record
  type, preserving document compatibility and lifecycle/removal semantics,
  reusing publication-record and intelligence-snapshot contracts. Replace the
  provisional ExAIS-only publisher envelope with consumption of that output.
- WAVE-133 supports structured CSV evidence and exact document spans without
  fake PDF/chunk bindings. WAVE-134 provides scoped ingestion and consistent
  publication/correction/withdrawal handling in graph and ordinary retrieval.
- WAVE-135 implements exact, lexical and semantic candidates with bounded typed
  paths; WAVE-136 measures real-answer quality and incremental graph value.
  Amounts come from canonical reviewed facts/derivations, never sums of chunks.
- KS-613 remains the existing school-finance slice. KS-651 supplies the sibling
  benchmark across bills, years and agencies, including a positive held-back
  case. Its labels must be independent of retrieval/extraction tuning. All-refusal
  runs, source inventories and synthetic fixtures cannot satisfy acceptance.
- The K.S.A. harvest is complete: the [retained-corpus audit](../instances/ks-state-civics/research/statute-harvest-handoff.md)
  verifies 31,079 files and corrects the proposed 400-byte exclusion. The raw
  manifest's 72,753 event occurrences include 20 repeated by duplicate document
  groups; 72,733 remain after that deduplication, all unresolved. No restart is
  needed, and statute completion does not supply the appropriation ledger or
  canonical export. Unresolved history references are source evidence, not
  published fiscal relationships. No runtime or activation change accompanies
  this inventory update.
- Close this ticket only after the follow-up proof, an eligible upstream export,
  correction/withdrawal and isolation evidence, and a concrete scoped operator
  handoff. Any activation remains an explicit operator action; no activation,
  implementation completion or new test result is implied by these doc edits.

## Historical v1 scope and proof requirements

The following records what the existing code and earlier tests attempted. Its
fixed node/edge shape, universal chunk binding, one-hop limit and publisher
envelope must be revisited by the correction tickets; they are not independent
acceptance criteria for the revised real-data design.

- Ground the design in the existing State Civics fiscal corpus and official
  SB125 sources. Record actual source/revision/account availability, run real
  retrieval questions, preserve the returned passages and citations, and fix
  mismatches demonstrated by those records. Real-source refusal/gap reporting
  is required where canonical spans, review or legal provenance are absent;
  do not fabricate published records to make a demonstration pass.
- Include the existing KanView structured corpus in that grounding. Implement
  a read-only, manifest/custody-verified account evidence audit in
  `scripts/release/kansas-fiscal-corpus-audit.py`, exercised against the real
  FY2011–FY2026 agency extracts. Preserve raw CSV record locations, year,
  observed quarters, and the unknown subunit; never mint canonical IDs or
  treat a candidate as a reviewed legal-account join. Document the resulting
  correction to the PDF-only graph evidence contract. Bulk CSVs, vendor and
  employee data, live store cleanup, publication, and activation are outside
  this corrective increment.

- Implement the six node types and five typed directed edges in the fiscal
  section of `docs/CELL_GRAPH_PROFILES.md`, strict IDs/attributes/FY/citations,
  bounded 1,000-node/2,000-edge artifacts, one export run, and explicit fixture
  rejection in runtime routes.
- Register a fiscal handler and explicit search lens with a graph run selector
  kept separate from ordinary file filters. Enforce exact Principal/store/
  corpus/profile/run binding and preserve semantic, Grant, court, Topeka behavior.
- Load through the existing scoped PostgreSQL graph loader after fiscal shape,
  document/chunk binding, generation immutability, and replacement checks.
- Expand one hop with source/current-file/chunk verification, caller filters,
  Principal group/role ACLs and authorized hydration. Preserve original chunk
  citations and bounded directed relationship metadata, including relationships
  between nodes citing the same chunk. Never sum chunks into fiscal totals.
- Provide an operator adapter/load/evaluation path, disabled fiscal profile
  example, and reproducible synthetic chain. Exact span/quote-to-chunk mapping
  is evidence from the authorized upstream publisher plus the adapter's checked
  source binding, not independent certification of canonical human review.
- Prove the complete five-relation chain plus stale/withdrawn/wrong-source,
  generation, scope, filter, ACL, malformed and fixture-only refusals using
  unit/API tests and an explicitly disposable real PostgreSQL database.
- Record exact test results and independent QC. No fabricated real source
  review and no live graph activation without the required reviewed artifact.

## Code and proof anchors

`packages/svs_common/svs_common/{grant_graph,cell_graph,search_lenses,schemas,retrieval}.py`,
`apps/api/svs_api/main.py` graph load/search and annotation seams,
`scripts/release/kansas-fiscal-document-ingest.py:_record_attributes`,
`tests/test_grant_cell_graph.py`, `tests/test_grant_graph_postgres.py`,
`tests/test_openai_responses_routes.py`, fiscal source package.

Existing `cell_graph_profile_for_store(principal, vector_store_id, attributes)`
and graph loader remain the shared owner. Runtime fiscal profile is a separate
single manifest selected through `SVS_CELL_GRAPH_PROFILE_PATH`.

## Bounded implementation ownership

The delegated implementation specialist owns only:

- new `packages/svs_common/svs_common/fiscal_graph.py`;
- new `tests/test_fiscal_graph.py` and `tests/fiscal_graph_test_support.py`.

Root owns API/registry integration, release adapter/tooling, PostgreSQL/API
integration proof, configuration, docs/ticket proof. These are parts of this one
ticket; no concurrent changes to the shared API or existing security modules.
Independent QC follows implementation, not concurrently.

### Shared interfaces for this ticket

The new module exposes constants `FISCAL_CORPUS_KIND`, `FISCAL_GRAPH_HANDLER_ID`,
`FISCAL_PROFILE_ID`, `FISCAL_SCHEMA_VERSION`, `FISCAL_RELATIONS`,
`FISCAL_NODE_TYPES`, `MAX_GRAPH_NODES`, `MAX_GRAPH_EDGES` and:

```python
fiscal_node_id(vector_store_id: str, node_type: str, attributes: dict) -> str
fiscal_edge_id(vector_store_id: str, edge_type: str, source: str, target: str, attributes: dict) -> str
validate_fiscal_graph(req: VectorStoreGraphLoadRequest, vector_store_id: str, *, allow_fixture: bool = False) -> dict
fiscal_search_run_id(inputs: dict | None, store_attributes: dict) -> str
validate_fiscal_graph_bindings(db, principal: Principal, vector_store_id: str, req: VectorStoreGraphLoadRequest, *, hydrate) -> None
guard_fiscal_graph_generation(db, principal: Principal, vector_store_id: str, req: VectorStoreGraphLoadRequest) -> None
expand_fiscal_graph(db, principal: Principal, vector_store_id: str, chunks: list[ChunkRecord], *, derivation_run_id: str, filters: dict, relation_types: tuple[str, ...], limit: int, hydrate) -> tuple[list[ChunkRecord], dict[str, dict], dict]
```

Validation returns at least `derivation_run_id`, `artifact_class`, `nodes`,
`edges`. Root serializes load on the scoped vector-store row before generation
guard/binding checks; active-profile replacement is rejected until disabled.
The generation guard rejects a non-identical replay of an existing run, using
exact node/edge ID/type/label/attribute and directed endpoint sets.

Expansion uses `fiscal_chunk_id` and exact existing file attributes, never an
arbitrary first document chunk. The explicit run is not inserted into file
filters. Keep result filters intact; supporting evidence need only satisfy
identity/access, not the result topic filters. Metadata is keyed by chunk ID
and contains `relationships` (bounded list) plus source spans and run. Seed
chunk relationships are retained even when no new chunk is added.

Test support exposes `graph_payload(vector_store_id="vs_fiscal_test", run_id=None,
artifact_class="reviewed_public") -> dict` with all six node types and five
relation types, one FY, distinct source chunk bindings, deterministic IDs; and
`chunk_for_node(node) -> ChunkRecord`. These are synthetic test inputs only, not
review assertions about real SB 125 records.

## Verification / implementation log

Implementation and containerized unit/API/PostgreSQL proof complete:
**1127 passed, 10 skipped, 3 existing deprecation warnings** in the full suite,
with fiscal and Grant PostgreSQL tests enabled against a newly created isolated
database. No fiscal runtime tests skipped. See
`.tranche/kansas-fiscal-graphrag/wave-132-proof.md` and the adjacent full output.
The historical independent review returned **PASS WITH NOTES**; see
`.tranche/kansas-fiscal-graphrag/wave-132-qc.md`. That review predates the
real-corpus findings and does not establish current acceptance.
The note is the actual reviewed StateCivics publisher-envelope producer needed
for real-corpus activation; runtime implementation completion does not mean a
live graph is populated or enabled.

### Real-data correction, 2026-09-10

Added `scripts/release/kansas-fiscal-corpus-audit.py` and
`tests/test_fiscal_real_corpus.py`; updated fiscal design/operator documentation.
The read-only audit verified the Department of Education expenditure extract
for all 16 years against the harvest manifest and retained custody bytes. Eight
real-source regression tests passed with no skips. Exact commands, source
identities, generated evidence location, design corrections and remaining gaps
are in `docs/FISCAL_GRAPH_REAL_DATA.md`.

Independent QC reproduced the audit and eight real-source tests and returned
**PASS WITH NOTES for this corrective increment**, with the full ticket still
open. See `.tranche/kansas-fiscal-graphrag/wave-132-real-data-qc.md`.

The PDF-only node contract is incompatible with the actual structured ontology.
Structured observation projection, citation recovery, reviewed legal-account
links and real end-to-end answers remain required work. The audit neither
publishes candidate records nor changes the runtime's rejection of them.

## Rollback and remaining authority boundary

Disable the fiscal profile to stop expansion; ordinary document search remains
independent. Changes are additive and require no schema migration. A live source
export still needs actual StateCivics review/custody/legal-status evidence. That
data gate does not prevent implementing and proving the ExAIS runtime now.
