# WAVE-141: Pace the full statute importer within the existing API limit

Status: complete; independent QC PASS WITH NOTES. Owner: ExAIS. Dependency: WAVE-140 coordinator accepted at
`eb1d181` (WAVE-140 live rollout paused on this operational defect).

## Trigger and outcome

The authorized full rollout reached 575 checkpointed records, then the local
API returned 429 for `documents.ingest`: the configured limit is 120 requests per
minute and the matching window held exactly 120. K.S.A. 3-319 has no persisted
row; the rejection preceded ingestion/provider effects. The coordinator exited 2,
preserving chapters 001/002 and partial 003. No automatic retry ran.

Add a small, deterministic caller pacer to the existing coordinator so the full
corpus can finish against the unchanged API policy. Vectorization cost is not a
gate. Do not alter application limits, authentication, provider selection, API,
worker, database, indexing semantics, source bytes or the deployed image.

## Read and reuse

- WAVE-140 ticket, coordinator/tests/proof/QC and its frozen operator command.
- `scripts/release/kansas-statute-rollout.py`: serial apply loop, checkpoint,
  signals, code pins, chapter state, and guarded output paths.
- Existing `consumer.apply_operations` remains the sole ingestion path.
- Actual failure artifacts under durable `wave-140/rollout` and worker log proof.

## Scope and acceptance

- Pace only upsert record operations using monotonic time, at a conservative
  ceiling of 110 per minute. Count exporter refreshes too. Preserve sequential
  preview + ingest operations and all existing mandatory checks.
- Do not wait after noops or infer any removals. No unbounded retry loop.
- Check stop requests during pacing; no new operation may start after a stop.
  Long completed requests must not cause catch-up bursts. First operation may
  run immediately after the already-expired failed window and full preflight.
- Persist the pacing policy in the consumer/input lock and proof. Existing old
  locks must still refuse a changed coordinator; do not relax that comparison.
- Extend tests using controlled monotonic time/sleep and real retained operations
  for short bursts, slow requests, noops, stopped waits, and replay. Run existing
  coordinator recovery/scope tests with zero skips. API doubles remain explicit.
- Prepare a reviewed checkpoint transfer into a **new** durable operator root
  `wave-140/rollout-paced`, preserving the failed run unchanged. Copy chapter
  state bytes exactly, with a transfer manifest binding the old inputs lock,
  progress, per-file hashes, old/new coordinator hashes and unchanged inputs.
  Validate chapter states using the new coordinator and verify every transferred
  file hash before activation. The original W139 seed remains unchanged.
- The fresh root is an explicit, reviewed consumer upgrade over retained state;
  it must never be described as identical-command resume. Subsequent resumes
  use the new frozen command and its own unchanged pins normally.
- Independent QC before any activation. After PASS, WAVE-140 owns starting the
  paced job and proving the previously rejected document, retained identities
  and new chapter progress. This ticket completes the caller fix, not full
  corpus indexing. Full live completion remains WAVE-140's final gate.

## Ownership

The same one worker owns the coordinator, its existing test file and compact
`wave-141-pacing-proof.md` / `.json` under the aligned proof directory. Root owns
this ticket, indexes and operator/source documentation. No other runtime code
changes are assigned. Do not launch while implementing or reviewing this fix.

## Result

[Implementation proof](../.tranche/statecivics-semantic-graph/aligned/wave-141-pacing-proof.md)
and [independent QC](../.tranche/statecivics-semantic-graph/aligned/wave-141-pacing-qc.md)
accept the caller pacing and exact checkpoint transfer. Independent tests: 27
passed, zero skips. WAVE-140 owns paced activation and full live completion.
