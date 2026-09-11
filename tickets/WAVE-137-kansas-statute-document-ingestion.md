# WAVE-137: Prepare and ingest retained Kansas statutes with exact coordinates

Status: complete for bounded offline document implementation; live activation pending.
Parent: WAVE-132. Owner: ExAIS. Base: `16a92d8`.

## Problem and owner direction

The completed K.S.A. corpus is available, but ExAIS has no statute source package
or exact-coordinate statute ingestion path. The owner asks to proceed, not wait
on the harvest or migration 111. Implement this bounded document-search path now.
Live ingestion still consumes the existing StateCivics custody-backed retrieval
export; a harvest manifest is not that export and cannot invent eligibility.

## Scope and boundaries

- Add an explicitly scoped `statecivics_statute_markdown_v1` profile using
  `source_text_chunking_profile` and source collection
  `statecivics-kansas-statutes`, retaining mode `markdown_docs_v1`.
  Reject ambiguous simultaneous page/text profile requests.
- Reuse existing ingestion, source identity/version/dedupe, preview, provider,
  usage and index APIs. Generalize the existing fiscal manifest runner with
  explicit `--source-family kansas-statutes`; preserve its default fiscal path.
  New family requires `--vector-store-slug kansas-statutes` and statute
  Markdown records; no source-family inference from a title or keyword.
- Select the existing `voyage_4_docs_1024` embedding profile for this opt-in
  source. No global registry/default change; fail before writes/provider calls
  if that profile is unavailable or privacy rules refuse it. No silent fallback
  to another embedding model. Preserve all other routes.
- Parse actual renderer source/title/body/trailing-metadata boundaries, classify
  empty body and inline History-only regions separately, preserve short bodies,
  and produce bounded exact original slices using natural subsection/paragraph
  boundaries where available. Offsets are Unicode code points, zero-based,
  end-exclusive; lines explicitly LF document-local/one-based. No PDF page
  values, canonical provision IDs, resolved history edges or current-law claims.
- Add a reusable harvest preflight and CLI `kansas-statute-preflight.py` that
  reads all declared files, verifies manifest/file/URL/hash/size bindings and
  path/resource bounds, rejects conflicting duplicates, reconciles exact
  duplicate groups while preserving non-null response-text capture metadata,
  and reports deterministic classifications/chunk totals/history counts.
  The output is local preparation proof, not a replacement canonical exporter.
- The API runner joins eligible approved export records to the reviewed harvest
  by exact official URL and rendered hash. Carry original evidence metadata
  and ordered unresolved history references without modifying source bytes or
  upstream record digests. Export/custody mismatches fail before API effects.
  Profile/provenance changes must not silently deduplicate to stale chunks.
- Before applying, confirm the actual server-computed parser and agreed
  embedding profile through nonpersistent preview. Unsupported servers cannot
  advance applied state. Content exclusions must also remove previously indexed
  versions when necessary, rather than leaving stale searchable text.
- Declare a separate non-production-ready `kansas-statutes` source package with
  the existing retrieval-export contract and pending live manifest/store proof.
  Do not create a live store, activate a source, perform paid bulk indexing,
  alter StateCivics/custody, or implement migration 111/KS-600/650 here.

## Prior art and code anchors

Read before changing:
- `chunking.py`: ParsedChunk, choose_chunker, source_page_chunking_profile,
  statecivics_page_markdown_chunks (preserve fiscal behavior).
- `ingestion.py`: ingest_now, _find_exact_duplicate, _find_version_target,
  _page_coordinate_evidence_context and the shared evidence-context whitelist.
- `vectorization_router.py`: build_ingestion_plan, privacy/provider checks.
- `kansas-fiscal-document-ingest.py`: load_manifest, _validate_record,
  read_custody_object, plan_operations, submit_upsert, apply_operations, main.
- `instance_source_packages.py` and `vector-store-source-package.schema.json`:
  existing declarations/validation; no new package contract.
- Existing page-coordinate, ingestion metadata, fiscal runner, router and source
  package tests. Read the real harvest handoff and machine-readable inventory.
- Upstream read-only `statute_parsers.py:statute_to_markdown` and
  `statute_scraper.py`; do not change the producer.

## Exact file ownership

One coder owns these files serially:
- `packages/svs_common/svs_common/statecivics_statutes.py` (new)
- `packages/svs_common/svs_common/chunking.py`
- `packages/svs_common/svs_common/ingestion.py`
- `packages/svs_common/svs_common/vectorization_router.py`
- `scripts/release/kansas-fiscal-document-ingest.py`
- `scripts/release/kansas-statute-preflight.py` (new)
- `tests/test_statecivics_statutes.py` (new)
- `tests/test_kansas_statute_ingest.py` (new)
- `tests/test_ingestion_page_coordinates.py`
- `tests/test_ingestion_metadata_refresh.py`
- `tests/test_vectorization_plan.py`
- `tests/test_instance_source_packages.py` (only necessary declaration expectations)

Root owns source-package declarations, this ticket, WAVE-132 links, active
ownership addenda/index and operator/instance handoff/proof notes. Independent
QC follows implementation and may write only its review artifact.

## Acceptance and verification

- Execute preflight against all 31,079 real files: verify six duplicate groups,
  72,753 raw/72,733 document-deduplicated unresolved event occurrences, and
  structural body counts before separately handling inline History-only text.
- Real tests cover short K.S.A. 2-303/2-908/2-916, metadata-only larger files,
  inline History-only expiry records, real subsection/long-section boundaries,
  Unicode, exact source slices and no fabricated PDF/legal identities.
- Negative tests: wrong hash/URL/path, duplicate conflicts, unknown body layout,
  source family/profile mismatch, excluded content, unsupported server,
  unavailable/wrong model, wrong export/custody binding and no side effects
  before validation. Prove profile/evidence refresh, unchanged retry/dedupe and
  stale excluded-content removal through existing runner/API seams.
- Run focused Docker tests and prior fiscal/source-package regressions with
  real mounts and zero skipped required corpus tests. Record actual API-path
  parameter proof separately from provider/index doubles. Actual PostgreSQL
  selector proof is required if SQL changes; use a disposable instance only.
- Independent QC must pass before commit/acceptance. Full parent GraphRAG
  acceptance remains open; no new deployed-answer claim.

## Dependencies and next live handoff

The existing document retrieval-export contract is available. Acquisition is
complete. The available upstream checkout does not yet contain migration 111,
KS-600 provision contract or KS-650 entity export, but those are not prerequisites
for this bounded document implementation. The live statute run requires actual
custody revisions and eligible retrieval-export records plus deployment of this
consumer. Never fabricate those records from the harvest to bypass that boundary.

## Implementation proof

Implemented the explicit statute parser/profile and existing API-runner extension,
with the separate [source package](../instances/ks-state-civics/vector-stores/kansas-statutes/README.md).
No global embedding default or canonical graph contract changed.

- [Full-corpus preparation](../.tranche/statecivics-semantic-graph/aligned/wave-137-statute-preflight.json):
  31,079 retained files verified, 83,258 exact-coordinate chunks prepared, six
  duplicate groups reconciled, 72,733 document-deduplicated unresolved history
  occurrences preserved. Empty-body and inline History-only exclusions remain
  separate from structural body counts and legal-validity claims.
- [Implementation and execution proof](../.tranche/statecivics-semantic-graph/aligned/wave-137-implementation-proof.md):
  coder focused 138 passed/zero skipped; root regression 561 passed/zero skipped,
  verified from JUnit; 39 actual disposable PostgreSQL selector assertions passed.
  API request and persistence parameter proofs explicitly identify their doubles.
- [Independent QC](../.tranche/statecivics-semantic-graph/aligned/wave-137-qc.md):
  PASS WITH NOTES. Independently executed 113 tests/zero skipped, the 39 PostgreSQL
  assertions and full-corpus exact-slice coverage with no uncovered non-whitespace.

The source package stays `productionReady: false`, with graph disabled and live
store/export proof pending. No deployment, paid embedding or live index mutation
was performed. WAVE-132/133–136 retain their separate acceptance requirements.
