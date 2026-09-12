# WAVE-140: Index the approved full Kansas statute corpus

Status: complete 2026-09-11T22:34:29Z; full corpus indexed and reconciled; acceptance PASS; final live QC below. Coordinator QC PASS WITH NOTES; original 575 checkpoints preserved. Dependency: WAVE-139 complete (ab86356, QC PASS WITH NOTES). Owner: ExAIS. Parent: WAVE-132.

## Outcome

The owner directs proceeding with the full corpus in the existing local Kansas
cell; vectorization cost is not a gate. Consume the 85 verified chapter exports
and finish with 28,812 indexable documents / 83,258 active chunks, preserving
the 2,267 non-indexable source records in custody and unresolved History evidence.
Use store `vs_daafbc5d7aa54b23b3f10392` in `ks-fiscal-local`; no new cell,
OVH preparation, deployment, provider default, migration or canonical graph.

## Read first / reuse

Read WAVE-139, its tests/proof/QC and full export audit, source package, existing
runner `load_manifest`, `load_state`, `plan_operations`, `apply_operations`,
`ensure_vector_store`, and `preflight_statute_harvest`. Existing API/provider
batching and source identity/dedupe remain authoritative. WAVE-138/139 capture
the live IDs, configuration and fiscal preservation baseline.

## Scope

- Add a small operational coordinator only if needed, reusing the existing
  Python runner functions. Do not create another ingestion/data path. Verify
  the required INDEX SHA-256, target, all chapter paths/hashes/counts and unique
  logical identities before live effects. Pin the unchanged harvest once.
- Use durable `/Users/mfrieson/Developer/statecivics-statute-ingestion/` state
  outside every checkout. Seed from the verified WAVE-139 state. Keep independent
  chapter state to avoid rewriting a 31,079-row state file after every document;
  preserve logical identity across the existing canaries and new chapter exports.
- Apply serially with an exclusive process lock, stable idempotency keys and
  atomic state/progress updates. Never infer removals from omitted identities.
  A failure stops the run with a nonzero status and exact failed chapter;
  completed documents remain resumable. Do not claim running/interrupted work
  complete. No untested parallel writes or unbounded retry loop.
- Retain immutable input/consumer pins, command, progress, error and final proof.
  Use the deployed API image and existing API, with no secrets in output.
  A long job may run in a named container with durable mounts, but must remain
  monitored and have a concrete stop/resume command.
- Verify existing exporter-only changes do not create extra document versions
  or vectors. Preserve the original six-record export and prior stage state.
- Final live verification: exact expected document/version/chunk counts and
  per-chapter counts, all dense/sparse statuses and source revision/hash bindings,
  scoped Qdrant points/model/dimensions, no indexed exclusions, intact fiscal
  inventory and application/infra state. Check exact stored text against custody
  and execute real dense recall across multiple chapters, retaining honest ranks.
- Record all completion/failure counts and remaining gaps; keep GraphRAG and
  production readiness separate. Finish with independent QC and source-lock,
  ticket/tracker and handoff updates. No source bytes or large responses in Git.

## File ownership and gates

One worker may own `scripts/release/kansas-statute-rollout.py` and
`tests/test_kansas_statute_rollout.py` if orchestration code is required, plus
`wave-140-rollout-proof.md` / compact `.json` under the aligned proof directory.
Root owns ticket/source/operator documentation. Characterize actual retained
inputs, interrupted resume, wrong index/path/hash/scope/duplicate IDs, lock
exclusion, seed partitioning and omission preservation before any new coordinator
is used live. Provider/API doubles must remain explicitly labeled.

Independent coordinator QC must pass before bulk activation if code is added;
final live QC must pass before the ticket is complete. Do not broaden API,
schema, transaction or provider code to improve throughput inside this ticket.
If a concrete service defect prevents completion, record it and isolate the
necessary fix rather than weakening evidence or silently skipping records.


## Result

Completed 2026-09-11T22:34:29Z, container exit 0, `status: completed`, 85 of 85
chapters, `removed: 0`. Nine attempts, eight replays.

### Final live verification

| | Expected | Actual |
|---|---:|---:|
| Indexable documents | 28,812 | **28,812** |
| Active chunks | 83,258 | **83,258** |
| Embeddings | == chunks | **83,258** |
| Document versions | == documents | **28,812** |
| Documents with >1 version | 0 | **0** |
| Documents without chunks | 0 | **0** |
| Chunks without an embedding | 0 | **0** |
| Per-chapter vs `INDEX.json` indexable_documents | exact | **all 85 exact** |

Qdrant: **83,858** points in `svs_biz_ks_state_civics_voyage_4_docs_1024`. That
collection is **shared** — 83,258 statute vectors plus 600 belonging to the
fiscal store, whose other 12,580 chunks live in the openai collection. Comparing
its `points_count` against statute chunks alone reports a 600-point surplus that
does not exist.

`indexed_vectors_count` rests at 80,020, a stable 3,838 below `points_count`.
This is neither lag nor loss: `optimizer_config.indexing_threshold` is 20,000, so
a segment smaller than that is never HNSW-indexed and is served by exact brute
force. Deterministic, and more accurate than HNSW rather than less. Verified that
nothing in the search path sets `indexed_only` — the only `"exact": True`
references are in `qdrant-chaos-repair.py` and `qdrant-repair-all.py`, which are
repair tooling.

Fiscal inventory intact and untouched: 69 documents / 13,180 chunks, newest
`updated_at` still 2026-09-10T08:50:57Z.

The 2,267 non-indexable source records remain in custody, unindexed, as directed.

### Dense recall across multiple chapters, with honest ranks

53 preregistered cases across 34 chapters, dense-only (`embedding_weight` 1.0,
`text_weight` 0.0, rerank disabled — confirmed in the audit events for all 53).

* **48 passed**; 38 at rank 1, 47 within rank 5
* **0 blocking**. Every miss's expected document is present in the store
* **5 retrieval-quality findings**, non-blocking, each recorded with its
  top-three hits: 2-303, 12-520, 16-1909, 19-3309, 59-2118
* 0 infrastructure errors, 0 cases requiring a search retry

No aggregate recall rate is published: 53 cases cannot distinguish 90% from 96%,
so the report is per-case pass/fail with every failure enumerated.

### Stored text checked against custody

**530 returned slices re-verified** against custody bytes — content hash, source
revision id, citation URL, character span, line span, text hash and both
coordinate conventions re-derived for every slice. **0 verification failures.**

### Preregistration

Case set `recall-cases-fullcorpus.json` sha256
`d0be6835ad0fd7e1de6d1c0e4e7b40f65050ff69370b382e29a1aa951bbf9eaf`; decision rule
`acceptance-decision-rule.md` sha256
`cc50b63246133beef36ce85365c9524099851e926f02ac68e1e9a784ff708c79`. Both written
and hashed before any result existed; the superseded rule
`474355a2a1c1fec0994cea7619b4791c00d924a7ed9b86dda0e7dd5f05e70c76` is recorded so
the amendment is auditable rather than silent. The Qdrant index state at scoring
time is stamped into the summary.

## Service defect found, isolated, not fixed here

Per this ticket's own instruction to record a blocking service defect rather than
weaken evidence: **the ingest path has no retry around the embeddings call**, so a
single transient outbound failure kills an entire run. This wave needed nine
attempts to finish.

Three regimes (`provider.embed()` batches one call per document, so calls ≈
documents):

| Window | Calls | Errors | Rate |
|---|---:|---:|---|
| 14:09 → 19:12 | ~15,000 | 0 | — |
| 19:12 → 19:38 | ~800 | 3 | ~1/270 |
| 19:38 → 22:34 | 13,272 | 5 | ~1/2,654 |

Two error classes, not one: `httpx.ConnectError` (never connected) at 19:12:27,
19:22:37, 19:31:30, 20:00:45, 20:32:02, 22:05:57, 22:15:16, and
`httpx.ReadTimeout` (connected, no answer) at 21:43:14.

**No mechanism is established.** An earlier "the API process degrades around 5
hours / 15,000 calls" reading was disconfirmed by direct test — the freshly
restarted process failed after 1,296 calls, 22 minutes in — so no threshold or
budget model survives. At ~1/2,654 the post-restart rate is unremarkable for
third-party HTTPS; the anomaly needing explanation is the pristine opening five
hours, not the failures.

A bounded retry with backoff belongs around the embeddings call. A failed
*connect* means the request never reached the provider, so retrying cannot
double-submit — this is **not** the 429 case WAVE-141 addressed, where the request
did land. It is deliberately not fixed inside this ticket, per the scope rule
against broadening provider code for throughput.

## Operational changes not present in the approved command

The API container was restarted twice mid-wave, both via `docker restart` (which
cannot re-resolve the image), both verified to leave the image id unchanged at
`sha256:e7271b65b055…` and the env hash unchanged at `12f228e079f0f98e`:

* **2026-09-11T19:38:21Z** — while diagnosing the failures above
* **2026-09-11T22:52:11Z** — immediately before the acceptance run, so a transient
  connect failure could not surface as a recall miss

A third incident is recorded for completeness: at 17:12Z a single
`/api/v1/retrieval/search` issued **during** ingestion deadlocked the run for ten
minutes. Ingestion held a `vector_stores` row lock in an open transaction while
the search's `UPDATE vector_stores SET last_active_at` waited on it;
`idle_in_transaction_session_timeout`, `statement_timeout` and `lock_timeout` are
all 0 on this cell, so it could not self-heal. Cleared with
`pg_cancel_backend(<waiter>)`, which returned that connection to the pool and
preserved the holder's uncommitted document — verified committed on recovery. The
mechanism remains unproven. **Nothing may be sent through the cell API while an
ingestion is running**; monitoring must go through psql, `docker inspect` and
`docker logs` only.

## Follow-ups

- Bounded retry with backoff around the embeddings call, before any full-corpus
  re-run. 31,079 documents at the observed rate is ~12 expected failures.
- `lock_timeout` on role **`svs_app`** — the role the API actually connects as;
  `svs_owner` is only the local psql session, so an `ALTER ROLE svs_owner` would
  succeed and change nothing. Verify with `SHOW lock_timeout` on a new API
  connection. Applies between waves, as it only takes effect on new connections.
- Restart the API container between waves as cheap hygiene, justified by an
  observed rate difference and not by a model — noting the baseline it is
  measured against may itself be the anomaly.
- Corpus property, for any parser: **chapter, article and section can each carry
  a letter suffix, independently** (772 / 1,718 / 2,779 occurrences; the article
  suffixes span 28 chapters). A pattern permitting a suffix on some segments but
  not others silently drops the rest, and the failure presents as *missing data*
  rather than as a parse error. This bit three times in one day — the registrar's
  original `_FILENAME_RE` (5,206 files), a label parser using `(\S+)` against
  multi-token range labels (445 headers), and this wave's per-chapter
  reconciliation (1,593 documents, a false shortfall across 25 chapters, caught
  only because the exact totals contradicted it).
- Unchanged and out of scope here: migration 111 attestations, canonical
  provision/action linking and the law-and-money GraphRAG (KS-600/650/651),
  `locator_verification` on the export, bounded Session Laws support. OVH remains
  **unverified**; this is the local cell only, `productionReady: false`.
