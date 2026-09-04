# Kansas Fiscal Documents

This vector store is the narrative retrieval plane for StateCivics fiscal
evidence: budget reports, agency budget narratives, fiscal notes, ACFRs,
minutes, testimony, and other exporter-approved explanatory documents.

It is not the fiscal system of record. Codes, accounts, crosswalks, amounts,
resolution status, and publication decisions remain in StateCivics canonical
tables. Retrieval may locate a passage and return its official citation; it
must never decide that two fiscal dimensions are the same.

## Extraction boundary

Every retained `application/pdf` is submitted to
`POST /api/v1/documents/upload` with `mode=auto_detect_v1`. That route invokes
the configured RunPod Marker serverless endpoint and preserves Marker page,
layout, table, and job provenance in ExAIS metadata. There is no local Marker
fallback and no silent plain-text PDF path. Marker performs its document,
layout, image, and table work in one job; the fiscal quality gate evaluates the
Markdown from that same response and never submits a second extraction.

Already-structured `text/markdown` and `text/plain` objects use
`POST /api/v1/documents/ingest` directly. Sending those through Marker would
waste extraction capacity and reduce fidelity. Raw KanView transaction and
chart-of-accounts extracts are not retrieval documents and are refused.

## Marker fiscal quality gate

The release gate uses a hash-pinned FY2025 Governor's Budget presentation and
checks minimum output structure, identifying anchors, and nine exact fiscal
rows spread across three tables. It emits counts, hashes, and pass/fail details,
but never prints or stores the source document's extracted text:

```bash
python scripts/release/marker-fiscal-quality-proof.py \
  --pdf "$KANSAS_FISCAL_QUALITY_PDF" \
  --profile instances/ks-state-civics/vector-stores/kansas-fiscal-documents/quality/fy2025-director-presentation.json \
  --profile-sha256 c7d024d803c7e0feb685569a1eac786a622ade2445fb740a42e9d4b4968b53f0 \
  --output .release/cells/ks-state-civics/kansas-fiscal-documents/marker-quality-proof.json
```

The 2026-09-04 live proof passed in one Marker job: 30,615 Markdown
characters, 6 structured tables, 125 rows, and 927 cells. All three anchors and
all nine pinned table rows matched. This proves representative extraction
fidelity; it does not make PDF-derived amounts canonical. KanView and other
registered structured feeds remain the numeric system of record.

## Source and idempotency

StateCivics exports a deterministic desired-state JSONL manifest from its
custody ledger. The adapter:

- verifies the manifest record digest;
- resolves `civic-custody://` only under an explicitly mounted custody root;
- verifies custody bytes against both the URI digest and ledger digest;
- uses `logical_document_id` as stable source identity across revisions;
- scopes idempotency to vector store, logical document, desired action, and
  record digest;
- applies removals before additions and atomically checkpoints each result.

Dry-run performs all local validation and custody reads but makes no API calls
or state writes:

```bash
python scripts/release/kansas-fiscal-document-ingest.py \
  --manifest "$STATECIVICS_FISCAL_MANIFEST" \
  --custody-root "$STATECIVICS_CUSTODY_ROOT" \
  --state .release/cells/ks-state-civics/kansas-fiscal-documents/state.json \
  --proof .release/cells/ks-state-civics/kansas-fiscal-documents/plan.json
```

After reviewing the plan, supply the created vector-store ID and append
`--apply`. Production readiness remains false until a disposable/live API run,
repeat-run zero-mutation proof, Marker metadata proof, and recall evaluation
all pass.

API persistence, vector indexing, repeat-run zero mutation, and recall remain
gated even though the representative Marker extraction and table-fidelity proof
now pass.
