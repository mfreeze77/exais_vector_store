# Agreed StateCivics / ExAIS handoff — 2026-09-10

The owner supplied the developer manager's answers and authorized correction of
the existing tickets and documentation. This is planning and documentation work;
do not implement runtime changes, publish records, index data, deploy, or alter
the running statute harvest. This handoff supersedes contrary proposals in the
earlier intent, legal-assets alignment, and ungated base draft.

## Canonical goal

Enable the Kansas State Civics cell to answer law-to-money questions across
bills and fiscal years by combining semantic and exact retrieval over
source-bound entity descriptions and documents with validated structured graph
relationships, proven on diverse real sources including an unseen bill.

## Settled ownership and boundaries

- ADR-CII-001 / ADR-CII-011 already make statewide StateCivics PostgreSQL the
  canonical civic graph. Custody and the source ledger own retained evidence.
  ExAIS owns rebuildable scoped retrieval indexes and derived graph projections.
- The focused path is enacted provision → appropriation action → fiscal-year
  account → agency/fund, with exact legal and supporting budget evidence.
- `appropriation_action.action_type` owns the legal operation. Fiscal `stage`
  supplies context, `metric` identifies the measured value, and `evidence_class`
  describes the assertion's evidentiary character. Preserve the existing enums.
- KS-595 (in_review at handoff) owns SourceSpan/locator infrastructure and the
  existing retrieval exporter. KS-597 (in_progress) owns anchoring extracted
  fiscal fields to exact spans. KS-600 (proposed) owns legal provision linkage,
  appropriation reconciliation, and the missing provision-reference definition.
  Extend KS-600 before implementation; do not create a competing provision ticket.
- Provision identity is version-specific and separate from displayed numbering,
  source revision/span coordinates, and observation/effective dates. No provision
  ID exists yet: the current ExAIS SourceSpan-as-entity-ID rule must be superseded,
  not described as an already fixed runtime capability. Cross-version continuity
  requires evidenced lineage. Unknown effective dates stay unknown.
- Use `derivation.schema.json` typed inputs/outputs to relate appropriation actions
  to fiscal facts. Verified schema correction to the manager's shorthand: inputs
  require `{type, id, revision_or_hash}`; outputs allow `{type, id, hash_sha256}`,
  where the output hash is currently optional/nullable. KS-600 must supply the
  exact supported output hash for this reviewed lineage. Reuse input and output
  set hashes. Do not add `appropriation_action_id` to fiscal facts or
  create a second lineage table. A multi-input derivation proves joint lineage,
  not an arbitrary Cartesian set of one-to-one action/fact edges; preserve run
  context and require explicit supported correspondence for stronger assertions.
- KS-600 owns allowed field combinations, evidence-class interpretation, snapshot
  selection and reproducible authority arithmetic. Never total an action amount
  together with its linked fact. Separate changes, balances, period flows,
  transfers, authority, and expenditure; incomplete sources never imply zero.
- KS-601 owns reviewed, effective-dated account crosswalks. Preserve ambiguity,
  unknown subunit, code-system and agency/FY scope. Do not duplicate its resolver.

## Export work to assign explicitly

`contracts/civic-impact/retrieval-export-record.schema.json`,
`scripts/operator/export_retrieval_manifest.py`, and the existing service are
the owner for document/custody export. They already carry redistribution,
license_profile, custody_status and lifecycle current/superseded/corrected/
withdrawn plus removal_required. Keep that existing document record compatible.

The canonical entity/relationship projection is unbuilt and unowned. Create one
upstream follow-up ticket extending the KS-595 exporter with a second versioned
record type and explicit dispatch. Do not create an independent exporter stack
or require StateCivics to implement ExAIS's provisional
`statecivics.fiscal-graph-publisher.v1` envelope.

Reuse `publication-record.schema.json` (KS-605) for entity publication/correction
and `intelligence-snapshot.schema.json` for reproducible as-of datasets, budget
baselines, geography vintages, methodology and source sets. These contracts do
not prove their producers or eligible records exist; define compatibility and
record-level prerequisites without gating on entire unrelated ticket epics.

Verified schema correction: publication-record.subject_type currently enumerates
adjudication, forecast_reconciliation, impact_result, law_performance and
actor_reliability, not fiscal entities. KS-650 owns the bounded compatible
extension/mapping needed for these records, coordinated with KS-605; do not
mislabel a fiscal entity as another subject type or claim compatibility exists.

The second record type must support canonical identities/revisions, typed
relationships, typed derivation references, structured CSV evidence or legal/
document spans, eligibility/lifecycle and deterministic source-derived semantic
descriptions. Preserve raw/parsed source distinction. Use existing custody/span
registration and KanView dimensions/observations; no fake PDFs or copied CSV
corpus. Registration/extraction is idempotent missing work, not a second harvest.

Semantic descriptions are rebuildable projections of sourced labels/aliases/
context; exact fiscal data remain structured. No embedding every CSV row or
quarterly total, and no candidate records leaking through ordinary search.
Use each store's configured embedding profile and encode queries accordingly;
canonical-ID federation does not require equal vector dimensions across stores.
Do not add a new provider, graph engine, automatic cross-store expansion, or
global policy changes. Keep provider selection/benchmarking in ExAIS scope.

## Real sources and acceptance

- KS-613 remains the existing school-finance slice: original FY2026 authority,
  $4M lapse, calculated adjusted authority, FY2027 authority, crosswalk, separately
  evidenced payments, explicit forecast absence if applicable, non-causal result,
  correction path and reproduction bundle. Do not widen its scope or require
  its payment/forecast/outcome deliverables for this narrower GraphRAG milestone.
- Create a sibling upstream ticket for the reviewed real-source generalization
  benchmark: at least three enacted bills, two sessions, two FYs, three agencies,
  multiple operations and a positive held-back bill/agency case. Freeze coverage,
  labels/denominators and thresholds before tuning. A reviewer-controlled held-out
  answer set must not be fed into development or tuning. Include no-path/gap cases
  but do not pass solely by refusing answers. Numeric expected answers must be
  supported by retained sources and derivations, not inherited pilot constants.
- Retained seven Session Laws books (2023–2025) can supply enacted provisions.
  Source/custody registration and exact-span readiness must be inspected, not
  inferred from downloaded file counts. Existing narrative retrieval is reusable.
- The K.S.A. harvest is already running outside checkouts. At the manager handoff
  it reported 2,062 / 31,085 sections, chapter 9 / 91, no failures. This is a dated
  report, not live completion evidence. History references are retained unresolved;
  current statutes supply standing authority/definitions/lineage and do not
  replace uncodified appropriation acts. No pre-harvest canary/start task remains.
- Reported source/dimension counts are inventory snapshots, not public eligibility.
  Synthetic tests remain mechanics/security proof; real chains and cited answers
  determine product acceptance.

## Repositories and plan output

- ExAIS active runtime worktree:
  `/Users/mfrieson/Developer/exais-vector-store-ovh`. Preserve existing uncommitted
  runtime files. Only edit tickets/docs/planning artifacts in this turn.
- Upstream planning worktree:
  `/Users/mfrieson/Developer/statecivics-fiscal-graph-plan`, fast-forwarded from
  the clean planning branch to current main before edits. Canonical operational
  checkout is `/Users/mfrieson/Dropbox/AI_Projects/exai_projects/Statecivicsai`;
  do not edit its running-harvest source or operational data.
- Instance research/downloads live in the user's ExAIS workspace at
  `/Users/mfrieson/Dropbox/AI_Projects/exai_projects/exais_vector_store/instances/ks-state-civics/research/`.
  Read `law-and-money-backbone.md`; downloaded source is optional reference, not
  an adoption requirement. Do not add repository SHA pins/submodules to downloads.
- Correct the ungated draft in a fresh `aligned/` pipeline directory, preserving
  the old draft as superseded history. Output base/enriched/build-contract/index
  there. Use absolute file paths for cross-repository gate checks; distinguish
  existing `code_refs` from proposed new files and signatures.
- Existing ticket IDs stay stable. At inspection StateCivics max is KS-649 and
  ExAIS max WAVE-132. Intended new upstream tickets: KS-650 exporter extension,
  KS-651 cross-bill acceptance sibling. Recheck allocation before materializing.
  ExAIS follow-ups can start WAVE-133 for typed structured evidence, ingestion,
  retrieval/traversal, and evaluation. Keep WAVE-132 the reopened parent and
  activation acceptance gate. Do not create a competing KS-600/601 implementation.
- Amend related KS-595/597/601 docs by owner references and bounded requirements;
  keep their implementation history/status intact. KS-613 needs only the sibling
  pointer. Root will materialize final Markdown tickets and update indexes after
  all gates. Plan agents write only their assigned JSON artifacts.

## Current ExAIS contradictions to correct

- WAVE-130 / CELL_GRAPH_PROFILES uses SourceSpan as enacted-provision identity.
- V1 requires document/chunk bindings for every entity, excluding CSV dimensions.
- WAVE-132's runtime mechanics and earlier PASS are not current product acceptance.
- Provisional publisher envelope duplicates the unbuilt upstream contract boundary.
- Old draft T-011 treats harvest and history capture as future/pre-canary work.
- Historical bill-specific and synthetic proof cannot stand in for generalization.

Mark the existing v1 details as historical implementation constraints and record
the agreed replacement requirements explicitly. Do not claim code changed just
because its governing tickets and docs now describe the required correction.
