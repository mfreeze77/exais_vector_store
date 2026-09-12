# Kansas Fiscal Documents

This vector store is the narrative retrieval plane for StateCivics fiscal
evidence: budget reports, agency budget narratives, fiscal notes, ACFRs,
minutes, testimony, and other exporter-approved explanatory documents.

It is not the fiscal system of record. Codes, accounts, crosswalks, amounts,
resolution status, and publication decisions remain in StateCivics canonical
tables. Retrieval may locate a passage and return its official citation; it
must never decide that two fiscal dimensions are the same.

The [unified law-and-money handoff](../../../../docs/STATECIVICS_LAW_MONEY_ALIGNMENT.md)
records the agreed upstream owners and correction tickets. KS-650 extends the
existing document exporter with a second entity/relationship record kind;
WAVE-133 through WAVE-136 consume typed structured/document evidence and prove
real answers. Raw CSV ingestion remains outside this narrative lane. Provision
identity comes from KS-600, while source spans retain their evidence role.

Related instance research: [law-and-money backbone](../../research/law-and-money-backbone.md)
records the open-source comparison and the classification, aggregation, and
provision-evidence responsibilities agreed with the StateCivics developer manager.

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

The 2026-09-04 live proof passed in one Marker job: 32,281 Markdown
characters, 6 structured tables, 125 rows, and 927 cells. All three anchors and
all nine pinned table rows matched. This proves representative extraction
fidelity; it does not make PDF-derived amounts canonical. KanView and other
registered structured feeds remain the numeric system of record.

## One-pass extraction handoff

After API ingestion, ExAIS already holds the exact Marker Markdown and its
source/structure metadata. The handoff exporter retrieves those persisted
objects through authenticated ExAIS APIs, verifies the StateCivics revision,
original PDF hash, Markdown hash, character count, table counts, and ExAIS IDs,
then writes deterministic Markdown plus JSONL for StateCivics.

The source adapter selects the jurisdiction-neutral
`fiscal_tables_page_aware_v1` profile, so that original Marker job also requests
page markers, HTML-preserved tables, and image retention.

```bash
python scripts/release/kansas-fiscal-marker-handoff.py \
  --manifest "$STATECIVICS_FISCAL_MANIFEST" \
  --state .release/cells/ks-state-civics/kansas-fiscal-documents/state.json \
  --output-dir .release/cells/ks-state-civics/kansas-fiscal-documents/marker-handoff \
  --code-commit "$EXAIS_CODE_COMMIT" \
  --api-transport docker-network
```

That command plans only. Append `--apply` to fetch persisted content and write
the local handoff package. It has no Marker client or RunPod path, so this is
reuse of the original extraction, not another extraction charge. StateCivics
may parse its tables into candidate observations, but it must independently
resolve dimensions and publication status.

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

## Fiscal law-and-money GraphRAG

WAVE-132 adds a fiscal handler and the explicit `fiscal_relationships` search
lens for enacted provisions, appropriations, accounts, agencies, funds, and
supporting documents. It is enabled only by an exact fiscal cell/store profile
and a current reviewed graph run; semantic search remains independent.

The disabled template is `graph/profile.example.yaml`. It is separate from the
cell's court profile. The publisher adapter, staged load, and evaluation commands
are documented in [the operator path](../../../../docs/FISCAL_GRAPH_OPERATOR.md).
WAVE-132 remains reopened. KS-650 must extend the existing StateCivics exporter;
WAVE-133 through WAVE-136 must replace the provisional PDF/chunk assumptions
and prove real-source answers before activation. The current adapter envelope is
not an upstream contract requirement. Synthetic runtime proof grants no source
publication approval.
