# WAVE-140 rollout proof — complete

The reviewed WAVE-141 caller pacer passed independent QC and was committed at
`87fbe41`. The full rollout **completed 2026-09-11T22:34:29Z**, container exit 0,
`status: completed`, 85 of 85 chapters, in
`exais-kansas-statute-rollout-wave140-paced`, using the explicitly transferred
`rollout-paced` checkpoints and unchanged API image/limit. Transfer, frozen code,
seed and image hashes were reverified before launch and the image pin was
reverified after each of two API restarts. Final live verification and the
acceptance run are recorded below. Independent QC remains required; **GraphRAG
readiness is not claimed and production readiness is not claimed** — this is the
local cell only, `productionReady: false`, OVH unverified.

It took **nine attempts and eight replays**. Resume is idempotent: completed
chapters replay as `unchanged` in ~20s, and across all nine attempts not one
document acquired a second version.

## Final live verification

| | Expected | Actual |
|---|---:|---:|
| Indexable documents | 28,812 | **28,812** |
| Active chunks | 83,258 | **83,258** |
| Embeddings | == chunks | **83,258** |
| Document versions | == documents | **28,812** |
| Documents with >1 version | 0 | **0** |
| Per-chapter vs `INDEX.json` | exact | **all 85 exact** |

Qdrant **83,858** points in `svs_biz_ks_state_civics_voyage_4_docs_1024`. The
collection is **shared**: 83,258 statute + 600 fiscal (the fiscal store's other
12,580 chunks are in the openai collection). Comparing against statute chunks
alone reports a 600-point surplus that does not exist.

`indexed_vectors_count` 80,020, a stable 3,838 short. Structural, not loss:
`indexing_threshold` is 20,000, so a smaller segment is never HNSW-indexed and is
served by exact brute force — deterministic, and more accurate than HNSW. Nothing
in the search path sets `indexed_only`.

Fiscal inventory intact: 69 documents / 13,180 chunks, newest `updated_at` still
2026-09-10T08:50:57Z. The 2,267 non-indexable source records remain in custody.

## Acceptance — PASS

53 preregistered cases across 34 chapters, dense-only and unreranked (confirmed in
the audit events for all 53). **48 passed**, 38 at rank 1, 47 within rank 5.
**0 blocking** — every miss's expected document is present in the store. Five
non-blocking retrieval-quality findings, recorded with their top-three hits:
2-303, 12-520, 16-1909, 19-3309, 59-2118.

**530 returned slices re-verified against custody bytes** — content hash, source
revision id, citation URL, character span, line span, text hash and both
coordinate conventions re-derived. **0 verification failures.**

Case set sha256 `d0be6835…`, decision rule sha256 `cc50b632…`, both preregistered
before any result existed. No aggregate recall rate is published: 53 cases cannot
distinguish 90% from 96%.

The original attempt remains preserved: it checkpointed 575 records, completed
chapters 001/002, and exited 2 at K.S.A. 3-319 when the local API's 120/minute
counter returned HTTP 429. No automatic retry ran. WAVE-141 added caller pacing
and an independently reviewed checkpoint transfer, not an API-limit change.

Early paced checks pass: 3-319 now has one indexed version and two exact
retained-text chunks. A read-only comparison confirms every paused **579 document,
579 version, 1,518 chunk/embedding identity and vector fingerprint** is unchanged.
Three complete API minute windows held **84, 98 and 102 ingestion calls**, all
below the unchanged 120/minute limit; exact HTTP status matching found zero
ingestion 429s after paced launch. The remaining corpus is still being monitored.
`paced-live-launch.json` separately records actual execution of the immutable
reviewed `paced-launch-command.json`; its pre-launch artifact is not rewritten.

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

## Historical coordinator preparation proof

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

## Historical first-attempt launch and recovery commands

The operational root is
`/Users/mfrieson/Developer/statecivics-statute-ingestion/wave-140/rollout`.
`coordinator-launch-command.json` remains the immutable reviewed pre-launch
artifact. `live-launch.json` separately records its actual execution; the approved
command was not rewritten after launch.
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

Default is plan-only. The QC-approved named-container command used for this live
run adds `--apply`. Monitor `rollout/progress.json` for per-record progress and inspect the
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

Coordinator QC has passed and the first run launched, then fail-stopped at the
local API limit. WAVE-141 pacing review and activation are complete. Continued monitoring,
all 28,812 live documents / 83,258 chunks,
per-chapter and exclusion checks, all exact source bindings, prior-version/vector
preservation, fiscal/runtime preservation, dense recall and final live QC remain
required. Root owns the separate bounded streaming live verifier. WAVE-139
provided the historical 15-document/99-chunk baseline. After the first run stopped,
root verified the actual paused inventory: **579 documents, 579 indexed versions,
1,518 exact-source chunks and 1,518 Voyage-4/1024 vectors**. All initial identities
and vectors survived. The full paused snapshot is retained for comparison after
the paced run; no full-corpus completion is claimed. Graph creation and
legal-effectiveness findings remain separate work.

## Active paced operation

The active output root is durable `wave-140/rollout-paced/`. Monitor its
`progress.json` and container `exais-kansas-statute-rollout-wave140-paced`.
The earlier command examples describe the preserved original attempt. For the
active job, use the paced container name for inspect/stop/start. This activation
is an explicit reviewed consumer upgrade; subsequent resumes use the new frozen
command and unchanged pins. No full completion is claimed while it runs.
