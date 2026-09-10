# WAVE-128 Upload Transaction Scope And Event-Loop Concurrency

## Summary

`POST /api/v1/documents/upload` holds a single database transaction open for the
entire duration of the external Marker call, and reaches the database through
synchronous calls inside an `async def` handler. The combination means the
endpoint is not merely un-parallel, it deadlocks itself: a second concurrent
upload blocks on a row the first has written, and because that block happens in
a synchronous call on the event loop, it stalls the whole API — including the
first request's own Marker polling and the health endpoint.

Fixing this is what stands between a ~42 GPU-hour serial corpus run and an
estimated ~10-15 hours.

## Background

Measured during the WAVE-126 Kansas fiscal corpus sweep. Queue time exceeds GPU
time on small documents (11.5 s queued against 9.6 s executing), so concurrency
looked like the obvious win. Two concurrent submissions instead produced **28
minutes of total API blackout, zero extractions, and zero output**.

The endpoint was never concurrency-safe. This is not a regression introduced by
the sweep.

## Evidence

`pg_stat_activity` during the blackout, verbatim:

```text
8250|idle in transaction|Client/ClientRead|00:25:58.298588| UPDATE vector_stores SET last_active_at=now(), usage_bytes=usage_bytes + $1, expires_at=C
8251|active|Lock/transactionid|00:25:58.25043| INSERT INTO rate_limit_counters(id, tenant_id, business_instance_id, subject_id, bucket,
```

```text
select pid||' blocked_by='||array_to_string(pg_blocking_pids(pid),',') ...
8251 blocked_by=8250
```

Reading that: request A (pid 8250) is `idle in transaction` for nearly 26
minutes — idle because the application is awaiting Marker, in transaction
because nothing committed before the external call. Request B (pid 8251) is
`active` but parked on `Lock/transactionid`, waiting for A, stuck on the
rate-limit counter upsert.

Corroborating symptoms, all resolved by clearing the blocked backend:

- `GET /healthz` returned nothing after a 20 s client timeout; after
  `pg_cancel_backend(8251)` it returned 200 in 3 ms.
- Request A's Marker submit had actually failed with `ConnectTimeout` early on,
  but the log line only appeared 28 minutes later, the moment the loop was
  freed. Its async polling could not run while a synchronous call held the loop.
- A leaked `idle in transaction` backend then blocked a further request for
  another 3 minutes until terminated. On release, two queued Marker retries
  submitted within a second of each other.

## Root Causes

1. **Transaction spans an external call.** `enforce_rate_limit` writes
   `rate_limit_counters` near the top of the handler, before Marker. That row
   stays locked for the whole extraction, so any concurrent upload by the same
   principal — same tenant, business instance, subject and rate-limit bucket —
   serialises behind it. Nothing commits before the external call.
2. **Synchronous database access on the event loop.** The handler is
   `async def` but reaches Postgres through a blocking `Session`. A blocked
   `INSERT` therefore stalls every other task on the loop rather than just its
   own request. This is what turns "slow" into "wedged".
3. **Widened by WAVE-127's ordering fix, though not caused by it.** Moving
   `_refresh_vector_store_activity_or_404` ahead of the Marker call — correct,
   and necessary to stop paying for doomed extractions — added `vector_stores`
   to the set of rows locked across extraction. With `rate_limit_counters`
   already locked there, this does not change the outcome, but it does mean the
   fix would serialise on its own even if rate limiting were removed. Both need
   to move out of the long transaction, not just one.

## Scope

- Commit, or otherwise release, before the Marker call, and re-acquire after.
  WAVE-127 already re-establishes RLS context post-extraction, so the shape for
  resuming work after the external call exists.
- Keep the pre-extraction vector-store validation, but do not hold its lock
  across the call.
- Move synchronous database work off the event loop, or make the handler's
  database access async.

## Out Of Scope

- Removing the pre-extraction store check. It is what stops a misconfigured
  destination costing a full extraction, and must stay.
- Changing Marker profiles, options, or the fiscal contract.
- Raising rate limits as a workaround. The lock duration is the defect; the
  limit itself is doing its job.

## Acceptance Criteria

- Two concurrent PDF uploads for the same principal and same vector store both
  reach Marker, and neither blocks the other; proven by overlapping
  `marker_queue_seconds` windows and two distinct RunPod job ids in flight.
- `GET /healthz` stays under one second throughout a multi-minute extraction.
- No backend sits `idle in transaction` for the duration of a Marker call.
- A concurrent run persists both documents, with idempotency still preventing
  duplicate logical documents.
- Serial behaviour is unchanged for a single upload.

## Payoff And Risk

Payoff: real concurrency on an endpoint where queue time exceeds compute time.
On the 14,499-page Kansas fiscal corpus this is the difference between roughly
42 GPU-hours serially and an estimated 10-15 hours.

Risk: this restructures transaction boundaries in a shared ingestion handler
used by every corpus, not just the fiscal one. It wants its own change window,
a healthy host, and a concurrency proof before it is trusted. It was explicitly
deferred rather than attempted mid-campaign on a memory-constrained host with a
wedged API.

## Operational Note

Until this is fixed, drive the fiscal sweep at concurrency 1. The sweep driver
warns and proceeds if a higher value is requested, rather than silently
serialising or wedging.

If the API does wedge, the remedy is to clear the blocking backend, not to
restart the API: `pg_cancel_backend(<blocked pid>)` for a request still
executing, or `pg_terminate_backend(<pid>)` for a leaked `idle in transaction`
backend whose client is gone. Check for a submitted RunPod job id in the API log
first — a handler that has already submitted is holding a paid extraction, and
killing it wastes that job, whereas the result of a completed one still persists
even when its client has disconnected.

## Dependencies

- WAVE-127, whose ordering fix this ticket must preserve while removing the
  lock it holds.
