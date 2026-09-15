# Civic Impact / ExAIS pause — 2026-09-14

The owner paused this work. No development, migration, import, harvest, model calls or deployment resumes until asked. Source and handoff belong in the canonical repositories; do not create new coding roots or loose scripts under ~/Developer.

## Delivered locally

Implementation main 8c7eecc792387d1f7cc13b31df0ea468d8eeed45 is pushed: **2,391 HB 2513 candidate actions + 197 provisions = 2,588 stored records**, full readback, idempotent repeat and three expected rank-one cited examples. [Bulk runbook](statecivics-candidate-bulk.md), [receipt](statecivics-bulk-delivery-20260914.json). These are candidate answers, not reviewed final authority or actual-spending reconciliation. Public VPS delivery was not established.

Actual profile: **openai_text_embedding_3_small_1536**; collection **svs_biz_ks_state_civics_statecivics_candidates_openai_small_v1**. Codex chose it under owner delivery authorization. It is the current candidate decision, not a temporary Voyage bridge. Actual billed USD remains unverified. The detailed WAVE-134 correction is one of the five pending CI commits; this dated note supersedes its old Voyage planning paragraph until that branch merges.

## Preserve the CI repair

Branch **ci-repair-post-8c7eecc**, pushed at **b6f98e04f56e481903ce2e6109a24e15d32fd565**, remains unmerged. Preserve all five commits: 8414374, 0e25b8d, b980770, ae45e7c, b6f98e0.

[Hosted run 34918560579](https://github.com/mfreeze77/exais_vector_store/actions/runs/34918560579) is **failed** at the absent STATECIVICS_READ_TOKEN preflight. Hosted Python proofs did not execute. RLS integration and separate migration-tests/image-release passed.

Independent Docker QC passed 1,661 general tests with 144 existing named skips and 34 exact corpus deselections, zero errors. Actual retained corpus: 34 passed, both fixture preflights passed, no skips. Provenance SET: 7 passed; UNSET: one required intentional failure. Additional response/storage proof: 52 passed. These are local results, not hosted green.

After resumption, the owner supplies a fine-grained short-lived Contents read-only token scoped to private mfreeze77/state-civics-ai, stored as this repo's **STATECIVICS_READ_TOKEN** Actions secret. Never copy the broad workstation token or weaken the proof. The agent can rerun CI.

Existing merge authorization requires **hosted green first**, five commits intact, branch deletion after merge, and the successful run URL in WAVE-134. Incorporate documentation-only main changes without rewriting those commits and verify the combined tree. No new permission question is needed for the already authorized merge.

[Fixed-commit CI runbook](https://github.com/mfreeze77/exais_vector_store/blob/b6f98e04f56e481903ce2e6109a24e15d32fd565/runbooks/ci-repair-post-8c7eecc.md). Independent report: /Users/mfrieson/Developer/exais-backups/ci-repair-20260914/fresh-qc/report.md.

## Vision and next delivery

The authoritative shared handoff is [A's PAUSE_AND_RESUME.md](https://github.com/mfreeze77/state-civics-ai/blob/main/docs/specs/civic-impact-intelligence/PAUSE_AND_RESUME.md), locally in sibling Statecivicsai/docs/specs/civic-impact-intelligence/. It records the full KS-594–624 vision, source/data hashes and the unresolved FY2025/FY2026 case selection.

| Ticket | Delivered boundary / remaining acceptance |
|---|---|
| WAVE-132 | Parent remains open: full real law → account → authority/actual observation chain unproved |
| WAVE-133 | Contract work landed; preserve provenance |
| WAVE-134 | Candidate ingestion delivered; CI repair pending; full publication/lifecycle acceptance open |
| WAVE-135 | Exact/lexical/semantic retrieval and bounded complete typed paths remain open |
| WAVE-136 | Held-out real-source benchmark remains open; three examples do not replace it |

Next product outcome: **one complete reviewed financial story**, before claims, forecasts, impact models or Workbench integration. A's action-account links, fiscal facts and crosswalks are empty. The FY2026 Guardianship dossier has a durable supplemental, base law present only as an external file, unquantified carryforward, component-only mapping and an incomplete spending snapshot. FY2025 has four quarter labels but no verified year-end control or authority chain. Final year selection was not confirmed before pause.

## Cleanup and recovery

Canonical A/B use one checkout/worktree each. Existing operator repositories are intentional plain Docker clones, not development roots. No linked worktrees may be created. Only the CI branch remains alongside B main after housekeeping. A's four historical stashes were inspected and preserved; useful runtime fixes are already incorporated or superseded.

Existing runtime/data/volumes were left in place. Backup root: /Users/mfrieson/Developer/exais-backups/. The civic-impact-pause-20260914 folder contains final Git receipt, complete-history bundles including A's four stashes, evidence archive and checksums. Bulk database/vector backups are in bulk-candidates-20260914. Qdrant restore has not been exercised. These data backups are on this Mac, not off-machine; GitHub contains code/docs, not corpus/database.

On resume inspect current Git/runtime state and the receipt, refresh existing operator clones to the reviewed SHA, and use retained-corpus preflights rather than remembered test counts. Documentation-only housekeeping does not close CI or product acceptance.
