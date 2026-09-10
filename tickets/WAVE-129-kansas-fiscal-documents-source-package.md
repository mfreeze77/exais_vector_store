# WAVE-129 Kansas Fiscal Documents Source Package

## Summary

Create a separate Kansas fiscal-document vector store that consumes the
StateCivics custody-ledger export, routes every PDF through the configured
RunPod Marker serverless endpoint, preserves official citations and exact
source-revision provenance, and converges removals as well as additions.

## Background

StateCivics owns canonical fiscal identities, observations, crosswalks,
amounts, custody, and publication decisions. ExAIS owns document retrieval.
One StateCivics harvest can feed both planes, but retrieval must consume the
registered custody object rather than harvest again or infer canonical joins
from vector similarity.

The producer contract is pinned to StateCivics commit
`4a8cab323f73f360b4bfec2e361c3737f434c4bb` and retrieval-export contract SHA
`78a3de138cdb534831df034bc66f6a6a2bf7ec3f5d6d573efedf2b50d7a7f32b`.

## Scope

- Add stable connector-owned `source_identity` to ExAIS ingestion.
- Extend multipart upload metadata without bypassing its Marker PDF route.
- Validate and consume deterministic StateCivics desired-state JSONL.
- Verify custody URI, bytes, ledger hash, MIME routing, rights, and lifecycle.
- Prove representative fiscal-table fidelity from one Marker response without
  paying for or comparing against a second extraction.
- Export that already-persisted Markdown back through a hash-bound StateCivics
  handoff; never invoke Marker again for canonical candidate parsing.
- Add a non-production source package and fiscal recall/provenance gate.

## Out Of Scope

- Harvesting or extracting raw fiscal data a second time.
- Resolving fiscal aliases, dimensions, accounts, or crosswalks in retrieval.
- Indexing KanView transaction rows or chart-of-accounts CSVs.
- Creating or mutating the live vector store during implementation.

## Deliverables

- `scripts/release/kansas-fiscal-document-ingest.py`
- `scripts/release/kansas-fiscal-recall-eval.py`
- `scripts/release/kansas-fiscal-marker-handoff.py`
- `packages/svs_common/svs_common/fiscal_marker_handoff.py`
- `instances/ks-state-civics/vector-stores/kansas-fiscal-documents/`
- Multipart and JSON ingestion support for stable source identity/provenance.
- Unit, contract, and disposable-PostgreSQL identity tests.
- A cross-repository proof that passes output from the real StateCivics
  exporter and custody implementation through the ExAIS adapter CLI.

## Acceptance Criteria

- Every `application/pdf` upsert uses `/api/v1/documents/upload` with
  `mode=auto_detect_v1`; tests prohibit direct JSON PDF ingestion.
- Markdown and plain text bypass Marker while preserving the same provenance.
- Repeating an unchanged desired-state manifest produces no document mutation.
- Equal bytes under different logical IDs remain distinct documents.
- A changed revision or citation URL versions the same logical document.
- Restricted, withdrawn, unavailable, corrected, and superseded records remove
  a previously indexed file before any additions are applied.
- Tampered manifests, custody objects, PDF declarations, and target slugs fail
  closed before an API write.
- Recall proof requires relevant content, a public citation, and StateCivics
  logical-document plus source-revision provenance.
- The Marker quality proof pins source bytes, requires expected document
  anchors, and matches nine fiscal rows across three tables from the same
  response used to compute its output digest and structural counts.
- The extraction handoff verifies persisted ExAIS metadata and Markdown against
  the original revision and source hash, emits byte-stable files/JSONL, and
  carries the persisted ingestion interval for honest replay-safe derivation
  lineage. It validates against the StateCivics-owned contract at commit
  `14e54878`.
- The bounded `fiscal_tables_page_aware_v1` profile requests pagination,
  HTML-preserved tables, and retained images in that same Marker job; arbitrary
  operator-supplied Marker options are rejected.
- Live profile proof returned 31 consecutive page delimiters (0–30), 4 images,
  4 matching Markdown image references, and 6 HTML-preserved tables/125
  rows/927 cells with all 9 semantic rows matched.
  The endpoint's `pages` summary was zero, so only the actual delimiters are
  accepted as page evidence.

## Dependencies

- StateCivics migrations 099/100 and the retrieval exporter at the pinned
  producer revision.
- Explicit StateCivics custody mount and exported JSONL manifest.
- Configured ExAIS RunPod Marker and embedding providers.
- A created `kansas-fiscal-documents` vector store ID for apply/proof.

## Verification

```bash
pytest -q \
  tests/test_kansas_fiscal_document_ingest.py \
  tests/test_kansas_fiscal_recall_eval.py \
  tests/test_documents_ingest.py \
  tests/test_ingestion_metadata_refresh.py \
  tests/test_pdf_marker_upload.py \
  tests/test_marker_quality.py \
  tests/test_kansas_fiscal_marker_handoff.py \
  tests/test_instance_source_packages.py \
  tests/test_openapi_contract.py

STATECIVICS_REPO=/statecivics pytest -q \
  tests/integration/test_statecivics_fiscal_export_compat.py

python scripts/release/validate-instance-source-packages.py \
  --instance ks-state-civics --production
```

The final production gate additionally requires a real API `--apply`, an
unchanged repeat run showing zero mutations, persisted Marker provenance, and a
passing live fiscal recall proof.

Bounded quality proof completed 2026-09-04: one configured RunPod Marker job
converted the real 717,996-byte FY2025 Kansas Governor's Budget director
presentation into 32,281 Markdown characters containing 6 structured tables,
125 rows, and 927 cells. Three document anchors and nine pinned fiscal rows
across three tables all matched. This closes the representative parser/table
fidelity gate only; it does not close the API persistence, indexing,
idempotency, or recall gates.

Contract reconciliation completed 2026-09-04: the handoff now emits schema v2
with ExAIS' persisted vector-store-file `created_at` and `completed_at` values,
pins StateCivics commit `14e54878` and contract SHA-256
`a0ff93a4cca17d78f243007861a14f5c6249fb865180c255ca35dd995f617839`,
and names the canonical `operator-source://statecivics-ai` repository. The
production source-package validator passed; 81 focused ExAIS tests and 2 live
cross-repository compatibility tests passed in Docker. No API, Marker, vector,
or production-data write was made.

## Ticket Id Allocation

This ticket was originally authored as WAVE-126 on 2026-09-04 and renumbered to
129 on 2026-09-10. `WAVE-126` had been allocated twice, independently and in
good faith: this fiscal source package on
`feat/wave-126-kansas-fiscal-documents`, and
`WAVE-126-cell-owned-grant-graph-profile.md` on
`chore/dropbox-relocation-paths` a day later. Canonical's 126 is merged and
referenced, so this one moved. 129 was verified free on both branches before
the rename, and 17 cross-references were updated with it.

**ExAIS has no documented next-id rule, and that is the actual defect here.**
`tickets/README.md` says which prefix to use but never says how to choose the
number, so two branches picked the same one without either being careless. The
collision was caught only because both branches happened to be inspected
together.

An audit of the whole store while renumbering found this is not isolated.
**WAVE-005** and **WAVE-123** are each used by two different files, and both
duplicates already exist on `chore/dropbox-relocation-paths`:

- `WAVE-005-v0.9.7-live-postgres-jsonb-portability.md` and
  `WAVE-005-v0.9.7-live-postgres-portability.md`
- `WAVE-123-expert-conversation-sessions-kickoff.md` and
  `WAVE-123-expert-conversation-sessions.md`

So the store has carried duplicate ids for some time. Those two are left alone
here: they are merged, referenced, and renumbering them is a separate change
that should not ride along with a fiscal ticket.

StateCivics solves this explicitly — its `CLAUDE.md` fixes the next id at one
past the highest in `tickets/`, keeps ids contiguous and stable, and forbids
deriving an id from any other store. ExAIS should adopt an equivalent written
rule, and ideally a check that fails on a duplicate id, since a duplicate is
cheap to prevent and expensive to unpick once both branches have references.
Recommend raising that as its own ticket rather than widening this one.

## Notes

- The adapter is dry-run by default and never reads StateCivics or ExAIS
  databases directly.
- API idempotency prevents routine retries from repeating Marker. A process
  failure after Marker returns but before the idempotency transaction commits
  can repeat extraction cost; stable source identity still prevents duplicate
  logical documents. Closing that narrow compute-reservation window is a
  separate request-control change, not grounds to weaken this source contract.
