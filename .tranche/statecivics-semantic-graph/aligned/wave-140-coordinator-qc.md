# WAVE-140 independent coordinator QC

Decision: PASS WITH NOTES

Reviewed 2026-09-11. This is the **pre-activation coordinator gate only**.
The user-authorized full local rollout may start with the reviewed frozen
coordinator and prepared command. WAVE-140 is not complete; full live verification
and independent final QC remain required.

Ticket reviewed:

- `tickets/WAVE-140-kansas-statute-full-rollout.md`, WAVE-139 acceptance,
  `build-contract.json` → `statute_full_rollout_increment`.

Evidence reviewed:

- `scripts/release/kansas-statute-rollout.py` and
  `tests/test_kansas_statute_rollout.py`; existing consumer manifest, state,
  planning, preview/upsert, idempotency and atomic-write helpers; existing
  caller/store-visibility helper.
- All source declaration, README, tracker and build/index diffs; coordinator
  implementation proof/JSON; immutable plan, test and launch artifacts under
  `/Users/mfrieson/Developer/statecivics-statute-ingestion/wave-140/`.
- Root's frozen seven-query recall-case file is future final-verification input,
  not a claim of completed full-corpus recall. Root's separate streaming live
  verifier remains subject to the final live proof/QC gate.

Acceptance criteria for this gate:

- [pass] **Bounded existing path.** The new script imports the existing
  document consumer rather than implementing a second ingestion path. It uses
  normal visibility, preview and synchronous ingest calls with store creation
  disabled. Store/cell/KB are fixed to the accepted Kansas target; caller
  tenant/business must match. No API, provider, schema or deployed service code
  was changed.
- [pass] **Whole delivery preflight before effects.** Exact approved INDEX,
  harvest and 20-record seed hashes are required. All chapter paths, file
  hashes/sizes/counts, scope fields, custody namespaces and globally unique
  logical/revision/export IDs are checked. The loaded manifests and exact
  custody/harvest joins are reconciled to actual per-chapter classification,
  chunk and character totals. Letter-suffixed chapters remain represented.
  Unexpected removal operations reject the rollout.
- [pass] **Measured plan.** The retained standalone plan ran in the pinned
  deployed image with network disabled and reports 85 chapters / 31,079 records,
  28,812 indexable documents / 83,258 chunks, 28,801 upserts, 2,278 noops and zero
  removals. The upsert count includes four existing canary exporter-digest
  refreshes; it is not a new-document count. QC independently reproduced full
  preparation through the focused suite's real-input fixture.
- [pass] **Seed partition and omission preservation.** The 20-record seed is
  hash-pinned and unchanged, with every identity assigned to its actual chapter.
  Existing chapter state must belong to this store/chapter and retain seeded
  identities. Only incoming records are planned; omitted chapters/identities
  are not deleted. WAVE-139's accepted tests separately distinguish omission
  from explicit lifecycle removal; this fixed-input rollout refuses removals.
- [pass] **Serial resumability.** An exclusive process lock covers preparation
  and application. Each record uses the existing stable idempotency key and
  atomic state writer before the next operation. Separate attempt/progress
  records retain counts and active chapter/document. Tests demonstrate loss of
  an accepted response, preserved prior state, reuse of the same idempotency
  key after restart, completed-record replay without HTTP calls, and lock
  exclusion. Recovery tests explicitly use isolated HTTP doubles; actual
  source-level/server dedupe evidence remains the accepted WAVE-139 proof.
- [pass] **Stop/failure behavior.** Apply-loop failures checkpoint failed status,
  exact chapter/document and sanitized exception type, then exit nonzero.
  SIGTERM/SIGINT request a stop before the next record operation; preflight
  SIGTERM prevents apply. There is no coordinator retry loop. A forced kill
  remains recoverable through persisted state plus server idempotency/dedupe.
- [pass] **Durable launch.** The prepared, unexecuted command uses the existing
  local Docker network and immutable API image
  `sha256:e7271b65b0554f29c5378a0f39a9a2e5e3e4f46fc710138328ef4cf8515627c5`,
  which is still the healthy running API image. A hash-named frozen coordinator
  is mounted read-only, byte-identical to the reviewed source:
  `80923ec4623a39a49634e15c844baf01341d360f30393fa26e72ef055756c3b1`.
  Export/corpus/custody/seed mounts are read-only; only the durable operator
  directory is writable. Explicit Kansas tenant/business/admin values are
  supplied. The named detached container is retained for identical-command
  stop/resume; no Docker socket, provider credential or application-replacement
  operation appears in the launch command.
- [pass] **Resume pins.** `inputs.lock.json` binds input, seed, target and loaded
  coordinator/consumer/parser/chunker/common hashes, plus the required image
  identifier. Resume rejects pin drift. The image requirement is actually
  selected by the reviewed Docker command; the Python constant alone is not
  runtime attestation of an arbitrary invocation.
- [pass] **Independent tests and artifact integrity.** QC reran the focused
  suite with all required real mounts and network disabled: **22 passed in
  26.38 seconds**. Parsed JUnit confirms 22 executed and zero skipped/errors/
  failures. Coverage includes wrong hashes, scope, paths/symlinks, counts,
  duplicate IDs, seed identities, changed resume pins, unsafe output locations,
  lock conflict, CLI failures and recovery. All ten hash-listed operational
  artifacts recompute exactly; frozen source equals the current source and
  original seed bytes still match. `git diff --check` passes.
- [pass] **Honest live boundary.** At review, the planned bulk container does
  not exist, chapter output state and application input lock do not exist,
  and launch metadata still says unexecuted. The accepted current inventory
  remains 15 documents / 99 chunks; expected full totals are kept separate.
  Graph and production readiness remain disabled. This review issued no API
  ingestion/query or provider calls and did not repeat the future live verifier.

Findings:

- No blocking coordinator defect found.
- Stop granularity is a **record operation**, not each individual HTTP call.
  A record already started may complete both its preview and ingest before
  stopping. A forced stop during that operation relies on existing idempotency
  for resume; progress and actual container exit state must both be inspected.
- Startup/preflight failures exit nonzero with a sanitized exception type.
  Exact active chapter/document fields are recorded once execution enters the
  guarded apply loop. A preflight rejection can leave an older progress file;
  that file alone is not proof the new attempt ran or completed.
- The broad canonical graph, legal-effectiveness and future-input label-guard
  issues remain separate. Full-rollout counts, all actual vectors/source
  bindings, no extra versions from reexports, fiscal/runtime preservation and
  frozen-query recall must be measured after application. This gate does not
  substitute offline tests for those live requirements.

Required fixes before activation:

- None. Root may commit the reviewed coordinator/proof and launch the exact
  frozen command under the existing authorization. Preserve the frozen source,
  inputs, seed, state, command and attempt history. Any coordinator change
  requires updated pins and review before launch. Do not mark WAVE-140 complete
  until its independent final live gate passes.

## Independent reproduction

QC ran the implementation's test command with read-only `/work`, exports,
statutes, custody and WAVE-139 seed mounts, the immutable image above,
`--network none --memory 2g --cpus 2`, and required variables:

```text
SVS_STATUTE_EXPORT_ROOT=/exports
SVS_STATUTE_CORPUS_ROOT=/statutes
SVS_STATUTE_CUSTODY_ROOT=/custody
SVS_STATUTE_ROLLOUT_SEED=/rollout-seed.json
```

The test invocation was `pytest -q -rs --tb=short -p no:cacheprovider
--junit-xml=/tmp/qc.xml tests/test_kansas_statute_rollout.py`; the XML was parsed
inside the disposable container before successful exit. Its temporary files
were not written into retained proof or operator state.

Separate read-only metadata checks recomputed every listed artifact hash/size,
compared the frozen coordinator to current source, inspected launch argv/mounts/
scope, checked the actual current API image/health, verified the seed hash and
absence of a launched bulk container or partition state, and read the full
standalone plan. Only this QC report was written by the reviewer.
