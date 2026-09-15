# WAVE-136: Evaluate real-source generalization and incremental graph value

> **Civic Impact work paused by owner — 2026-09-14.**
> [Current delivery, pending CI and resume order](../runbooks/civic-impact-pause.md) supersede older dispatch instructions. Historical proof and unmet acceptance criteria remain.

Status: proposed. Parent: WAVE-132 (reopened). Filed 2026-09-10.

## Summary

Measure whether source-derived semantic descriptions and validated graph traversal improve diverse real law-to-money answers while preserving exact retrieval, numeric correctness and isolation.

## Background

Existing keyword/provenance and relation-ID checks can pass without a correct complete fiscal answer. Product acceptance needs frozen source-derived expected values, paths and citations, plus positive generalization evidence that was not used for tuning.

## Scope

- Extend kansas-fiscal-recall-eval.py as sole five-mode product scorer, leaving existing keyword/relationship-ID checks explicitly smoke-only. Consume KS-651 frozen benchmark contract, source/snapshot/graph/description/profile/run hashes and immutable query ordering. Dry-run produces validated=false or evaluated=false as appropriate, never a product PASS.
- Freeze metric definitions and thresholds jointly with KS-651 before tuning. Compare exact_lexical, document_semantic, entity_semantic, hybrid and hybrid_graph on identical cases/snapshots. Score candidate recall/ranking separately from complete supported path and final answer correctness, monetary/FY/citation correctness, positive success, no-path/refusal quality and leakage.
- Enforce the frozen nontrivial positive denominators/rates, zero prohibited candidate/audience/withdrawn leakage, exact-ID non-regression, numeric/evidence gates, and material graph gain over the better semantic-only mode in development and heldout separately. No total-pass from generic keyword matches, synthetic proof or all-refusal outcomes; no post-hoc exclusions. Repeated extraction/duplicate evidence is deduplicated by canonical source revision/raw hash/locator.
- Reviewer-only entry accepts protected heldout bundle separately from development artifacts and exposes only aggregate signed/hash-bound report. Never log expected answers into developer output or index them. Contaminated holdout invalidates the run and requires KS-651 re-freeze on a new unseen positive bill/agency case.
- Record p50/p95 latency, actual embedding and reranker request counts, tokens/description volume, storage and actual configured profile cost inputs. Exact baseline must show zero embedding and reranker calls using spies and runtime audit. Test outages, stale injected points, graph-disabled candidate leakage, revocation during request, raw/parsed duplicates and cross-store/tenant probes.
- Report all modes and failures on fixed denominators; reproduce deterministic identities/source hashes and report legitimate provider variability. Numeric expected outputs come from retained canonical derivations; corpus audit is source inspection only. Store a reviewed versioned report and public hash/reference to separate heldout report for WAVE-132 activation; do not claim product acceptance from mechanics tests.

## Out Of Scope

- Post-hoc threshold or label tuning
- Synthetic-only product acceptance
- All-refusal acceptance
- New provider/vector-store migration
- Broad rollout or deployment

## Prior Art

Verified during ticket enrichment on 2026-09-10. Read these existing owners before implementing. New files and signatures below are proposed work.

- **Code** — [scripts/release/kansas-fiscal-recall-eval.py](../scripts/release/kansas-fiscal-recall-eval.py): `score_result`. Current generic term/citation/provenance smoke score is insufficient for answers or graph value.
- **Code** — [scripts/release/kansas-fiscal-recall-eval.py](../scripts/release/kansas-fiscal-recall-eval.py): `live_eval`. Existing CLI/evaluator owner for five-mode benchmark extension.
- **Code** — [scripts/release/kansas-fiscal-recall-eval.py](../scripts/release/kansas-fiscal-recall-eval.py): `dry_run_eval`. Currently returns passed=true for requirements listing; new benchmark dry-run must not imply product pass.
- **Code** — [scripts/release/kansas-fiscal-graphrag.py](../scripts/release/kansas-fiscal-graphrag.py): `_relationship_ids`. Existing relationship-ID presence check is mechanics, not path/numeric correctness.
- **Code** — [scripts/release/kansas-fiscal-corpus-audit.py](../scripts/release/kansas-fiscal-corpus-audit.py): `inspect_year`. Existing source record/hash locator audit, explicitly publication_allowed false; not numeric authority oracle.
- **Code** — [packages/svs_common/svs_common/retrieval.py](../packages/svs_common/svs_common/retrieval.py): `RetrievalService._audit`. Existing audit metadata seam for mode/profile/provider counts/latency.
- **Code** — [tests/test_kansas_fiscal_recall_eval.py](../tests/test_kansas_fiscal_recall_eval.py): `test_fiscal_eval_requires_term_citation_and_ledger_provenance`. Existing evaluator regression to retain as smoke-only.

## Current Evidence

Existing keyword/provenance and relation-ID checks can pass without a correct complete fiscal answer. Product acceptance needs frozen source-derived expected values, paths and citations, plus positive generalization evidence that was not used for tuning.

The Prior Art anchors distinguish existing code from the missing behavior. Source inventory and earlier synthetic test passes do not establish real-source product acceptance.

## Implementation Notes

Follow [the agreed law-and-money handoff](../docs/STATECIVICS_LAW_MONEY_ALIGNMENT.md). Preserve existing canonical owners, native contract shapes and record-level evidence requirements.

Use the shared-owner map in [build-contract.json](../.tranche/statecivics-semantic-graph/aligned/build-contract.json) and look up affected files/symbols in [stack.index.json](../.tranche/statecivics-semantic-graph/aligned/stack.index.json). These are local planning artifacts; their signatures describe future work unless marked existing. Runtime must not depend on worktree paths or these planning files.

## Deliverables

- [scripts/release/kansas-fiscal-recall-eval.py](../scripts/release/kansas-fiscal-recall-eval.py) — Single evaluator extended with frozen benchmark modes/labels/metrics/heldout interface. Shared file owner: WAVE-136. Edit sequence: WAVE-136.
- [scripts/release/kansas-fiscal-graphrag.py](../scripts/release/kansas-fiscal-graphrag.py) — Keep relation-ID smoke separate; delegate product scoring to existing recall evaluator. Shared file owner: WAVE-133. Edit sequence: WAVE-133 → WAVE-134 → WAVE-136.
- [packages/svs_common/svs_common/retrieval.py](../packages/svs_common/svs_common/retrieval.py) — Add narrowly scoped audit fields needed to measure existing provider/profile behavior. Shared file owner: WAVE-135. Edit sequence: WAVE-134 → WAVE-135 → WAVE-136.
- [tests/test_kansas_fiscal_recall_eval.py](../tests/test_kansas_fiscal_recall_eval.py) — Scoring, no post-hoc exclusions, dry-run distinction and frozen thresholds. Shared file owner: WAVE-136. Edit sequence: WAVE-136.
- [tickets/WAVE-136-fiscal-real-source-generalization-evaluation.md](WAVE-136-fiscal-real-source-generalization-evaluation.md) — NEW: five-mode real-source product acceptance follow-up. Shared file owner: WAVE-136. Edit sequence: WAVE-136.
- `tests/test_fiscal_hybrid_retrieval.py` (planned new file) — Dependency-owned WAVE-135 test file: extend lifecycle/leakage/provider measurement cases only. Shared file owner: WAVE-135. Edit sequence: WAVE-135 → WAVE-136.

Expected integrated output: WAVE-136 extends the existing recall evaluator to compare all five modes on identical KS-651 frozen cases and produce a reproducible reviewed source-backed report plus separate reviewer-controlled positive heldout report hash. Frozen exact-ID/nontrivial positive/numeric-FY-citation/leakage/material-graph-gain gates apply separately to development and heldout. Report all failures, latency, calls and cost; reject all-refusal, generic keyword, duplicate-evidence, post-hoc exclusion, contaminated holdout and dry-run-as-PASS outcomes. Mechanics tests supplement mandatory real-source evaluation.

## Acceptance Criteria

- Freeze metric definitions, mode comparisons, denominators and thresholds before tuning and bind runs to the KS-651 benchmark revision, source/snapshot/graph manifests, description template and configured provider/profile identities. Held-out answer labels remain reviewer-controlled and unavailable to development/tuning.
- Compare provider-free exact/lexical, document semantic, entity-description semantic, hybrid and hybrid-plus-graph modes. Report candidate recall/ranking, complete correct path/answer rate, monetary/FY/source/citation correctness, refusal and no-path quality, audience/eligibility leakage, stale/withdrawn leakage, latency, embedding calls and storage/embedding cost.
- Require positive source-backed answers across the diversity matrix and on the unseen positive bill/agency case. No post-hoc denominator exclusions, inherited pilot numeric constants, generic-keyword passes or all-refusal success. Keep failures visible, deduplicate repeated source/extraction evidence and distinguish retrieval success from answer correctness.
- Set and enforce a predeclared material graph improvement criterion over semantic-only on both development/tuned and held-out groups, alongside no exact-identifier regression and hard correctness/leakage gates. Provider/profile comparisons stay within existing ExAIS provider scope and record their actual configuration/cost.
- Verify that candidate records cannot leak through ordinary semantic retrieval with graph expansion disabled and that lifecycle removals and wrong-scope/source-snapshot cases cannot pass through exact retrieval, expansion or citations. Test multi-input derivation cases without fabricated pairwise edges and arithmetic without action/fact double counting.
- Run reproducibility checks from the same frozen inputs and report legitimate variability. Synthetic tests remain mechanics/security proof. Produce a reviewed/versioned report with reproducible source-backed expected numeric answers/derivations and held-out evaluation evidence suitable for WAVE-132 activation gating.

## Dependencies

- Canonical prerequisite: KS-651
- Canonical prerequisite: WAVE-135

Dependencies apply to the specific contracts, evidence and eligible records consumed here. Do not wait for unrelated payments/forecasts/outcomes or the full K.S.A. harvest. KS-613 keeps its existing scope; KS-651 owns the separate generalization benchmark.

## Verification

Run after implementation in the required test environment; these commands were not executed during ticket drafting.

```sh
pytest -q tests/test_kansas_fiscal_recall_eval.py tests/test_fiscal_hybrid_retrieval.py
```

All-refusal/generic-keyword/duplicate/contaminated/missing-case reports fail; reviewer-run positive heldout and frozen five-mode real-source report are additional mandatory acceptance.

StateCivics commands must use scripts/run_gate.sh statewide; no host dependency installs. ExAIS pytest commands run inside its existing configured test/container environment; PostgreSQL proof needs explicitly disposable SVS_FISCAL_GRAPH_TEST_DATABASE_URL and cannot count skipped tests as passed. Real-source product acceptance is separate from synthetic tests.

## Risks

Tuning thresholds after seeing held-back answers invalidates the comparison. Freeze thresholds, denominators and source coverage first, require useful positive answers, and report failures without relabeling them.

## Rollback

Keep WAVE-132 acceptance open and the revised fiscal capability disabled if the frozen benchmark fails. Retain failure reports and make any new source/benchmark revision explicit.

## Implementation Log

Implementation has not started under this ticket. Planning only: corrected against the 2026-09-10 developer-manager handoff and independently gated ticket stack. Record actual changed code and verification results here during execution.
