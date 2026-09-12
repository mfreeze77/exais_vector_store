# WAVE-141 independent pacing and transfer QC

Decision: PASS WITH NOTES

Reviewed 2026-09-11. This accepts the caller pacing fix and the prepared explicit
checkpoint upgrade. The paced command may be activated under WAVE-140 after
root records this gate. It does not establish full-corpus indexing or successful
live continuation past the original 429.

Ticket reviewed:

- `tickets/WAVE-141-kansas-statute-rollout-pacing.md`, WAVE-140 and its accepted
  coordinator gate, build-contract/index ownership and current paused-run proof.

Evidence reviewed:

- Exact coordinator/test diffs, WAVE-141 proof/JSON, root's source/operator/
  ticket updates and corrected historical-versus-current WAVE-140 inventory.
- Retained old failed root, new `rollout-paced` root, frozen coordinator,
  transfer script/manifest, old/new input locks, per-file state hashes, offline
  plan, test JUnit and prepared launch command.
- Independent 27-test rerun; direct read-only execution of the frozen module's
  state loading and old-lock rejection; artifact/transfer/launch checks; current
  Docker application/infrastructure configuration comparisons.

Acceptance criteria:

- [pass] **Bounded caller-only change.** Runtime diff adds a monotonic pacer,
  policy metadata and admission calls in the existing serial upsert loop. The
  existing consumer still owns preview, synchronous ingestion, idempotency and
  state writes. No service policy, API, worker, provider, schema or source
  behavior changed. Current application/infrastructure IDs, image IDs,
  environment fingerprints, mounts and ports match the WAVE-139 baseline.
- [pass] **Rate behavior.** One pacer spans all chapters in an apply attempt.
  Upsert starts are at least 0.55 seconds apart, with at most 110 starts in
  a 60-second interval under the controlled-clock test. Exporter refreshes
  count as upserts. Admission anchors to actual monotonic time, so slow
  operations create no catch-up credits. Noops/replay bypass waiting, and no
  automatic retry loop was added.
- [pass] **Stop handling.** Waits check the stop flag in steps no larger than
  0.1 seconds. The apply loop checks again before starting an operation. Tests
  prove a stop while waiting records stopped state and prevents a second
  preview/upsert. Previously accepted record-operation stop semantics remain:
  an operation already started may finish its sequential preview and ingest.
- [pass] **Policy/consumer pins remain strict.** Pacing policy is recorded in
  both input locks and progress. The old failed input lock is not relaxed or
  rewritten. Final QC executed the actual new frozen module against the real
  old root; `prepare` rejects it with `resume input/consumer/target pins changed`
  before API effects. New loaded module hashes/policy match the new lock exactly.
- [pass] **Exact checkpoint transfer.** All three files were independently
  compared byte for byte against the old root: chapter 001 has 26 records,
  002 has 456 and partial 003 has 93, totaling **575**. Their byte counts and
  hashes match both the transfer manifest and launch requirements. Old lock,
  failed progress and state hashes remain intact; the original WAVE-139 seed
  hash is unchanged. The real new state loader validates all transferred records
  against approved chapter membership and seeded identities.
- [pass] **Explicit upgrade lineage.** The transfer binds old/new coordinator
  hashes, old container, input/progress/state hashes, unchanged source/seed/
  target pins, unchanged consumer helper hashes, new policy, new plan and new
  strict lock. Only coordinator and pacing-policy pins differ. This is correctly
  labeled a reviewed consumer upgrade, not identical-command resume. The old
  container remains exited with code 2; the new paced container does not exist.
- [pass] **Prepared launch.** The frozen coordinator is byte-identical to reviewed
  source, SHA-256
  `3fd29bddec86366a5d5fb002558ab84bdf7c42c97d28596fc369b516bc5b1580`.
  The command keeps the same immutable API image, Kansas network/target/scope
  and read-only inputs/seed, and selects `/operator/rollout-paced` for output.
  It includes transfer/new-lock/per-state hashes for pre-launch checking and
  remains marked unexecuted. The existing old-root command is preserved.
- [pass] **Actual proof and independent rerun.** QC reran all focused tests in
  the immutable network-disabled API image with real required mounts:
  **27 passed in 26.23 seconds**. JUnit has 27 executed and zero skipped/errors/
  failures. All existing preparation, scope, interruption, lost-response,
  stable-key replay and lock cases still pass. All **13** hash-listed WAVE-141
  artifacts recompute exactly. The independent module check made zero API calls.
  `git diff --check` passes.
- [pass] **Remaining work stated honestly.** The retained new full plan reports
  28,235 upserts / 2,844 noops / zero removals; two upserts are remaining exporter
  refreshes. Current paused inventory is root-verified **579 documents / 1,518
  chunks/vectors**, not the historical 15/99 stage baseline. Its preservation
  snapshot hash was independently rechecked. No complete live-run claim follows
  from pacing tests or an offline plan.

Findings:

- No blocking code or transfer defect found.
- QC caught stale wording in WAVE-140 that described the stopped run as
  applying and retained a misleading `current_live_inventory_unchanged` name
  for the 15/99 historical baseline. Root corrected both before acceptance;
  final text explicitly names the failed run and actual paused 579/1,518 proof.
- Pacing limits this coordinator's operation starts; it is not a reservation
  of a shared API bucket or a guarantee against every future 429/provider error.
  Preserve existing fail-stop behavior and monitor actual progress/status.
- WAVE-140 must verify live continuation past 3-319, preservation of all paused
  identities/vector hashes, full counts/exclusions/source evidence, dense recall
  and final live QC. This pacing gate does not pre-accept those results.

Required fixes before activation:

- None. Root may complete WAVE-141, commit the reviewed source/proof and activate
  the prepared paced command under WAVE-140. Recheck its recorded transfer/state/
  lock hashes immediately before launch and preserve the old failed root.
  Subsequent resumes use the new frozen command and unchanged new pins.

## Reproduction and reviewer boundaries

QC used immutable image
`sha256:e7271b65b0554f29c5378a0f39a9a2e5e3e4f46fc710138328ef4cf8515627c5`
with `--network none --memory 2g --cpus 2`, the implementation's required
read-only checkout/exports/statutes/custody/WAVE-139-seed mounts and environment.
It ran `pytest -q -rs --tb=short -p no:cacheprovider
--junit-xml=/tmp/qc.xml tests/test_kansas_statute_rollout.py`, parsing JUnit inside
the disposable container before successful exit. Temporary test files remained
inside that container; no retained state or proof was overwritten.

A separate container loaded the actual hash-frozen coordinator at its intended
`/app/scripts/release/kansas-statute-rollout.py` path with all operator/input
mounts read-only. It executed `load_index`, `partition_seed`, `chapter_state` for
every chapter, compared `code_pins()`/policy against the new lock, then invoked
`prepare` on the old root and required the exact pin-drift refusal. It did not
repeat a second full custody audit or run apply.

Host metadata checks independently recomputed all artifact/transfer/state/seed
hashes, compared old/new pin dictionaries, inspected the launch argv and frozen
source bytes, confirmed old exited/new absent containers and compared current
service configuration fingerprints. No live API, provider or ingestion call
was issued. Only this QC report was written by the reviewer.
