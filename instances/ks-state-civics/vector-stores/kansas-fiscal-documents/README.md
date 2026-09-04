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
fallback and no silent plain-text PDF path.

Already-structured `text/markdown` and `text/plain` objects use
`POST /api/v1/documents/ingest` directly. Sending those through Marker would
waste extraction capacity and reduce fidelity. Raw KanView transaction and
chart-of-accounts extracts are not retrieval documents and are refused.

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

Current bounded extraction proof: on 2026-09-04 the configured RunPod Marker
endpoint converted the real 718 KB FY2025 Kansas Governor's Budget director
presentation into 30,615 characters of Markdown in one attempt. This establishes
endpoint parsing only; API persistence, vector indexing, and recall remain gated.
