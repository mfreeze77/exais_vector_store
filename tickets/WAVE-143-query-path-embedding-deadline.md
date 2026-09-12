# WAVE-143 Per-Call Embedding Deadline For The Query Path

Status: proposed. Priority: P1. Owner: ExAIS. Dependency: WAVE-142 (complete, landed_by c2bc7f72).

## Problem

WAVE-142 added a bounded retry around the Voyage embedding request and justified it
entirely from a 31,000-document ingestion run. The retry is applied inside
`VoyageEmbeddingProvider.embed`, and **the interactive query path calls the same
method**: `packages/svs_common/svs_common/retrieval.py:394` runs
`provider.embed([query], model, dimensions, input_type="query")` for a single user
query.

The arithmetic, confirmed: `httpx.AsyncClient(timeout=120)` per request, with the
300s deadline checked *before* each retry rather than during it.

| attempt | request | elapsed | remaining | action |
|---|---:|---:|---:|---|
| 1 | 120s | 120 | 180 | retry |
| 2 | 120s | 240 | 60 | retry |
| 3 | 120s | 360 | — | deadline blown, raise |

So a query embedding can now occupy **~360s** where it previously failed at 120s.
A search box and a bulk importer have different latency budgets, and `embed()`
exposes no way to pass a shorter deadline for interactive use.

This was found by WAVE-142's round-4 QC and recorded there as a follow-up rather
than fixed, because fixing it means changing `embed()`'s signature, which is wider
than that ticket's single call site.

## Second problem, same ticket

`POSSIBLE_DOUBLE_BILL_ERRORS` is `(httpx.ReadTimeout,)` — faithful to the owner's
F6 decision, which named only ReadTimeout. But `httpx.ReadError` (connection reset
while reading the response) and `httpx.RemoteProtocolError` (server disconnected
without a valid response) also occur **after the request was fully sent**, so they
carry the same "may already have been processed and billed upstream" risk. Both are
in `RETRYABLE_TRANSPORT_ERRORS` and are therefore retried up to five times with no
`possible_double_bill` line and no charge against `embedding_max_timeout_retries`.

That weakens WAVE-142's stated guarantee, "so spend stays auditable". It is a gap
in the decision's coverage, not a deviation from it.

`ConnectTimeout` is correctly excluded and must stay excluded: no connection means
nothing was billed.

## Scope

- A per-call deadline parameter on `embed()`, defaulting to
  `settings.embedding_retry_deadline_sec` so nothing changes for existing callers.
- The query path passes a short one.
- `ReadError` and `RemoteProtocolError` get the `possible_double_bill` audit line
  and count against the timeout allowance, as `ReadTimeout` does.

## Acceptance

- A query-path embedding fails within its own short deadline, proven by a test with
  an injected clock rather than by waiting.
- Existing ingestion callers are unchanged, proven by the WAVE-142 suite staying
  green at its current counts.
- A retried `ReadError` and a retried `RemoteProtocolError` each emit
  `possible_double_bill` with the batch id and token count.
- `ConnectTimeout` still emits no such line.

## Not in scope

Retry for the other providers. WAVE-142 declined it for want of observed failures
and that reasoning is unchanged.
