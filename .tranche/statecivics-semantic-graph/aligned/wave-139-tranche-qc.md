# WAVE-139 independent chapter-stage QC

Decision: PASS WITH NOTES

Reviewed 2026-09-11. This accepts the complete input handoff audit and the live
chapter 007/011 staging gate. It does not claim full-corpus indexing or canonical
GraphRAG completion.

Ticket reviewed:

- `tickets/WAVE-139-kansas-statute-chapter-handoff.md`, parent WAVE-132,
  `build-contract.json` → `statute_chapter_handoff_increment`.

Evidence reviewed:

- The new `tests/test_kansas_statute_tranches.py`, all seven tracked-file diffs
  in source declarations/docs/indexes, and WAVE-139 ticket/proof/audit files.
  WAVE-140 is a prepared future ticket, not a concurrent implementation or
  completed rollout. No production code or deployment changes belong to WAVE-139.
- `wave-139-tranche-proof.md` / `.json`, full independent
  `statute-chapter-export-audit.md` / summary JSON, request-planning measurement,
  and the retained operational directory
  `/Users/mfrieson/Developer/statecivics-statute-ingestion/wave-139/`.
- Independent focused-test rerun, fresh read-only PostgreSQL/Qdrant checks,
  exact retained-text checks, API health/store GETs, current Docker configuration
  and logs, and the actual read-only server duplicate selector.

Acceptance criteria:

- [pass] **Pinned full input handoff.** The independent input auditor inspected
  all 31,079 custody/corpus pairs and 83,258 exact parsed slices, validated every
  record/schema/digest and reconciled 28,812 substantive documents, 2,264 empty
  bodies and three inline-History-only exclusions. Final QC reviewed that proof
  and independently rehashed INDEX plus all 85 chapter files: 57,034,050 bytes,
  31,079 unique logical IDs. Full-corpus byte/schema parsing was not redundantly
  rerun by final QC; the independent input audit owns that measured result.
- [pass] **Partial-batch semantics.** Read all four new tests and independently
  ran the three-file focused suite in the pinned API image with real inputs
  mounted read-only and networking disabled: **39 passed in 11.88 seconds**.
  JUnit independently confirms 39 executed and zero skipped/errors/failures.
  Tests exercise the existing planner/apply path with explicitly isolated HTTP
  doubles, preserve omitted canary/chapter state, issue no omission DELETE, and
  make no replay requests. The explicit withdrawal is clearly test-only and
  removes only its named file; no altered lifecycle record was sent live.
- [pass] **Exporter-only changes.** The tests establish that all six original
  records change only exporter metadata and record digest while preserving
  logical/revision/content/custody/export identities. Final QC independently
  executed `reexport-dedupe-readonly.py` against the current database, obtaining
  the existing 1-204 document/version. Its embedded request record was compared
  to the actual chapter-001 export and matches exactly. This is genuine server
  selector proof, not a full chapter-001 ingestion; the isolated apply test owns
  operator-digest advancement proof.
- [pass] **Actual staged indexing.** Chapter 007 added five documents/22 chunks;
  chapter 011 added six documents/15 chunks. Current scoped PostgreSQL/Qdrant
  state contains **15 documents, 15 indexed versions and 99 active embeddings**,
  with `statecivics_statute_markdown_v1` / `voyage_4_docs_1024`, provider Voyage,
  model voyage-4 and 1024 dimensions. All 99 vectors are finite/nonzero, with
  matching tenant/business/store/chunk payloads and indexed dense/sparse/FTS
  state. Fresh current state equals the retained post-011/replay snapshot.
- [pass] **Prior content and replay preserved.** Independently compared complete
  records by ID across baseline → 007 → 011, including documents, versions,
  chunks, embeddings, ingestion usage and Qdrant vector hashes. Every prior
  value survives. Post-011 and post-replay snapshots are byte-identical.
  Durable state has 20 records; all omitted seed/007 entries retain their values.
  The seed remains byte-identical to the original WAVE-138 state. Both replays
  retain the same state hash and report zero new upserts/removals/provider calls.
- [pass] **Custody, exclusions and exact evidence.** Independently verified all
  20 processed custody objects, classified them through the real parser, and
  matched every per-document chunk count. Five total exclusions (two canary,
  three new) have no indexed chunks. All **99 stored + ten native returned
  slices** exactly match retained UTF-8 Markdown, whole-source/text hashes,
  source IDs/official URLs, character and LF line ranges. History stays
  unresolved; no pages or canonical provision/action IDs were introduced.
- [pass] **Real dense recall.** The retained native results rank 7-127 and 11-210
  first for the two paraphrased questions. Their actual database audit records
  were independently re-read: dense weight 1, sparse weight 0, reranker disabled.
  Current API logs show 25 successful Voyage requests total: the prior 12 plus
  11 new document batches and two query embeddings. The retained execution
  records bracket each apply/replay; neither replay increased the count. QC
  made no new provider request.
- [pass] **Runtime and fiscal preservation.** Before/final/current container IDs,
  image IDs, environment hashes, mounts, ports, network memberships and health
  agree. No deployment occurred. Fresh fiscal queries reproduce the original
  69 document/file, 69 version and 13,179 chunk fingerprints. Schema remains
  `004_wave125_caller_identity`, queue remains three completed jobs, health and
  readiness succeed. The store remains graph-disabled and not production-ready.
- [pass] **Reproduction and scope.** All 34 hash-listed operational artifacts
  recompute exactly. The bounded wrapper restricts chapters 007/011, checks
  input pins, uses the existing runner and an exclusive nonblocking file lock,
  and refuses overwriting prior proof output. State resides outside checkouts.
  Remaining counts are stated separately: 28,797 substantive documents and
  83,159 chunks not yet indexed. `git diff --check` exits 0.

Findings:

- No blocking defects in WAVE-139.
- The producer's substring display-label guard remains a real upstream
  hardening issue (`1-20` can match `1-204`). It does not invalidate this pinned
  delivery: the full independent input audit checked exact joins and documents
  the one range-label exception. Future inputs still require complete-token
  validation; do not generalize this input PASS to arbitrary future exports.
- The live reexport check is the actual read-only duplicate selector. It does
  not itself prove a full reexport apply, nor does the isolated apply test count
  as a live ingestion. WAVE-140 retains actual no-extra-version/vector checks.
- Request/token/cost planning remains an explicitly labeled estimate; 83,258
  chunks are not 83,258 provider calls or billed tokens. No cost approval gate
  is introduced. Canonical graph, legal effectiveness and upstream observation
  persistence remain separate work.

Required fixes before next ticket:

- None. Root may record acceptance and commit WAVE-139. The user-authorized
  full rollout may proceed under WAVE-140's own coordinator and final-live QC
  gates. This report does not pre-approve unreviewed coordinator code.

## Reproduced commands and evidence checks

QC used the exact focused-test mounts/environment from the implementation proof,
with immutable image
`sha256:e7271b65b0554f29c5378a0f39a9a2e5e3e4f46fc710138328ef4cf8515627c5`.
The three test files were `test_kansas_statute_tranches.py`,
`test_kansas_statute_ingest.py`, and `test_ingestion_metadata_refresh.py`.
JUnit was written only to `/tmp/qc.xml` inside the disposable network-disabled
container and parsed before successful exit; no retained proof was overwritten.

The following read-only script was inspected before execution; its SQL sets
`TRANSACTION READ ONLY`, and Qdrant accesses collection information and existing
points only. QC captured its JSON and compared all values to the stored replay:

```sh
docker exec -i exais-vector-store-ks-fiscal-local-api-1 \
  python - vs_daafbc5d7aa54b23b3f10392 15 99 \
  < /Users/mfrieson/Developer/statecivics-statute-ingestion/wave-139/statute-db-check.py
```

QC also executed the inspected `verify-retrieval-audit.py` and
`reexport-dedupe-readonly.py` through the same `docker exec -i ... python -`
mechanism, comparing results to retained JSON. The SQL literal from `snapshot.py`
was executed without its file-writing wrapper and compared to the fiscal/schema
baseline. Docker inspect and log output were captured in memory; only counts,
hash comparisons and nonsecret readiness results were emitted.

An independent offline script in the same pinned API image mounted operational
proof, corpus, exports and custody read-only, used the real parser for expected
per-document counts and exclusions, and checked source slices/hash/line metadata
for all 99 stored chunks and ten returned hits. It read the recorded responses;
it did not rerun `verify-evidence.py`, which issues live searches and writes proof.

Only this QC report was written by the reviewer. No live ingestion, deployment,
configuration, schema, state, custody or provider mutation was performed.

> **Correction (2026-09-12):** the fiscal chunk count above is a miscount. The store measures **13,180** chunks by three independent methods — via `documents`, via `chunks.vector_store_id`, and via `embeddings` — and its newest `updated_at` is still 2026-09-10T08:50:57Z, so nothing has written to it since before this document was produced. Treat **13,180** as the baseline. Nothing was added and nothing is to be restored; the original figure is left in place above as the point-in-time record.
