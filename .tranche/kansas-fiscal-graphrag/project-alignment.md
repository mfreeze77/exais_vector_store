# Civic Impact Intelligence alignment

Read on 2026-09-10 at the user's request. Planning notes only: no runtime changes, source review decisions, or activation are made by this document.

## Sources and precedence

- User-specified package: `/Users/mfrieson/Dropbox/AI_Projects/exai_projects/statecivics-civic-impact-intelligence`. Read `README.md`, `SUPERSEDED.md`, numbered chapters 00–14, contract overview, and both SB 125 pilot explanations. The compiled full spec duplicates the chapter set.
- Current canonical StateCivics repository: `/Users/mfrieson/Dropbox/AI_Projects/exai_projects/Statecivicsai`, inspected at `4cc4c262e3bf736c2140c833e55b3b13a8730aa5`. Current tickets, models, and service code take precedence over package completion claims and historical numbering.
- Read current `AGENTS.md`, `workbench/ARCHITECTURE_AMENDMENT.md`, `docs/specs/civic-impact-intelligence/FISCAL_DATABASE_AND_ETL_BUILDOUT.md`, `FISCAL_INGESTION_IMPLEMENTATION_PLAN.md`, and KS-601 implementation notes alongside the source/ontology/exporter code.
- ExAIS inspected at `bb7e575016ed398a6f9379d6bddf4bda0ca8639f` in this isolated worktree.

The package says it was applied and must not be reapplied. Its supersession note records an earlier +6 ticket shift; current matching titles are KS-594–KS-624 (original package KS-585–KS-615). Resolve by current title and file, not an arithmetic renumbering rule. Workbench is now under `Statecivicsai/workbench/` per KS-627; its services still have separate databases, credentials, and custody boundaries.

## Product intent

The four planes are Civic Record (who said or did what), Fact Graph (claims, propositions, evidence, adjudication), Civic Impact Graph (exact legal changes through fiscal authority to observations), and Policy Forecast Ledger (attributed forecasts, maturity, actuals, reconciliation).

The long-term loop is official sources → civic intelligence → snapshot-bound drafting → publication candidate → official-source reconciliation → observed outcomes and forecast reconciliation → future drafting.

The first complete case is SB 125 Supplemental State Aid: exact enacted source/version → appropriation action and account `652-00-1000-0840` → final authority → reviewed payment-code crosswalk → KSDE payment evidence for Topeka USD 501. Package amounts are fixture expectations, not newly verified live figures. District allocation and causal attribution require additional accepted evidence/methods.

## Consequences for ExAIS GraphRAG

1. StateCivics owns canonical fiscal identities, amounts, exact source spans, derivations, review, and corrections. ExAIS owns a rebuildable retrieval projection with citations and access controls.
2. Preserve exact bill/source revisions, fiscal period, accounting basis, fiscal stage, and evidence class. Official, calculated, modeled, observed, and causal results must remain distinguishable.
3. Reuse PostgreSQL graph tables and bounded, explicitly selected relationship expansion. Qdrant retrieves candidates; similarity cannot approve an account join or proposition equivalence. A new graph database is unnecessary for this scope.
4. The narrative document exporter deliberately excludes raw transaction extracts. Payments and totals remain structured canonical queries. Do not turn millions of CSV rows into narrative chunks or sum search hits to answer a fiscal question.
5. The broader appropriation-to-outcome chain guides the projection, but the first ExAIS implementation remains bounded by available reviewed source records. It does not implement the Forecast Ledger, impact simulator, Workbench gateway, or public adjudication.
6. Support fixture development before activation, with real-corpus activation requiring reviewable canonical exports, exact document identity, source-span/citation resolution, generation/lifecycle checks, and isolation proof.

## Current upstream distinctions that affect the contract

- KS-595 custody, KS-596 version binding, KS-598 ontology/loader, KS-597 fiscal extraction, and the narrative retrieval exporter have concrete code. Their ticket status is not equivalent to complete production acceptance.
- KS-601 now has `AccountCrosswalk` and `CrosswalkCandidate` models plus migration 110. Ticket notes report the operator crosswalk tables are empty by design. Loaded alias rows are still candidates; a unique dictionary match is not publication approval.
- Ontology records use `publication_status`, `resolution_status`, and `lifecycle_status`. `AccountCrosswalk` instead follows its normative contract: `status`, `publication_allowed`, review, effective period, identity pair, and revision chain. Do not invent the ontology status triplet on crosswalk decision rows.
- A published crosswalk can say `not_same`. That is a negative decision, not a positive account/payment edge. Reviewed-but-unpublishable decisions are valid upstream records and must not be exported as approved public joins.
- KS-601's proposed ambiguous-set publication semantics still await owner sign-off. ExAIS must not resolve that policy dispute or collapse candidate sets into a single account.
- Current tickets identify KS-612 as recipient ingestion, KS-613 as the grounded school-finance vertical, KS-620 as the drafting gateway, KS-621 as simulation, and KS-624 as the closed-loop proof. The latter roadmap capabilities remain proposed.
- Some current prose still lags implementation: for example the build-out notes mark the official USD list resolved while the ingestion plan's final unresolved list retains the old blocker. Recheck code and dated evidence at the relevant implementation boundary.

## Immediate direction

Reconcile WAVE-130's fiscal projection contract with these actual upstream shapes, then implement and test a small inactive projection and explicit search lens. Prove corrected/withdrawn sources and unreviewed/negative/ambiguous mappings cannot produce positive public relationships. Real graph loading waits for the required reviewed source records; ordinary fiscal document search can continue independently.
