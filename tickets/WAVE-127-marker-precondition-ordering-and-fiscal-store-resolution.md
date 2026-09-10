# WAVE-127 Marker Precondition Ordering And Fiscal Store Resolution

## Summary

Seven defects found while running the WAVE-129 Kansas fiscal pipeline end to end
for the first time against a real RunPod Marker endpoint. The most expensive one
checks the target vector store only after the extraction is complete, and by
then the request's transaction-local RLS context is gone, so the lookup finds
nothing and 404s. That makes the PDF path unusable for any document slow enough
to matter, and it discards a Marker job that has already been paid for. Three
more defects explain how a caller reaches a bad store id, mislabel the store if
it is ever created, and block the removal path WAVE-129 depends on. The fifth is
why none of this can currently be costed: the client discards RunPod's own
timing fields.

## Background

The first live WAVE-129 ingest of a Division of the Budget comparison report
(`fy2005-comp-rpt.pdf`, 727,758 bytes) ran for 24 minutes and returned
`HTTP 404 Vector store not found`. The extraction had already completed and was
discarded. Nothing was persisted, so the idempotency record was never written and
the compute was unrecoverable.

The proximate operator error was passing
`--vector-store-id vs_kansas_fiscal_documents_pending`, which is a source-package
placeholder name and not a settable id — `POST /v1/vector_stores` generates ids,
and `ensure_vector_store` is designed to resolve a store by **name**. That
operator error should have been rejected in milliseconds. Instead it was billed.

WAVE-129's Notes already describe a narrow compute-reservation window where a
process failure after Marker returns can repeat extraction cost. Defect 1 is
adjacent but distinct and worse: it is not a crash after Marker, it is a
precondition that is never evaluated before Marker.

## Scope

- Resolve and validate the target vector store before any Marker extraction.
- Make `--allow-create-vector-store` reachable on the Kansas fiscal path.
- Stop stamping Topeka municipal-code attributes on non-Topeka stores.
- Set the transaction-local system-worker flag in `delete_vector_store_file`.

## Out Of Scope

- Closing the compute-reservation window described in WAVE-129's Notes; that is
  a request-control change and remains separate.
- Changing Marker request profiles, the `fiscal_tables_page_aware_v1` bounds, or
  any extraction behavior.
- Reworking tenant/business RLS policy itself.

## Defects

### 1. The PDF upload path loses its RLS context across the Marker call, so every slow PDF 404s after extraction

`apps/api/svs_api/main.py::upload_document` calls `marker_pdf_upload_request(...)`,
which performs the full RunPod extraction, and only afterwards calls
`ingest_or_enqueue`, whose first statement is
`_refresh_vector_store_activity_or_404(db, principal, req.vector_store_id)`.

The ordering is bad on its own, but the failure is worse than ordering. RLS
context is established once per request by `db_for_principal` (line 195) using
`set_config(..., true)`, which is **transaction-local**. By the time the Marker
call returns roughly twenty minutes later, that context is gone.
`refresh_vector_store_activity` then runs an `UPDATE ... RETURNING id` against
`vector_stores`, RLS matches no rows, the function returns `False`, and the
handler raises `404 Vector store not found or expired` — discarding a completed
extraction that has already been paid for.

Evidence:

- Two independent live runs failed identically. Run 1: submitted 02:26:38Z,
  404 at 02:49:56Z (23m18s). Run 2, with a verified-good store id: submitted
  02:54:01Z, 404 at 03:13:42Z (19m41s).
- The store was healthy and resolvable throughout. `GET /v1/vector_stores`
  returned exactly one match by name, `status=completed`, `expires_at=NULL`,
  which satisfies every non-RLS condition in the `UPDATE`'s `WHERE` clause.
- The same store accepted documents through `POST /api/v1/documents/ingest` and
  through `POST /api/v1/documents/upload` with a **non-PDF** file, using
  identical principal headers and identical form fields. Those requests are fast
  and take the non-Marker branch. Only the slow PDF branch fails.
- Direct database check: as `svs_app` with no RLS context,
  `SELECT count(*) FROM vector_stores` returns **0**; with
  `svs.tenant_id` / `svs.business_instance_id` set transaction-locally it
  returns 2. RLS invisibility is the only condition in that `WHERE` clause that
  was not satisfied.
- The codebase already knows this context can be lost mid-request: both
  `ingest_document` (line 1843) and `upload_document` (line 1893) call
  `set_rls_context(db, principal)` again immediately before `store_idempotency`.
  Neither re-establishes it before `ingest_or_enqueue`. On the JSON path nothing
  slow happens in between, so the gap is invisible. On the PDF path a full
  Marker job sits in that gap.

The consequence is that the WAVE-129 PDF ingestion path cannot currently succeed
for any document large enough to take a meaningful amount of Marker time. It is
not an intermittent or configuration-dependent failure; it reproduced exactly
twice, and the faster the document the more likely it is to slip under whatever
window the transaction survives.

Resolving the vector store **before** extraction fixes both the wasted-GPU
ordering and this failure, because the lookup then happens while the request's
original transaction and its RLS context are still live. Re-establishing RLS
context after the Marker call is the narrower fix and would still leave the
precondition being checked after the money is spent.

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
have carried Topeka municipal-code provenance. The store used for the WAVE-129
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
removal. This matters beyond tidiness: WAVE-129 requires that restricted,
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
WAVE-129 a real per-document cost figure.

### 6. Caller identity depends on whether `.release/` happens to be visible

`default_headers` in `scripts/release/topeka_pipeline_common.py` resolves the
tenant, business instance and user from `maybe_read_env(cell)`, which reads
`ROOT/.release/cells/<cell>/.env.cell` and otherwise falls back to
`DEFAULT_TENANT_ID` and friends.

`ROOT` is derived from the script's own location, so the same command run against
the same cell sends a different principal depending on which copy of the tree the
process sees. In this run the ingest executed from the API image, where `/app`
has no `.release`, and sent `ten_ks_state_civics`. The handoff executed with the
worktree mounted, where `.release/cells/ks-fiscal-local/.env.cell` does exist, and
so sent that file's `SVS_DEV_TENANT_ID` of `ten_dev`. The handoff then failed with
`404 Vector store file not found` on a file that was present and healthy, because
RLS correctly hid another tenant's row.

Two commands in the same pipeline, pointed at the same cell, disagreeing about who
they are is a latent correctness problem well beyond this run. The fallback should
be explicit rather than filesystem-dependent, and the resolved principal should be
logged.

### 7. The endpoint no longer honours two of the three fiscal profile options

This one is endpoint-side, not client-side. The client builds the request
correctly: `paginate_output`, `html_tables_in_markdown` and
`disable_image_extraction` are all placed inside `payload["input"]`, and the
persisted `marker_options` confirms all three were sent.

The returned Markdown does not reflect two of them. Measured on the 139-page
FY2005 comparison report (937,624 characters):

- `paginate_output: true` produced **zero** `{N}` page delimiters.
- `html_tables_in_markdown: true` produced **zero** `<table>` elements; all 106
  detected tables are GFM pipe tables, 4,047 pipe lines.
- The same is true of the 1-page allotment letter, so this is systemic rather
  than a property of one document.

The 2026-09-04 bounded proof recorded 31 consecutive page delimiters and 6
HTML-preserved tables from the same profile, so the endpoint's behaviour has
changed since. The consequence is that the handoff refuses with
`persisted Marker artifact has no page delimiters`, and WAVE-129's requirement
for HTML-preserved table geometry (rowspan/colspan) cannot be satisfied from this
output either.

This blocks KS-599 regardless of the fixes in this ticket: extraction now
succeeds and persists, but produces output the contract cannot accept. Confirm
the deployed Marker image and option names before spending further GPU.

## Deliverables

- Vector-store resolution moved ahead of Marker extraction in `upload_document`.
- `ensure_vector_store` verifying a supplied id, or resolving by name, rather
  than returning any non-sentinel id unchecked.
- Corpus-neutral store-creation attributes supplied by the calling adapter.
- `set_config('svs.system_worker', 'true', true)` in `delete_vector_store_file`
  before its chunk mutation.
- RunPod `delayTime` and `executionTime` captured into the persisted Marker
  attributes, and Marker status transitions logged on the upload path.
- Regression tests for each.

## Acceptance Criteria

- Uploading a PDF for a nonexistent vector store returns 404 without any RunPod
  request being issued; proven by a test that fails if the Marker client is
  called.
- A PDF whose Marker extraction takes long enough to outlive the request's
  original transaction still persists successfully; proven by a test that
  simulates a slow extraction and asserts the vector-store lookup still resolves.
- A supplied `--vector-store-id` that does not exist fails closed before upload.
- `--allow-create-vector-store` creates a store on the Kansas fiscal path, and
  the created store carries that adapter's own corpus attributes, not Topeka's.
- `DELETE /v1/vector_stores/{id}/files/{file_id}` returns success, marks chunks
  inactive, and queues index cleanup without weakening tenant/business RLS.
- The WAVE-129 removal ordering (removals converge before additions) is proven
  through the per-file route.
- A completed Marker extraction records its queue time and its GPU execution
  time, so per-document cost can be read off a run rather than inferred from
  wall clock.

## Dependencies

- WAVE-012, whose system-worker fix this extends to the third delete route.
- WAVE-129, whose live run surfaced all seven defects.

## Verification

```bash
pytest -q \
  tests/test_pdf_marker_upload.py \
  tests/test_documents_ingest.py \
  tests/test_kansas_fiscal_document_ingest.py \
  tests/test_openai_vector_store_file_routes.py
```

Plus a live re-run of the WAVE-129 single-document ingest confirming that a bad
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
