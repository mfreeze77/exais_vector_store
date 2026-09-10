# WAVE-127 Marker Precondition Ordering And Fiscal Store Resolution

## Summary

Four defects found while running the WAVE-126 Kansas fiscal pipeline end to end
for the first time against a real RunPod Marker endpoint. The most expensive one
runs a complete Marker extraction before checking whether the target vector store
exists, so any store misconfiguration costs a full GPU job to discover. The other
three explain how a caller reaches that state, mislabel the store if it is ever
created, and block the removal path WAVE-126 depends on.

## Background

The first live WAVE-126 ingest of a Division of the Budget comparison report
(`fy2005-comp-rpt.pdf`, 727,758 bytes) ran for 24 minutes and returned
`HTTP 404 Vector store not found`. The extraction had already completed and was
discarded. Nothing was persisted, so the idempotency record was never written and
the compute was unrecoverable.

The proximate operator error was passing
`--vector-store-id vs_kansas_fiscal_documents_pending`, which is a source-package
placeholder name and not a settable id — `POST /v1/vector_stores` generates ids,
and `ensure_vector_store` is designed to resolve a store by **name**. That
operator error should have been rejected in milliseconds. Instead it was billed.

WAVE-126's Notes already describe a narrow compute-reservation window where a
process failure after Marker returns can repeat extraction cost. Defect 1 is
adjacent but distinct and worse: it is not a crash after Marker, it is a
precondition that is never evaluated before Marker.

## Scope

- Resolve and validate the target vector store before any Marker extraction.
- Make `--allow-create-vector-store` reachable on the Kansas fiscal path.
- Stop stamping Topeka municipal-code attributes on non-Topeka stores.
- Set the transaction-local system-worker flag in `delete_vector_store_file`.

## Out Of Scope

- Closing the compute-reservation window described in WAVE-126's Notes; that is
  a request-control change and remains separate.
- Changing Marker request profiles, the `fiscal_tables_page_aware_v1` bounds, or
  any extraction behavior.
- Reworking tenant/business RLS policy itself.

## Defects

### 1. Marker runs before the vector-store precondition is checked

`apps/api/svs_api/main.py::upload_document` calls `marker_pdf_upload_request(...)`,
which performs the full RunPod extraction, and only afterwards calls
`ingest_or_enqueue`, whose first statement is
`_refresh_vector_store_activity_or_404(db, principal, req.vector_store_id)`.

A nonexistent, expired, or cross-tenant vector store therefore costs one complete
extraction before the 404 is raised. Measured cost of one such discovery: 24
minutes of wall clock on a 727,758-byte PDF.

This is the highest-value fix in this ticket. The vector store is known from the
multipart form before a single byte is sent to RunPod.

### 2. `--allow-create-vector-store` is unreachable on the fiscal path

`scripts/release/topeka_pipeline_common.py::ensure_vector_store` opens with:

```python
if vector_store_id and vector_store_id != DEFAULT_VECTOR_STORE_ID:
    return vector_store_id
```

`DEFAULT_VECTOR_STORE_ID` is `vs_topeka_municipal_code_pending`. The Kansas fiscal
command's own default is `vs_kansas_fiscal_documents_pending`
(`scripts/release/kansas-fiscal-document-ingest.py`), which never equals that
sentinel. So whenever an id is supplied the function returns it verbatim: the
lookup-by-name branch and the create branch are both unreachable, the flag is
dead code, and the id is never verified to exist. That unverified id is what
defect 1 then charges a Marker job to reject.

### 3. Store creation stamps Topeka attributes on any corpus

The same helper's create payload hardcodes:

```python
"attributes": {
    "corpus": "topeka_municipal_code",
    "source_collection": "topeka-municipal-code",
    ...
}
```

Had creation been reachable for Kansas fiscal documents, the resulting store would
have carried Topeka municipal-code provenance. The store used for the WAVE-126
proof was created out of band with correct Kansas fiscal attributes and
`production_ready: false` to avoid this.

### 4. `delete_vector_store_file` fails under chunk RLS

`DELETE /v1/vector_stores/{id}/files/{file_id}` returns HTTP 500:

```text
psycopg.errors.InsufficientPrivilege: new row violates row-level security policy for table "chunks"
```

This is the same failure WAVE-012 fixed, on a route WAVE-012 missed.
`/v1/files/{file_id}` sets `SELECT set_config('svs.system_worker', 'true', true)`
before its `UPDATE chunks`, and so does the vector-store delete path.
`delete_vector_store_file` updates `chunks` with no such flag.

Deleting the entire store still succeeds, so the gap is specific to per-file
removal. This matters beyond tidiness: WAVE-126 requires that restricted,
withdrawn, unavailable, corrected, and superseded records remove a previously
indexed file *before* any additions are applied. That convergence path runs
through this route.

### 5. No per-job Marker cost telemetry

`MarkerRunpodClient` polls `/status/{job_id}` and reads only `status` and
`output`. RunPod returns `delayTime` (time spent queued, including cold start)
and `executionTime` (actual GPU time) on that same response, and both are
discarded. The client's `emit` progress callback is also not wired to logging on
the `upload_document` path, so a completed job leaves no record of how long it
queued versus how long it ran.

The consequence is operational, not cosmetic: with only end-to-end wall clock,
there is no way to tell whether a slow corpus is GPU-bound or queue-bound, and
therefore no way to decide whether adding concurrency would help or would merely
parallelise a queue. Capturing `delayTime` and `executionTime` into the persisted
Marker attributes would make that decision evidence-based and would also give
WAVE-126 a real per-document cost figure.

## Deliverables

- Vector-store resolution moved ahead of Marker extraction in `upload_document`.
- `ensure_vector_store` verifying a supplied id, or resolving by name, rather
  than returning any non-sentinel id unchecked.
- Corpus-neutral store-creation attributes supplied by the calling adapter.
- `set_config('svs.system_worker', 'true', true)` in `delete_vector_store_file`
  before its chunk mutation.
- Regression tests for each.

## Acceptance Criteria

- Uploading a PDF for a nonexistent vector store returns 404 without any RunPod
  request being issued; proven by a test that fails if the Marker client is
  called.
- A supplied `--vector-store-id` that does not exist fails closed before upload.
- `--allow-create-vector-store` creates a store on the Kansas fiscal path, and
  the created store carries that adapter's own corpus attributes, not Topeka's.
- `DELETE /v1/vector_stores/{id}/files/{file_id}` returns success, marks chunks
  inactive, and queues index cleanup without weakening tenant/business RLS.
- The WAVE-126 removal ordering (removals converge before additions) is proven
  through the per-file route.

## Dependencies

- WAVE-012, whose system-worker fix this extends to the third delete route.
- WAVE-126, whose live run surfaced all four defects.

## Verification

```bash
pytest -q \
  tests/test_pdf_marker_upload.py \
  tests/test_documents_ingest.py \
  tests/test_kansas_fiscal_document_ingest.py \
  tests/test_openai_vector_store_file_routes.py
```

Plus a live re-run of the WAVE-126 single-document ingest confirming that a bad
store id is rejected before extraction rather than after.

## Notes

- Found on branch `feat/wave-126-kansas-fiscal-documents` at HEAD `25dd295`,
  running a locally built cell (`ks-fiscal-local`, API port 28085) against the
  configured RunPod Marker endpoint.
- That cell was brought up with `docker compose` directly rather than
  `cell-up.py`, so the digest-pinned release provenance gate was **not**
  exercised. Any acceptance claim from that run carries this caveat.
- Separately worth recording: the cached `exais-fiscal-test:local` image from
  2026-09-04 predates `FISCAL_TABLES_PAGE_AWARE_PROFILE` and
  `marker_options_for_profile`. Reusing it would have produced a plausible
  extraction with no pagination, no HTML-preserved tables, and no image
  extraction, and the StateCivics handoff would then have failed validation for
  reasons that look like a receiver bug. Rebuild from HEAD before any Marker
  measurement.
