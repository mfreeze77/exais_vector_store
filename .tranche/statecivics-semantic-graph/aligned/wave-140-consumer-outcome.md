# WAVE-140 — consumer-side outcome

> Version-controlled copy. The working original was written to the operator
> directory `~/Developer/statecivics-statute-ingestion/wave-140/`, which is not a
> git repository; this is the canonical copy.

The statutes are ingested, reconciled and searchable in the `ks-fiscal-local`
cell, store `vs_daafbc5d7aa54b23b3f10392` ("Kansas Statutes").

## Completion reconciliation — PASS

Run finished 2026-09-11T22:34:29Z, container exit 0, `status: completed`,
85 of 85 chapters, `removed: 0`.

| | Target | Actual |
|---|---:|---:|
| Documents | 28,812 | **28,812** |
| Chunks | 83,258 | **83,258** |
| Embeddings | == chunks | **83,258** |
| Versions | == documents | **28,812** |
| Qdrant points in the shared voyage collection | 83,858 | **83,858** |
| Per-chapter vs `INDEX.json` indexable_documents | exact | **all 85 exact** |
| Documents with >1 version | 0 | **0** |

Qdrant's collection `svs_biz_ks_state_civics_voyage_4_docs_1024` is **shared**:
83,258 statute vectors + 600 belonging to the fiscal store (whose other 12,580
chunks live in the openai collection). Comparing its `points_count` against
statute chunks alone reports a 600-point surplus that does not exist.

`indexed_vectors_count` sits at 80,020, a stable 3,838 short of `points_count`.
That is **not** lag or loss: `optimizer_config.indexing_threshold` is 20,000, so
a segment below that size is never HNSW-indexed and is searched by exact brute
force. Deterministic, and more accurate than HNSW rather than less.

Invariants held: fiscal store untouched at 69 documents / 13,180 chunks, newest
`updated_at` still 2026-09-10T08:50:57Z.

## Acceptance run — PASS

53 preregistered cases across 34 chapters, dense-only (`embedding_weight` 1.0,
rerank disabled, confirmed for all 53 in the audit events).

* **48 passed**, 38 of them at rank 1, 47 within rank 5
* **0 blocking** — every miss's expected document is present in the store
* **5 retrieval-quality findings** (non-blocking): 2-303, 12-520, 16-1909,
  19-3309, 59-2118, each recorded with its top-three hits
* **530 returned slices re-verified** against custody bytes — every content
  hash, source revision, citation URL, character span, line span and coordinate
  convention re-derived. **0 verification failures**
* 0 infrastructure errors, 0 cases needing a retry

Pins: case set `d0be6835ad0fd7e1de6d1c0e4e7b40f65050ff69370b382e29a1aa951bbf9eaf`,
decision rule `cc50b63246133beef36ce85365c9524099851e926f02ac68e1e9a784ff708c79`
(both preregistered before any result existed; the superseded rule
`474355a2a1c1fec0994cea7619b4791c00d924a7ed9b86dda0e7dd5f05e70c76` is recorded so
the amendment is auditable). Qdrant index state at scoring time is stamped into
the summary.

## Operational record

Nine attempts, eight replays, one mid-run operational change.

**Three regimes of outbound embedding failure** (`provider.embed()` batches one
call per document, so calls ≈ documents):

| Window | Calls | Errors | Rate |
|---|---:|---:|---|
| 14:09 → 19:12 | ~15,000 | 0 | — |
| 19:12 → 19:38 | ~800 | 3 | ~1/270 |
| 19:38 → 22:34 (after API restart) | 13,272 | 5 | ~1/2,654 |

Two error classes, not one: `httpx.ConnectError` (never connected) at 19:12:27,
19:22:37, 19:31:30, 20:00:45, 20:32:02, 22:05:57, 22:15:16 and `httpx.ReadTimeout`
(connected, no answer) at 21:43:14. They need not share a cause and are not
collapsed here.

**No mechanism is established.** An earlier "the API process degrades around 5
hours / 15,000 calls" reading was disconfirmed by direct test: the freshly
restarted process threw its first ConnectError after 1,296 calls, 22 minutes in,
so no threshold or budget model survives. At ~1/2,654 the post-restart rate is
unremarkable for third-party HTTPS — the anomaly needing explanation is the
pristine opening five hours, not the failures.

The API container was restarted once mid-run, 2026-09-11T19:38:21Z, via
`docker restart` (which cannot re-resolve the image). Image id verified unchanged
at `sha256:e7271b65b055…`, env hash unchanged at `12f228e079f0f98e`. This was an
operational change not present in the approved command and is recorded as such.
It was restarted again at 22:52:11Z immediately before the acceptance run, so a
transient connect failure could not surface as a recall miss.

**Recommended before the next wave**, in priority order:

1. A bounded retry with backoff around the embeddings call. A failed *connect*
   means the request never reached the provider, so retrying cannot
   double-submit — this is not the 429 case the WAVE-140 handoff warned about,
   where the request did land. One dropped TCP connect out of 31,000 currently
   costs an entire run.
2. Restart the API container between waves as cheap hygiene — justified by an
   observed rate difference, not by a model, and noting the baseline it is
   measured against may itself be the anomaly.
3. A `lock_timeout` on `svs_app` (**not** `svs_owner` — the API connects as
   `svs_app`; the owner role is only the local psql session). Verify with
   `SHOW lock_timeout` on a new API connection. This converts a permanent stall
   into a failed request the coordinator already handles.

## Corpus property worth recording

**Chapter, article and section can each carry a letter suffix, independently.**
Across the corpus: 772 chapter suffixes, 1,718 article suffixes spanning 28
chapters, 2,779 section suffixes. Any filename or URL pattern that permits a
suffix on some segments but not others silently drops the rest — and the failure
presents as *missing data*, not as a parse error. This bug class appeared three
times in one day: in the registrar's original `_FILENAME_RE` (5,206 files), in a
section-label parser using `(\S+)` against multi-token range labels (445 headers),
and in this wave's per-chapter reconciliation (1,593 documents, reported as a
false shortfall across 25 chapters before the exact totals contradicted it).

Related: a section label is not always a single token — 445 headers carry range
labels such as `K.S.A. 40-2,205 through 40-2,209`, of which 351 are Reserved, 89
have an empty title, and 5 are real sections with substantive text. Separators
vary: 367 use "through", 77 a comma pair, one a bare space.
