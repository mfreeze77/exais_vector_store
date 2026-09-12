# WAVE-141 pacing and checkpoint-transfer proof

Implementation and [independent QC](wave-141-pacing-qc.md) passed with notes. **The paced job has not been
launched.** WAVE-140 remains paused at its recorded local API 429. This ticket
adds caller pacing and prepares an explicit checkpoint transfer; it does not
claim full-corpus indexing or change the API's existing 120/minute policy.

Only `scripts/release/kansas-statute-rollout.py`, its existing test file and these
proof files changed. The consumer's preview/ingest/state path, deployed images,
provider selection, API limits, authentication, database and source bytes are
unchanged.

## Pacing behavior

A single monotonic pacer spans the serial upsert loop across chapters. It spaces
upsert starts by at least **0.55 seconds**, conservatively limiting them to at
most **110 per minute**. Exporter refreshes count as upserts. Noops do not wait.
A slow operation does not accumulate burst credits: the next admission anchors
to actual monotonic time. There is no retry loop.

Waits check the existing stop flag at intervals no larger than 0.1 seconds, and
the caller rechecks immediately before beginning an operation. A record already
started still uses the existing sequential preview + ingest path. Pacing policy
is included in both the strict input/consumer lock and progress proof. Existing
old-lock equality is unchanged: the old failed root rejects this coordinator
rather than silently adopting new code.

**27 tests passed, zero skips, 27.64 seconds.** Tests use required retained inputs
and explicit isolated HTTP doubles. Controlled-clock additions verify the burst
ceiling, no catch-up after slow work, stopped waits, absence of a second preview
after stop, no waiting on noops/replay and strict rejection of the old lock. All
previous full-input, scope, interruption, stable-key recovery and replay tests
also pass. `git diff --check` passes.

## Exact checkpoint transfer

The old container is exited with code 2. With its lock held read-only, preparation
verified the recorded old lock/progress/state hashes and copied **575 records in
three chapter-state files** byte-for-byte to:

`/Users/mfrieson/Developer/statecivics-statute-ingestion/wave-140/rollout-paced/`

The old `rollout/` files and WAVE-139 seed were not changed. Old chapters 001/002
are complete; chapter 003 contains 93 checkpointed records. Each copied file was
rehashed against its source before the new plan. The transfer manifest binds the
old input lock, failed progress, all state file hashes, old/new coordinator hashes,
unchanged input and consumer-file pins, new pacing policy and new input lock.

Old coordinator:
`80923ec4623a39a49634e15c844baf01341d360f30393fa26e72ef055756c3b1`.
New coordinator:
`3fd29bddec86366a5d5fb002558ab84bdf7c42c97d28596fc369b516bc5b1580`.

This is an **explicit consumer upgrade over retained checkpoints**, not an
identical-command resume. The new root has its own strict pinned lock. Subsequent
resumes use the new frozen command normally. The immutable preparation manifest
and command still mark activation as pending; eventual actual launch must be
recorded separately after QC.

The new frozen coordinator's standalone plan ran in the unchanged immutable API
image with networking disabled. It validated every copied chapter state through
the real coordinator, then reverified all 85 manifests and custody/harvest joins:
**31,079 records / 28,812 indexable documents / 83,258 chunks**, exit 0, zero API
calls. Remaining operations: **28,235 upserts, 2,844 noops, zero removals**.
Two upserts are remaining exporter-digest refreshes, so new documents still pending
are 28,233. Root's separate paused live verifier records 579 documents / 1,518
chunks and retains all their identities/vector hashes for post-resume comparison.

## Reproduction and next gate

Exact Docker argv, JUnit XML, output, elapsed time, transfer script/manifest,
full offline plan and frozen source are outside Git under durable `wave-140/`.
Their full paths/hashes appear in [the JSON proof](wave-141-pacing-proof.json).
The test command reuses the WAVE-140 required mounts/environment and executes:

```sh
python -m pytest -q -rs --tb=short -p no:cacheprovider \
  --junit-xml=/proof/pacing-tests.xml tests/test_kansas_statute_rollout.py
```

`paced-plan-command.json` records the executed offline full plan.
`paced-launch-command.json` is prepared but **not executed**. It uses the existing
Kansas network/image, the new hash-frozen coordinator, the unchanged read-only
inputs/seed and the new `rollout-paced` output root. It names
`exais-kansas-statute-rollout-wave140-paced` and records the exact transfer hashes
that must still match before activation. No application deployment is needed.

Independent QC passed before activation; WAVE-140 may now start this command. WAVE-140 then owns
monitoring, proving the previously rejected 3-319 document, retaining all paused
579-document/1,518-vector identities, full live verification and final QC. The
old failed container, state and proof remain intact throughout.
