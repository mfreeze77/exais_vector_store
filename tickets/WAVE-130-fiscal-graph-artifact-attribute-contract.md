# WAVE-130 Fiscal Law-and-Money Graph Artifact Contract

Filed: 2026-09-10. Reconciled against ExAIS `bb7e575` and StateCivics
`4cc4c262e3bf736c2140c833e55b3b13a8730aa5`.
Status: historical documentation proof complete; key v1 requirements superseded
by the 2026-09-10 StateCivics manager alignment. The earlier independent QC PASS
does not establish real-source suitability or acceptance of the corrected runtime.

Read [the unified handoff](../docs/STATECIVICS_LAW_MONEY_ALIGNMENT.md) before
implementation. WAVE-133 replaces SourceSpan-as-provision identity and universal
PDF/chunk evidence; WAVE-134 consumes the KS-650 extension of the existing
StateCivics exporter. The remaining v1 description is preserved as implementation
history, not a competing upstream contract. WAVE-132 remains reopened.

## Goal

Define the citation-preserving graph contract for the owner's approved chain:

**Enacted provision → appropriation → agency/fund/account → supporting budget
documents.**

This is a contract-design ticket. It authorizes no runtime implementation,
source publication decision, graph load, or profile activation.

## Owner scope decision

The owner explicitly approved the chain above in the current conversation:
“that is perfect Enacted provision → appropriation → agency/fund/account →
supporting budget documents.”

The first curated reference is SB 125 Supplemental State Aid, FY2026/FY2027,
limited to its enacted provisions, appropriation operations, canonical account,
agency, fund, and cited supporting legal/budget documents. The implementation
budget is at most 1,000 evidence nodes and 2,000 edges, one hop per request,
0–10 added chunks (default profile cap 3), at most 10 seed chunks and 200
candidate edges. No silent truncation or large-graph batching is in scope.

The complete approved chain is the first-release target. An agency-only fixture
does not fulfill it. Fixture work can progress while individual real-data links
are unavailable; report gaps rather than synthesizing them.

Payments, recipients, outcomes, forecasts, claim adjudication, district-impact
models, and Workbench simulation are outside this release. Those remain
StateCivics responsibilities. ExAIS retrieves cited relationships and documents;
canonical fiscal facts, amounts, legal status, review, and corrections stay in
StateCivics.

## Contract and implementation boundaries

The historical design is the **Historical Kansas fiscal artifact contract v1**
section in [CELL_GRAPH_PROFILES.md](../docs/CELL_GRAPH_PROFILES.md). It specified:

- Six fiscal-only node types and five directed relationship types covering the
  approved chain, separate from Grant vocabulary.
- Strict node/edge attributes, canonical digest/identity rules, exact FY and
  bill-version context, source revision/span/chunk bindings, and one completed
  relationship-export derivation run per artifact.
- Existing WAVE-129 document-file join keys. Many entities/spans can share a
  document; graph-only changes do not require adding scalar entity/span/run
  attributes to files or re-embedding them.
- Type-specific canonical eligibility and normalized publisher assertions,
  including the distinction between published ontology rows and appropriation
  actions. Actual human review is not independently proven by an ExAIS tag.
- The existing JSON graph-load envelope, proposed explicit fiscal lens and
  run selector, access checks, replacement/correction behavior, and separate
  fiscal runtime manifest.

This ticket adds documentation only. A future fiscal handler must register
`kansas_fiscal_law_money_graph_v1` / `kansas_fiscal_documents` and route fiscal
validation before the generic loader. `GRAPH_HANDLERS` currently registers only
Grant and `_cell_graph_profile_or_503` is Grant-gated. A fiscal manifest remains
unloadable through that resolver until runtime work lands.

The existing `instances/ks-state-civics/graph/profile.yaml` describes courts;
leave it unchanged. A future fiscal example belongs under the fiscal source
package and is rendered to a separate operator-owned runtime file selected by
`SVS_CELL_GRAPH_PROFILE_PATH`. The loader accepts one strict manifest, not a
multi-profile YAML document.

## Current grounding and outstanding inputs

| Source | Verified contract/code | Remaining requirement for a real graph |
| --- | --- | --- |
| KS-595 source ledger | `SourceArtifactRevision`, `SourceSpan`, `DerivationRun`; immutable provenance | Exact retained source revisions, populated spans, and a completed relationship-export run |
| KS-598 fiscal ontology | Canonical dimensions/accounts, separate source observations, publication/resolution/lifecycle fields | Eligible reviewed identities and cited component relationships for this selected chain |
| KS-600 appropriation reconciliation | `appropriation-action.schema.json` defines exact bill version, action, source, period, review/status; ticket remains proposed | Published actions and independently established enacted legal status, with veto/override/period reconciliation |
| KS-601 account bridge | Current `AccountCrosswalk` uses status/publication_allowed/review; aliases are candidates in dated ticket evidence | Positive reviewed crosswalk only when this chain needs one; whole-ticket completion is not a universal gate |
| Narrative retrieval exporter / WAVE-129 | Current retained narrative/legal source records become deterministic document manifests; file identity/provenance already exists | A distinct cited relationship export and ExAIS span-to-chunk adapter; existing document export does not supply either |

Open/in-review ticket statuses are dependency signals, not proof that no
eligible canonical record can exist. Inspect actual exported records and their
review, source, publication, legal-status, and lifecycle evidence at activation.
This ticket does not query the upstream database or claim a live eligibility
audit. In particular, it does not repeat the old unverified payment/payee counts
or treat document/chunk counts as activation thresholds.

Important corrections to the original proposal:

- Fiscal logical document IDs are lowercase SHA-256 strings, not Grant UUIDs.
- Source-revision hashes need hex validation/lowercase normalization; their
  upstream database check guarantees length only.
- Ontology evidence spans are nullable upstream. Span-less records cannot
  produce cited nodes/edges.
- Canonical dimensions and accounts have separate observation/derivation
  records; not every entity row itself carries a derivation ID. One export run
  binds the selected input set without replacing its individual provenance.
- An enrolled PDF is not proof that each provision survived into effective law.
- `AccountCrosswalk` lacks the ontology status triplet. A published `not_same`
  decision is valid negative evidence and cannot create a positive graph link.
  Candidate aliases and unresolved/ambiguous mappings are not publication.
- Court GraphRAG (WAVE-115), Topeka routing, Grant validation, and ordinary
  document ingestion/search are existing separate behavior.

## Scope

- Update this ticket in place to record the approved product boundary.
- Add the fiscal design to `docs/CELL_GRAPH_PROFILES.md`.
- Record source/export/runtime dependencies without fabricating completion.
- Mark the previous broader/ontology-first local tranche as superseded for
  implementation; retain its artifacts as historical planning evidence.

## Out of scope

Runtime modules, API/ACL changes, migrations, handlers/lens registration,
upstream writes/review, fixtures loaded into a live cell, deployment, new
database services, and follow-up ticket implementation.

## Acceptance criteria

- [x] A fiscal-specific attribute and identity contract is documented with no
  fiscal `gip_*` keys.
- [x] The full owner-approved chain has explicit node types, typed directed
  edges, scope exclusions, and a curated budget below 10,000/20,000.
- [x] Exact source revision/span/chunk evidence, 1–20 citations per edge,
  lowercase-hex validation, FY context, and bill-version requirements are explicit.
- [x] One relationship-export derivation run binds the artifact while preserving
  separate input derivation provenance.
- [x] Type-specific publication rules reject ineligible ontology/actions and
  negative/candidate/ambiguous account mappings without inventing source fields.
- [x] The file-attribute mapping handles multiple entities/spans per document,
  and the graph selector does not accidentally become a document-file filter.
- [x] KS-595/598/600 and conditional KS-601 dependencies, the missing relationship
  export/span adapter, and current handler/profile limitations are explicit.
- [x] Scope-isolated load/search, source corrections, generation switching,
  fixture separation, and rollback requirements are defined for future runtime.
- [x] No runtime files, live graphs, profile settings, or upstream records are changed.

## Verification and proof

Read-only code/contract anchors inspected:

- `packages/svs_common/svs_common/grant_graph.py` — existing strict validator,
  bounds, scoped expansion, Principal/filters/hydrate seam.
- `packages/svs_common/svs_common/cell_graph.py` — strict single-profile schema,
  handler allowlist, exact Principal/store/attribute binding.
- `packages/svs_common/svs_common/schemas.py` — graph request fields/defaults.
- `packages/svs_common/svs_common/search_lenses.py` — explicit lens/input seam.
- `apps/api/svs_api/main.py` — `_load_vector_store_graph`,
  `_cell_graph_profile_or_503`, `_graphrag_enabled_for_vector_store`.
- `scripts/release/kansas-fiscal-document-ingest.py:_record_attributes`.
- Fiscal `store.yaml` and existing Kansas court `graph/profile.yaml`.
- StateCivics `models/source_artifacts.py`, `models/fiscal_intelligence.py`,
  `core/identifiers.py`, `alembic/versions/100_civic_fiscal_dimensions.py`,
  `services/civic_impact/retrieval_exporter.py`, and the appropriation contract.
- Current StateCivics KS-595, KS-598, KS-600, KS-601 ticket metadata and recorded
  implementation evidence, plus the overall source package read earlier.

Verification commands/results:

- `git diff --check` — no whitespace errors.
- `git diff --stat` — tracked changes are this ticket and the appended fiscal
  contract only (2 files).
- A Python standard-library check compared the pre-fiscal-section bytes of
  `CELL_GRAPH_PROFILES.md` with `git show HEAD:docs/CELL_GRAPH_PROFILES.md`,
  asserted the exact tracked changed-file set, and resolved the new local
  handoff links — PASS.

The exact documentation-check script and output are recorded in
`.tranche/kansas-fiscal-graphrag/wave-130-proof.md`. Independent QC returned PASS;
its criterion-by-criterion review is in
`.tranche/kansas-fiscal-graphrag/wave-130-qc.md`.
No application tests or live graph calls are needed for this documentation
change, and no runtime behavior is claimed tested by it.

## Rollback

Revert only this ticket's documentation changes. No graph/data rollback is needed.
Future runtime activation uses a separate disabled fiscal profile and explicit
scope/run/source checks; disabling that profile is the immediate runtime rollback.

Related work: WAVE-115 court proof; WAVE-126 profile mechanism; WAVE-129 fiscal
document ingestion; WAVE-131 embedding batching. The local tranche's earlier
build contract is historical after the owner's narrowed scope decision.
