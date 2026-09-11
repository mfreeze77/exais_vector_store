# WAVE-140 coordinator proof — QC accepted, bulk launch pending

The coordinator is implemented and verified. **No full-corpus application has
started.** This proof accepts neither live rollout completion nor GraphRAG
readiness. [Independent coordinator QC](wave-140-coordinator-qc.md) passed with notes before activation; final live
verification and QC remain later requirements of WAVE-140.

Changed files: `scripts/release/kansas-statute-rollout.py`,
`tests/test_kansas_statute_rollout.py`, this proof and its
[compact JSON companion](wave-140-rollout-proof.json). No existing consumer,
provider, API, schema, index or deployment behavior was changed.

## What the coordinator does

It imports the existing fiscal/statute document consumer and uses its unchanged
manifest, custody, planning, preview/ingestion, idempotency and state helpers.
It validates the approved INDEX hash, all 85 chapter hashes/counts, source scope,
unique logical/revision/export IDs, exact official chapter URLs and custody joins
before any API effects. The full harvest is preflighted once per process, and
actual classifications/chunk totals are reconciled against every chapter entry.
Letter-suffixed chapters such as `016a` are retained.

The target is limited to the approved existing local cell/store/KB. Before apply,
the existing store visibility check runs with explicit Kansas tenant/business
headers and creation disabled. The required immutable API image and hashes of
the loaded coordinator/consumer/parser/chunker/common files are recorded. Resume
rejects changed input, seed, consumer, target or image-requirement pins.

State is partitioned by chapter under the durable operator directory. The
20-record WAVE-139 seed remains separate and unchanged; all its identities are
assigned to their actual chapter. Omitted records never imply a withdrawal.
One exclusive lock protects the rollout. Each operation calls the existing
`apply_operations` with one record, so its atomic state write checkpoints progress
before the next request. `progress.json` and separate attempt records retain the
active chapter, logical document, counts and sanitized error type once apply
enters its guarded loop. Startup/preflight rejection reports nonzero status and
a sanitized error type before that chapter progress exists. No API response
body, secret or source text is copied into progress.

A failure stops immediately with nonzero status. SIGTERM/SIGINT stops between record operations; a record already underway may
finish both its preview and ingestion requests before stopping. Restart uses the same state
and stable idempotency keys; it does not contain an automatic retry loop. If a
response is lost after acceptance, server idempotency/dedupe remains authoritative.

## Executed proof

The standalone plan ran in the immutable deployed API image with the coordinator
mounted read-only, all inputs mounted read-only, and **network disabled**. Exit 0
in **26.51 seconds**:

| Measurement | Result |
| --- | ---: |
| Chapter tranches | 85 |
| Validated export records / custody joins | 31,079 |
| Indexable documents | 28,812 |
| Expected chunks | 83,258 |
| Seed records partitioned in memory | 20 |
| Planned upserts | 28,801 |
| Planned noops | 2,278 |
| Planned removals | 0 |
| API/provider calls | 0 |

The 28,801 upserts include four existing canaries whose exporter metadata/digest
changed; they are not four new document identities. New documents still pending
are 28,797. The plan wrote only its compact proof and lock; no chapter state,
application pin lock or live API effect occurred.

**22 focused tests passed, zero skips, 26.77 seconds.** The suite requires real
export, corpus, custody and WAVE-139 seed mounts and fails if any is missing.
Its recovery tests use explicitly isolated HTTP doubles. Coverage includes:

- Complete real input preparation and exact 20-record seed partition.
- Lost response after server acceptance, stable-key resume, retained completed
  records, and subsequent replay without HTTP calls.
- Graceful stop and preservation of an omitted chapter's state.
- Exclusive lock contention and CLI SIGTERM/nonzero failure behavior.
- Wrong INDEX hash, path, symlink, chapter hash/count/scope, duplicate IDs and
  mismatched chapter; wrong seed/scope/identity; resume-pin drift; unsafe output
  overlap with inputs or a checkout.

The focused command used the same immutable image and mounts as the standalone
plan, with a read-only `/work` checkout and these required test variables:
`SVS_STATUTE_EXPORT_ROOT=/exports`, `SVS_STATUTE_CORPUS_ROOT=/statutes`,
`SVS_STATUTE_CUSTODY_ROOT=/custody`, and
`SVS_STATUTE_ROLLOUT_SEED=/rollout-seed.json`. It ran:

```sh
python -m pytest -q -rs --tb=short -p no:cacheprovider \
  --junit-xml=/proof/coordinator-tests.xml tests/test_kansas_statute_rollout.py
```

The exact complete Docker argv, stdout, JUnit XML, timings and standalone plan
are retained under
`/Users/mfrieson/Developer/statecivics-statute-ingestion/wave-140/`.
Their paths/hashes and the actual loaded consumer pins appear in the JSON proof.
`git diff --check` passes. No source bytes or large responses were added to Git.

## Reviewed launch and recovery commands

The operational root is
`/Users/mfrieson/Developer/statecivics-statute-ingestion/wave-140/rollout`.
`coordinator-launch-command.json` in its parent is **prepared, not executed**.
It selects the immutable existing API image, a hash-named frozen coordinator
mounted at `/app/scripts/release/kansas-statute-rollout.py`, the existing local
Docker network, explicit Kansas headers, read-only input mounts and `--apply`.
It names the container `exais-kansas-statute-rollout-wave140`; no application
container is replaced. The coordinator CLI is:

```sh
python scripts/release/kansas-statute-rollout.py \
  --index /exports/chapters/INDEX.json \
  --index-sha256 65d2424709bb1e54ab7fad9142ceffb6c00f961d463ca78b5dc7c277194f63e0 \
  --harvest-manifest /statutes/manifests/statute_scrape_20260911_030653.json \
  --harvest-manifest-sha256 17bed3eec5f0946de1e2f5126b84b8637d9aa4b910199f98fe4c9f3e3eb207a2 \
  --harvest-root /statutes --custody-root /custody \
  --seed-state /seed.json \
  --seed-state-sha256 b64003f370c161c45c6dc5384951ea787242cba56be6446b12327099755d5c2d \
  --operator-root /operator/rollout --api http://api:8080
```

Default is plan-only. After QC, the prepared named-container command adds
`--apply`. Monitor `rollout/progress.json` for per-record progress and inspect the
named container; process status and progress must both be considered. During
initial preflight there is no active chapter yet. Stop and resume commands:

```sh
docker inspect --format '{{.State.Status}}' exais-kansas-statute-rollout-wave140
docker stop --time 1800 exais-kansas-statute-rollout-wave140
docker start exais-kansas-statute-rollout-wave140
```

The stop timeout matches the bounded 1,800-second request timeout; a forced kill
still relies on already persisted state plus server idempotency when restarted.
Keep the container and its frozen mounts for identical-command resume. Do not
change pins or erase state to bypass a reported failure.

## Remaining gates

Coordinator QC has passed. Launch/monitoring, all 28,812 live documents / 83,258 chunks,
per-chapter and exclusion checks, all exact source bindings, prior-version/vector
preservation, fiscal/runtime preservation, dense recall and final live QC remain
required. Root owns the separate bounded streaming live verifier. Current
15-document/99-chunk inventory is the WAVE-139 accepted baseline; this coordinator
phase has made no live mutation. Graph creation and legal-effectiveness findings
remain separate work.
