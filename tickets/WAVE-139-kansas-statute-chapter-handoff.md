# WAVE-139: Verify the full statute export and chapter-by-chapter ingestion

Status: complete; independent QC PASS WITH NOTES. Owner: ExAIS. Dependency: WAVE-138. Parent: WAVE-132.

## Outcome and scope

The StateCivics manager delivered 85 chapter tranches at `ad6b38c0`. Verify the
complete input handoff and the existing consumer's partial-batch semantics,
then prove two small chapters can be applied and replayed in the existing local
Kansas store without removing earlier documents. This is the next bounded
rollout gate. Full-corpus application is a later operational stage; do not mark
28,812 documents indexed merely because their exports validate.

Use the existing local `ks-fiscal-local` cell and store
`vs_daafbc5d7aa54b23b3f10392`. No new application deployment, OVH workspace,
upstream mutation, global provider/default change or canonical graph activation.

## Read first / prior art

- WAVE-137/138 and their proof/QC; existing Kansas Statutes source package.
- `scripts/release/kansas-fiscal-document-ingest.py`: load_manifest,
  load_state, plan_operations, apply_operations, submit_upsert. Planning iterates
  incoming records only; omitted prior records currently have no operation.
- `tests/test_kansas_statute_ingest.py` and the fiscal runner test helpers.
- `statecivics_statutes.py`: pinned full harvest and exact-coordinate parser.
- Read-only upstream registrar/exporter changes at `63ae57b9`, export README
  and `chapters/INDEX.json`. Do not interpret substring-related display labels
  as canonical legal identity; source URL/key, revision and content remain distinct.

## Inputs and ownership

Exports: `/Users/mfrieson/Developer/statecivics-statute-exports/chapters/`.
INDEX SHA-256: `65d2424709bb1e54ab7fad9142ceffb6c00f961d463ca78b5dc7c277194f63e0`.
Retained harvest SHA-256:
`17bed3eec5f0946de1e2f5126b84b8637d9aa4b910199f98fe4c9f3e3eb207a2`.
The original six-record export remains pinned and unchanged.

One proof worker owns `tests/test_kansas_statute_tranches.py` and
`.tranche/statecivics-semantic-graph/aligned/wave-139-tranche-proof.md` / `.json`.
Root owns input audit orchestration, this ticket, indexes and source/operator
docs. Runtime source changes are not assigned: report a demonstrated defect
before altering behavior. Independent final QC follows all implementation.

## Acceptance

- Verify all 85 tranche pins/counts, 31,079 unique document records and exact
  custody/corpus joins. Reconcile 28,812 indexable documents, 2,267 exclusions,
  83,258 chunks and unresolved History metadata, with honest measured scope.
- Characterize the actual planner/apply boundary using retained chapter rows:
  chapter A then B with shared prior state must preserve every omitted A/canary
  entry and emit no omission DELETE. Replay B must be unchanged. Separately
  prove an explicit lifecycle removal removes only its named document, with
  altered removal records labeled test-only and never sent to the live API.
- Prove a new exporter commit/record digest with unchanged canonical source
  revision/hash can be accepted without manufacturing a new logical identity.
  State and server dedupe behavior must be distinguished.
- Real mounts are required for proof tests; no skipped success. Keep any API
  doubles explicit and separate from the subsequent real cell check.
- After the input audit passes, stage chapters 007 and 011 (14 total records,
  11 substantive documents, 37 chunks), using the existing runner and provider.
  Preserve the four-document/62-chunk canary. Reuse copied canary state in a
  durable operator directory outside every checkout, with serialized writers.
  Check the first chapter's document/version/chunk/vector identities survive
  the second, and replay makes no new vectors or embedding requests.
- Verify exact slices and real semantic recall for both new chapters; preserve
  fiscal inventory and application/infra configuration. Keep graph disabled.
- Record the measured stage result, remaining totals and rollout constraints.
  Chunk totals are not request or billable-token totals; any cost estimate must
  label token assumptions and use the published Voyage rate with a source.
- Independent QC PASS/PASS WITH NOTES before completion and further rollout.

## Result

[Implementation proof](../.tranche/statecivics-semantic-graph/aligned/wave-139-tranche-proof.md)
and [independent QC](../.tranche/statecivics-semantic-graph/aligned/wave-139-tranche-qc.md):
39 tests passed without skips; both chapters applied and replayed; 15 documents /
99 chunks verified, prior index/fiscal/runtime preserved. WAVE-140 owns the
remaining full-corpus rollout; canonical GraphRAG remains separate.
