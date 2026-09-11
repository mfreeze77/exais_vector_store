# WAVE-133: Project canonical identities and typed structured evidence into the fiscal graph

Status: in progress — independent offline foundation; upstream integration pending. Parent: WAVE-132 (reopened). Filed 2026-09-10.

## Summary

Replace the current provision identity and document-only evidence constraints with a rebuildable ExAIS projection of the upstream canonical contract.

## Background

The provisional fiscal graph uses SourceSpan as legal provision identity and requires document/chunk bindings for every entity. Accounting dimensions derived from CSVs therefore cannot be represented truthfully, and existing single-run replacement needs complete manifest and partition semantics.

## Scope

- Add fiscal v2 canonical references, document_span|structured_record evidence, typed derivation/run references, relationship assertions, bounded batches and complete manifests in schemas.py. Distinguish canonical legal/entity version IDs, evidence IDs and ExAIS projection IDs. Document spans bind real documents/chunks where present; CSV structured records require no chunk/document.
- Reuse graph_nodes/graph_edges for rebuildable projections with bounded canonical fields, descriptions, evidence/publication/snapshot metadata. Add explicit derivation run nodes/refs with directional inputs/outputs; supported stronger correspondence is separate. No canonical graph engine or new authority ledger.
- Keep existing max 1000 nodes/2000 edges PER BATCH. Manifest declares snapshot/run, ordered partition IDs/digests/counts and total expected nodes/edges. Validate complete accounting, duplicate/conflicting identity, cross-partition endpoint resolution and stream/batch limits before activation. No silent truncation or unbounded cap increase.
- Use immutable manifest/partition identity. A new bill stages into a new complete manifest that explicitly includes all retained approved bill/FY partitions. Replay guard compares identical partition contents rather than demanding one whole-run load. WAVE-134 owns active-pointer switching and removal; loading bill B cannot silently evict A.
- Retain historical v1 validation for audit/approved rollback; do not reinterpret SourceSpan identities as new provisions or require StateCivics to emit provisional publisher v1. Rebuild corrected v2 projection from KS-650 records and KS-600 identity.
- Define FiscalEvidenceCitation separately from ContextCitation: evidence kind, canonical subject/revision, source revision/raw hash, exact locator/public URL/digest, optional actual chunk/document only for document_span. Define entity results separately from ChunkRecord. WAVE-135 exposes native fiscal typed results/answers; a file-only compatibility endpoint cannot fake a file citation for a structured row.

## Out Of Scope

- Canonical civic graph ownership in ExAIS
- New graph engine or universal ontology
- Unbounded graph limits
- Fabricated document/chunk bindings
- Inferred Cartesian derivation edges
- Global policy changes

## Prior Art

Verified during ticket enrichment on 2026-09-10. Read these existing owners before implementing. New files and signatures below are proposed work.

- **Code** — [packages/svs_common/svs_common/fiscal_graph.py](../packages/svs_common/svs_common/fiscal_graph.py): `validate_fiscal_graph`. V1 strict SourceSpan provision identity, chunk fields, one run, same-year endpoints and 1000/2000 bounds.
- **Code** — [packages/svs_common/svs_common/fiscal_graph.py](../packages/svs_common/svs_common/fiscal_graph.py): `validate_fiscal_graph_bindings`. Every entity requires an accessible current chunk; structured-only cannot work currently.
- **Code** — [packages/svs_common/svs_common/fiscal_graph.py](../packages/svs_common/svs_common/fiscal_graph.py): `guard_fiscal_graph_generation`. Whole-run replay comparison must become partition-aware.
- **Code** — [packages/svs_common/svs_common/fiscal_graph.py](../packages/svs_common/svs_common/fiscal_graph.py): `fiscal_node_id`. Existing scoped deterministic projection IDs; distinct from canonical identities.
- **Code** — [packages/svs_common/svs_common/fiscal_graph_artifact.py](../packages/svs_common/svs_common/fiscal_graph_artifact.py): `build_fiscal_graph_artifact`. Historical provisional publisher/PDF-only evidence adapter.
- **Code** — [packages/svs_common/svs_common/fiscal_graph_artifact.py](../packages/svs_common/svs_common/fiscal_graph_artifact.py): `validate_built_artifact`. Existing manifest digest validation seam.
- **Code** — [packages/svs_common/svs_common/schemas.py](../packages/svs_common/svs_common/schemas.py): `ContextCitation`. Requires chunk_id/document_id; separate structured citation type needed.
- **Code** — [apps/api/svs_api/main.py](../apps/api/svs_api/main.py): `load_vector_store_graph`. Existing store-locked graph API and persistence integration.
- **Code** — [scripts/release/kansas-fiscal-graphrag.py](../scripts/release/kansas-fiscal-graphrag.py): `main`. Existing build/validate/load entry point.
- **Code** — [tests/test_fiscal_graph_postgres.py](../tests/test_fiscal_graph_postgres.py): `test_immutable_replay_and_separate_generation`. Existing generation persistence proof.

## Current Evidence

The provisional fiscal graph uses SourceSpan as legal provision identity and requires document/chunk bindings for every entity. Accounting dimensions derived from CSVs therefore cannot be represented truthfully, and existing single-run replacement needs complete manifest and partition semantics.

The Prior Art anchors distinguish existing code from the missing behavior. Source inventory and earlier synthetic test passes do not establish real-source product acceptance.

## Implementation Notes

Follow [the agreed law-and-money handoff](../docs/STATECIVICS_LAW_MONEY_ALIGNMENT.md). Preserve existing canonical owners, native contract shapes and record-level evidence requirements.

Use the shared-owner map in [build-contract.json](../.tranche/statecivics-semantic-graph/aligned/build-contract.json) and look up affected files/symbols in [stack.index.json](../.tranche/statecivics-semantic-graph/aligned/stack.index.json). These are local planning artifacts; their signatures describe future work unless marked existing. Runtime must not depend on worktree paths or these planning files.

## Deliverables

- [packages/svs_common/svs_common/fiscal_graph.py](../packages/svs_common/svs_common/fiscal_graph.py) — Own v2 identity, evidence, relation, partition and manifest validation. Shared file owner: WAVE-133. Edit sequence: WAVE-133 → WAVE-134 → WAVE-135.
- [packages/svs_common/svs_common/fiscal_graph_artifact.py](../packages/svs_common/svs_common/fiscal_graph_artifact.py) — Own KS-650 adapter and complete bounded manifest validation. Shared file owner: WAVE-133. Edit sequence: WAVE-133.
- [packages/svs_common/svs_common/schemas.py](../packages/svs_common/svs_common/schemas.py) — Own fiscal typed evidence/citation/entity-result/batch/manifest definitions. Shared file owner: WAVE-133. Edit sequence: WAVE-133 → WAVE-135.
- [apps/api/svs_api/main.py](../apps/api/svs_api/main.py) — Wire fiscal v2 validation to existing graph persistence. Shared file owner: WAVE-133. Edit sequence: WAVE-133 → WAVE-134 → WAVE-135.
- [scripts/release/kansas-fiscal-graphrag.py](../scripts/release/kansas-fiscal-graphrag.py) — Extend existing build/validate dispatch. Shared file owner: WAVE-133. Edit sequence: WAVE-133 → WAVE-134 → WAVE-136.
- [tests/test_fiscal_graph.py](../tests/test_fiscal_graph.py) — Version/identity/typed relationship mechanics. Shared file owner: WAVE-133. Edit sequence: WAVE-133 → WAVE-135.
- [tests/test_fiscal_graph_artifact.py](../tests/test_fiscal_graph_artifact.py) — Second-kind and structured-only evidence proof. Shared file owner: WAVE-133. Edit sequence: WAVE-133.
- [tests/test_fiscal_graph_postgres.py](../tests/test_fiscal_graph_postgres.py) — Coexisting partitions and immutable replay. Shared file owner: WAVE-133. Edit sequence: WAVE-133 → WAVE-134 → WAVE-135.
- [tickets/WAVE-133-fiscal-canonical-projection-contract.md](WAVE-133-fiscal-canonical-projection-contract.md) — NEW: typed projection/evidence follow-up. Shared file owner: WAVE-133. Edit sequence: WAVE-133.

Expected integrated output: WAVE-133 defines one v2 canonical-reference/evidence/citation/entity-result/batch/complete-manifest contract and consumes KS-650 through the existing fiscal graph adapter/validator/API. Multiple bill/FY partitions coexist, each bounded at 1000 nodes/2000 edges, with global counts/hashes/endpoint/replay checks; structured-only evidence needs no chunk. Typed run lineage preserves direction and excludes Cartesian correspondence. Contract and disposable PostgreSQL proof cover prior document compatibility and incomplete/conflicting partition rejection; historical v1 remains explicit audit/approved-rollback behavior.

## Acceptance Criteria

- Supersede SourceSpan-as-enacted-provision-ID in WAVE-130/CELL_GRAPH_PROFILES and the v1 requirement that every entity have a document/chunk binding. Mark these as historical implementation constraints and define migration/compatibility behavior without claiming the existing runtime is already corrected.
- Consume upstream canonical identity/revision and KS-600 provision references. Model structured CSV dimension/observation evidence separately from source/document spans, allowing structured-only entities with valid retained evidence. Preserve raw/parsed revisions, record/section locators, precise source bindings and observation/effective dates without inventing dates or PDFs.
- Preserve typed relationship direction, legal action role, agency/fund/account/FY scope, evidence, eligibility, revision and typed derivation references/run context. Support enacted provision to appropriation action to fiscal-year account to agency/fund with exact legal and supporting budget evidence. Represent joint derivation lineage without automatically materializing every input/output pair as one-to-one correspondence.
- Do not create edges from semantic similarity, section-number equality, unresolved statute History or normalized account labels. Stronger legal lineage or action/fact edges require explicit source-backed upstream correspondence.
- Define bounded partitions/batches and complete manifest accounting for multiple bills, years, and source revisions; reject incomplete/truncated activation. Loading another bill does not silently replace the first. Preserve immutable source/run/snapshot identity and a migration/rollback route for supported prior artifacts.
- Focused contract/persistence tests cover structured-only and document-span evidence, identity stability under re-extraction, separation across legal versions, joint-lineage edge rejection, typed path provenance/direction, multiple coexisting partitions, incomplete manifests, and valid prior document records.
- Resolve document locators against the pinned retained extraction, compare selected text with the exact quote/hash, and preserve raw-source derivation. Page/line type checks and a supplied quote/hash agreement alone are insufficient. Test wrong page/line bounds, truncated clauses, changed extraction bytes and incompatible locator conventions; never discard line fields to fit the legacy page-only adapter.

## Dependencies

- Canonical prerequisite: KS-600
- Canonical prerequisite: KS-650

Dependencies apply to the specific contracts, evidence and eligible records consumed here. Do not wait for unrelated payments/forecasts/outcomes or the full K.S.A. harvest. KS-613 keeps its existing scope; KS-651 owns the separate generalization benchmark.

## Verification

Run after implementation in the required test environment; these commands were not executed during ticket drafting.

```sh
pytest -q tests/test_fiscal_graph.py tests/test_fiscal_graph_artifact.py tests/test_fiscal_graph_postgres.py
```

Structured-only entities, independent legal identity, typed directed lineage, coexisting partitions and complete manifest accounting.

StateCivics commands must use scripts/run_gate.sh statewide; no host dependency installs. ExAIS pytest commands run inside its existing configured test/container environment; PostgreSQL proof needs explicitly disposable SVS_FISCAL_GRAPH_TEST_DATABASE_URL and cannot count skipped tests as passed. Real-source product acceptance is separate from synthetic tests.

## Risks

Conflating legal identity with evidence or treating derivation membership as pairwise proof creates false relationships. Incomplete manifest replacement can erase unrelated bill/year partitions. Validate identity, evidence and complete partition accounting independently.

## Rollback

Disable the fiscal projection/profile if validation fails. Preserve canonical source data and compatible document search; retain complete prior eligible generation manifests for diagnosis and a reviewed rollback.

## Implementation Log

2026-09-10: the owner authorized coder workers and independent quality review,
and confirmed that the StateCivics developer manager owns the KS tickets.
ExAIS implementation runs in the separate feature worktree
`/Users/mfrieson/Developer/exais-vector-store-law-money` on
`feat/statecivics-law-money-projection`, based on the preserved `3230b74` handoff.

The initial increment implements only independent offline typed evidence,
partition/manifest validation, and retained CSV evidence verification. It does
not define the KS-650 wire schema or a canonical provision identifier. The
existing runtime remains unchanged while these components are built and tested.

Read-only upstream inspection found no provision-reference contract or second
entity/relationship export implementation at planning `3650b8c5` or operational
`8ffabad9`. KS-600/650 remain integration prerequisites. The existing KanView
loader retains canonical observation identities but leaves source locators empty;
the ExAIS byte/record verifier cannot repair or publish those canonical records.

Full acceptance still requires the actual upstream contract and reviewed export,
adapter/API and disposable PostgreSQL integration, and the remaining acceptance
criteria above. WAVE-134 through WAVE-136 have not started.

The independent foundation is implemented: internal typed evidence/citations,
complete bounded manifests and retained-partition replay, source/extraction
revision hash consistency, and the offline CSV byte/record verifier. Root's
combined container check returned **272 passed, zero skipped**, including the
real source tests and existing API contracts. See
[the implementation proof](../.tranche/statecivics-semantic-graph/aligned/wave-133-offline-proof.md)
for commands, source coverage and deferred acceptance. Independent review found
and then verified the fix for a verifier/typed-locator composition defect;
[review 2](../.tranche/statecivics-semantic-graph/aligned/wave-133-offline-qc-2.md)
returned **PASS WITH NOTES** for this increment. No full-ticket completion or
activation is claimed.

Follow-up manager clarification: the next retained-source sample is KS-613's
SB 125 section 96(j) provision and lapse action. KS-600 must supply its legal
identity and persisted action; KS-597 supplies exact spans and KS-601 reviewed
crosswalks (or an explicit unresolved gap). KS-650 supplies the actual export
contract/records. Existing accounting identities and observations are reusable,
but neither ticket visibility nor K.S.A. harvest completion fills these gaps.
The [current handoff](../docs/STATECIVICS_LAW_MONEY_ALIGNMENT.md#current-implementation-handoff)
records the sequence and preserves StateCivics ownership of that work.

The manager subsequently located retained section 96(j) evidence and reported
starting KS-600's provision-reference contract. Consume the resulting upstream
identities/records when delivered; do not invent its wire schema. An unresolved
legal-account crosswalk does not prevent preserving or citing the lapse action,
but it must prevent asserting a reviewed composite join. The [retained-source
review](../instances/ks-state-civics/research/sb125-provision-handoff.md) supplies
the evidence locator and distinguishes the Chapter 128 amendment marker from
the scope actually checked. This update does not complete upstream persistence
or WAVE-133 integration.

Seven-book extraction follow-up: verified retained source/output hashes and
unique ordered page markers across 6,587 declared pages. The [readiness
audit](../instances/ks-state-civics/research/session-law-extraction-readiness.md)
corrects section 96(j)'s proposed character endpoint, documents producer-side
QA/registration exclusions and preserves the same owner boundary. These
machine-readable bytes are now available for evidence review; the canonical
schemas, reviewed derivation/records and adapter/API acceptance remain separate.

The page-local follow-up verified section 96(j) at page 358, inclusive lines
30–34 under an explicit marker/blank-line convention. Registration and current
offline ExAIS validation do not yet prove that a locator selects the supplied
quote. The [concrete integration handoff](../docs/STATECIVICS_LAW_MONEY_ALIGNMENT.md#concrete-input-needed-for-exais-integration)
lists the incoming records/evidence and remaining ExAIS implementation. This
clarifies existing evidence acceptance; no runtime completion is claimed.
