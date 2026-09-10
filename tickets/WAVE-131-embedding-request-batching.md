# WAVE-131 Embedding Request Batching And Vector/Chunk Alignment

## Summary

`OpenAIEmbeddingProvider.embed` posted every chunk of a document in a single
embeddings request. OpenAI caps one embeddings request at **300,000 tokens** and
answers a larger one with HTTP 400 `max_tokens_per_request`; the provider called
`raise_for_status()` on that, so the ingest surfaced a 500 and the document could
not be indexed at all.

This made the 16 largest documents in the Kansas fiscal corpus permanently
un-indexable: every Governor's Budget Report volume, 20.3 MB of markdown and
7,106 source pages, 57.6% of the corpus by markdown bytes.

Fixed by batching inside the provider under a strict ordering contract. All 16
are now indexed.

## Evidence

The failure recorded by the API, verbatim:

```text
INFO:httpx:HTTP Request: POST https://api.openai.com/v1/embeddings "HTTP/1.1 400 Bad Request"
httpx.HTTPStatusError: Client error '400 Bad Request' for url 'https://api.openai.com/v1/embeddings'
INFO:     192.168.65.1:38927 - "POST /api/v1/documents/ingest HTTP/1.1" 500 Internal Server Error
```

`raise_for_status()` discards the response body, so the operative error was not
in the logs. Reproduced live against `text-embedding-3-small` on 2026-09-10 with
near-boundary payloads built from a real GBR volume's chunks:

```text
under: chunks=325 tokens=296,755 bytes=1,196,623  -> HTTP 200, 325 vectors
over : chunks=330 tokens=302,434 bytes=1,211,290  -> HTTP 400
  {"error": {"message": "Requested 302822 tokens, max 300000 tokens per request",
             "type": "max_tokens_per_request", "code": "max_tokens_per_request"}}
```

The two payloads differ by 1.2% in bytes and straddle 300,000 tokens, so the
binding limit is tokens, not payload size. The other candidate limits were ruled
out by measurement over all 12,577 corpus chunks (cl100k_base):

| candidate limit | corpus maximum | binding? |
| --- | --- | --- |
| 300,000 tokens per request | 466,800 | **yes** |
| 2,048 inputs per request | 491 | no |
| 8,191 tokens per input | 1,642 | no |
| rate limit (429) | never observed | no |

Exact token counts partition the corpus cleanly, with the cap inside the gap:

- 46 successes: **all <= 249,456** tokens (max `fy2016-comp-rpt-upd-2015-09-17.md`)
- 16 failures: **all >= 351,821** tokens (min `FY-2016-GBR-Vol.-2.md`)

No chunk anywhere exceeds the per-input cap, so batching alone is sufficient to
make every one of the 16 indexable.

## Root Cause

`packages/svs_common/svs_common/providers.py` sent `json={'input': texts, ...}`
with no batching, for a `texts` list that is every chunk of the document.
`ingestion.py` calls `provider.embed()` once with the whole document, so request
size grew without bound with document size.

## The Ordering Hazard

Vectors are matched to chunk text **positionally** — `zip(parsed_chunks,
embeddings.data)` in `ingestion.py`, `zip(group, emb.data)` in
`maintenance.py`. Naive batching introduces two silent-corruption paths that are
worse than the 500 they replace, because retrieval would return wrong text with
no error anywhere:

1. **Batch-local indices.** The old code trusted `item['index']` from the
   response. Under batching that index is request-local, so it must be
   reassigned globally or vectors land against the wrong chunks.
2. **Short results truncate.** `zip` stops at the shorter sequence. A batch that
   returned n-1 vectors would silently drop the document's tail chunks while the
   document was still marked `completed`.

So the batching contract is strict: `embed()` returns exactly one vector per
input, in input order, or it raises.

## Changes

`packages/svs_common/svs_common/providers.py`

- `plan_embedding_batches()` splits inputs into contiguous `[start, end)` spans
  that cover every input exactly once in input order. An input whose own
  estimate exceeds the budget still gets its own span, so nothing is dropped.
- `estimate_embedding_tokens()` estimates from character length, because the
  runtime images carry no tokenizer. Measured over the corpus's 12,577 chunks
  the true ratio is 3.08 chars/token median and 1.58 minimum, so the divisor of
  2.0 over-counts for realistic text. Budget 200,000, leaving 100,000 headroom.
- `ordered_batch_vectors()` reorders each batch by the index the endpoint
  reported and rejects a short, duplicated, or out-of-range response.
- `embed_in_order()` concatenates spans and re-checks the total count.
- Bisection backstop: a batch rejected with `max_tokens_per_request` is split in
  half and re-sent. This reacts only to that explicit rejection, adds no delay,
  and terminates because each step halves the batch — it is a correctness
  backstop for content the character estimate under-counts, not a retry policy.
  `providers.py` has no retry/backoff convention and none was introduced.
- A single input still over the cap raises `EmbeddingBatchError` naming the
  chunking profile, rather than being dropped.
- Usage counters are summed across batches instead of reporting only the last.

Consumer-side guards, closing the `zip` truncation path:

- `ingestion.py` and `maintenance.py` now raise `EmbeddingBatchError` when the
  returned vector count does not match the chunk count.

## Other Providers

| provider | shares the flaw | action |
| --- | --- | --- |
| `openai` | yes, confirmed live | batched, 300,000 tokens / 2,048 inputs |
| `voyage` | yes, structurally | batched, 100,000 tokens / 1,000 inputs |
| `cohere` | yes, structurally | batched, 96 inputs |
| `GenericEndpointEmbeddingProvider` (TEI, Infinity, RunPod, self-hosted) | yes, structurally | **flagged, unchanged** |
| `hash_mock` | no — local, no request | none needed |

The Voyage and Cohere caps are applied conservatively — a batch below the vendor
cap is always accepted where a larger one would be — but they were **not**
confirmed against the live vendor APIs, unlike the OpenAI cap. Only OpenAI is in
use in this cell.

`GenericEndpointEmbeddingProvider` was deliberately left unchanged: it fronts
endpoints whose per-request caps are deployment-specific and unknown here, so any
batch size would be a guess, and it serves a live cell. Its request shape is
untouched. Extending the ordering and count guards to it needs a real endpoint's
limits measured first.

## Test

`tests/test_embedding_request_batching.py`, 15 cases. The fake endpoint enforces
the real 300,000-token cap and returns each batch's vectors **reversed** and
tagged with request-local indices, so any failure to reorder shows up as a
mismatch rather than passing by luck.

Covered: a document 2.3x over the cap is split and stays in order; batching is
driven by token estimate not input count (40 inputs, 800,000 tokens); usage sums
across batches; an under-estimated batch is bisected; a single oversized input
fails the document; a short response raises instead of truncating; duplicate
response indices raise; the planner covers every input exactly once, honours
both budget and count caps, and never drops an oversized input; Voyage and
Cohere batch and preserve order.

Confirmed the test catches the original defect: against the pre-fix provider the
same scenario makes **1 request of 700 inputs** and fails with
`Requested 700000 tokens, max 300000 tokens per request`.

Full suite after the change: **983 passed, 39 skipped**.

## Result

All 16 GBR volumes ingested, `status=completed`, 0 failed. 64 embedding requests
for 16 documents where the pre-fix path made 16 requests and all 16 got a 400.

Per-document `chunks == embeddings == dense_indexed == sparse_indexed`, and every
count equals an independent offline run of the same chunker. Qdrant holds 12,579
+ 600 = 13,179 points against 13,179 active chunks.

Alignment was verified against the live index rather than assumed: chunk texts at
batch boundaries (ordinals 0, 1, 124-126, 249-251, 374-376, 489, 490 of a
491-chunk volume) were re-embedded and compared with the stored vectors. Every
stored vector matched its own chunk at cosine >= 0.999997, while the nearest
other chunk reached at most 0.907.

## Follow-ups

- Rebuild the cell images. The fix reached the running cell as a file-level
  patch into `api-1` and `worker-1`; the `wave126-local` images still carry the
  unbatched provider and would reintroduce it on container recreate.
- Extend ordering and count guards to `GenericEndpointEmbeddingProvider` once a
  private endpoint's per-request limits are measured.
- Confirm the Voyage and Cohere caps against the live vendor APIs.
- `object_store.put_text` runs before `embed()` in `ingest_now`, so a failed
  embed leaves the original and parsed objects behind while the DB rows roll
  back. Pre-existing, unchanged here, worth a sweep.
- The worker registers no `SIGTERM` handler and runs as PID 1, where default
  signal dispositions do not apply, so `docker stop` always waits out the grace
  period and SIGKILLs it (exit 137, `OOMKilled=false`). Cosmetic but it makes
  every ordinary stop look like a crash.
