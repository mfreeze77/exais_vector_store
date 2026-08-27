# WAVE-111 Kansas Court Decisions Corpus Ingestion

## Goal

Build a resumable ingestion lane for the Kansas court decisions corpus at
`C:\Users\mfrie\Ai_Projects\ksa-diff-collector-main\data\raw\kscourts-decisions`
so it can become a real ExAIS vector store with legal metadata, searchable
citations, and a later GraphRAG-ready citation graph.

## Background

The source folder contains a large court-decision PDF corpus:

- `16,728` PDF files under `pdfs/`
- about `1.60 GB` of PDFs
- manifest files: `decisions_manifest.csv` and
  `decisions_manifest.input-backup.csv`
- courts: `12,501` Court of Appeals decisions and `4,227` Supreme Court
  decisions
- publication status: `7,836` Published and `8,892` Unpublished decisions
- date range observed in folder layout: `1986` through `2026`

The manifest already carries important legal metadata: `document_id`,
`docket_number`, `decision_date`, `court`, `status`, `title`, `filename`,
`pdf_url`, `saved_path`, `bytes`, `sha256`, and download status.

ExAIS already has the core ingestion surfaces:

- `/api/v1/documents/ingest` for text or Markdown payloads.
- `/api/v1/documents/upload` for multipart files.
- Raw PDF upload routes can call the configured RunPod Marker endpoint, store
  the original PDF source artifact, convert to Markdown, and ingest as
  `pdf_markdown_external_v1`.
- `scripts/release/vectorize-folder.py` can bulk ingest Markdown files, but it
  does not read this manifest or extract PDF text.

Sampling shows normal Kansas court PDFs are text-extractable locally with
`pypdf`. One large older PDF hit an AES dependency failure in local sampling,
so the importer must expect encrypted/scanned/problem PDFs and handle fallbacks
without stopping the full run.

## Scope

- Add a corpus-specific bulk ingestion script for
  `decisions_manifest.csv`.
- Create or reuse a vector store named `Kansas Court Decisions`.
- Read the manifest as the source of truth rather than walking PDFs blindly.
- Resolve `saved_path` relative to
  `C:\Users\mfrie\Ai_Projects\ksa-diff-collector-main`.
- Extract PDF text locally first and convert it to Markdown-like text suitable
  for `mode=pdf_markdown_external_v1`.
- Preserve legal metadata in document attributes:
  `document_id`, `docket_number`, `decision_date`, `court`, `status`, `title`,
  `pdf_url`, `source_index`, `saved_path`, `bytes`, `sha256`, and source
  collection name.
- Submit extracted text to `/api/v1/documents/ingest` with
  `mode=pdf_markdown_external_v1`, `source_uri` pointing to the original PDF URL
  or source path, and `security_level=1` unless overridden.
- Use `force_async=true` for large extracted documents so the worker owns
  indexing.
- Track progress in a resumable local state file containing at least source row
  identity, PDF path, SHA256, extraction status, ingest job ID or document ID,
  vector-store file ID, timestamps, retry count, and error message.
- Add idempotency keys derived from stable source identity and SHA256 so retries
  do not create duplicate documents.
- Add dry-run inventory mode for count, size, years, courts, publication
  status, missing files, duplicate hashes, over-limit files, and extraction
  viability sample.
- Add a pilot mode that ingests a bounded sample first, for example 25 to 100
  decisions across court/status/year buckets.
- Add Marker fallback only for PDFs that cannot be locally extracted or have
  low extracted text volume. Do not send the whole corpus to remote Marker by
  default.
- Surface fallback counts and failures clearly so remote processing cost and
  throughput are visible.
- Add search proof queries after pilot ingestion, including queries by title,
  docket number, court/status filters, and substantive legal terms.
- Keep the loader Docker-friendly: it must be runnable from the repo against
  the existing local Compose cell and should support a read-only mounted source
  corpus path for future VPS or one-shot importer use.

## Out Of Scope

- Implementing GraphRAG orchestration.
- Building a graph database or graph query API.
- Running full-corpus ingestion until a real embedding provider is selected.
- Treating `hash_mock` embedding proof as production semantic quality.
- Re-downloading the Kansas court corpus.
- Mutating source files under `ksa-diff-collector-main`.
- Replacing the existing Marker PDF conversion route.
- Legal advice, legal classification, or citation validity guarantees.

## Deliverables

- A resumable ingestion script, preferably under
  `scripts/release/kscourts-ingest.py`.
- Optional helper documentation under `docs/` or this ticket describing the
  operator command sequence.
- A small local progress/state file path convention, kept out of source control,
  such as `.release/cells/local/kscourts-ingest/progress.jsonl`.
- Pilot proof output showing created/reused vector store ID, submitted count,
  completed count, failed count, chunk count, indexed chunk count, and search
  results.
- A failure report for PDFs that need Marker fallback or manual review.
- A follow-up ticket draft for citation/entity extraction and GraphRAG readiness
  if pilot search proves the corpus is worth promoting.

## Acceptance Criteria

- [x] Dry-run inventory reads `decisions_manifest.csv` and reports counts that
  match the current corpus shape: `16,728` PDFs and about `1.60 GB`.
- [x] Dry-run reports court, publication-status, and year distributions without
  reading every PDF byte.
- [x] The importer refuses to run full-corpus mode while the target cell is
  using `DEFAULT_EMBEDDING_PROVIDER=hash_mock`, unless an explicit
  `--allow-hash-mock` proof flag is provided.
- [x] Pilot mode creates or reuses a `Kansas Court Decisions` vector store.
- [x] Pilot mode extracts text locally for normal text PDFs and preserves the
  original PDF path/URL/hash in metadata.
- [x] Pilot mode submits documents through the real ExAIS API, not direct DB
  writes.
- [x] Pilot ingestion is resumable: rerunning the same pilot does not duplicate
  already-successful manifest rows.
- [x] Failed, encrypted, scanned, or low-text PDFs are recorded separately and
  can be retried through Marker fallback.
- [x] Search proof returns relevant cited results for at least one docket/title
  query and one substantive legal query.
- [x] Metadata filters can distinguish Supreme Court vs. Court of Appeals and
  Published vs. Unpublished pilot results.
- [x] The importer prints a clear cost/throughput warning before any remote
  Marker fallback batch larger than the configured pilot limit.
- [x] The full-corpus runbook documents expected runtime, worker scale,
  embedding-provider requirement, progress/resume behavior, and cleanup steps.

## Dependencies

- Running ExAIS Docker cell.
- Operator/admin bearer key with `documents:write`, `vector_stores:write`,
  `vector_stores:read`, and `retrieval:read`.
- Source corpus at
  `C:\Users\mfrie\Ai_Projects\ksa-diff-collector-main\data\raw\kscourts-decisions`.
- Local or containerized PDF text extraction support, including a fallback for
  encrypted PDFs that require `cryptography`.
- Real embedding provider configuration before production-scale ingestion.
- Optional RunPod Marker credentials for fallback PDFs.

## Verification

Dry-run inventory:

```powershell
python scripts\release\kscourts-ingest.py `
  --cell local `
  --source-root C:\Users\mfrie\Ai_Projects\ksa-diff-collector-main `
  --manifest data\raw\kscourts-decisions\decisions_manifest.csv `
  --dry-run
```

Pilot ingestion:

```powershell
python scripts\release\kscourts-ingest.py `
  --cell local `
  --source-root C:\Users\mfrie\Ai_Projects\ksa-diff-collector-main `
  --manifest data\raw\kscourts-decisions\decisions_manifest.csv `
  --vector-store-name "Kansas Court Decisions" `
  --pilot-limit 50 `
  --state .release\cells\local\kscourts-ingest\progress.jsonl
```

Progress proof:

```powershell
docker-compose --env-file .release\cells\local\.env.cell `
  --env-file .release\cells\local\.env.images `
  -f infra\docker\compose.cell.yml `
  -p exais-vector-store-local ps
```

Search proof should include:

- title or docket query
- substantive legal query
- court/status-filtered query
- citation/evidence-card inspection through the admin UI or equivalent API
  response

## Notes

- The safe first pass is text-first extraction plus JSON ingestion as
  `pdf_markdown_external_v1`; use Marker as a fallback, not as the default for
  all `16,728` PDFs.
- This corpus is a strong future GraphRAG candidate because legal decisions
  naturally form citation and authority graphs. This ticket should preserve
  enough metadata and text to make citation extraction practical later, but it
  should not build the graph in this wave.
- The current local cell was observed with `DEFAULT_EMBEDDING_PROVIDER=hash_mock`.
  That is acceptable for plumbing proof only. Full legal retrieval quality needs
  a real embedding provider before indexing the whole corpus.

## Pilot Proof 2026-08-08

Implemented `scripts/release/kscourts-ingest.py` and patched
`/api/v1/documents/ingest` idempotency handling so async ingest restores RLS
context after enqueue commits and before idempotency storage.

Local Docker cell:

- API image repinned to
  `localhost:5000/expertaiservices/exai-vector-store-api@sha256:601b4e7ddcacbcc28f63a7cc79cdddb5e3942c3d8b13f03c2a950233ec272448`.
- `DEFAULT_EMBEDDING_PROVIDER=hash_mock`; this proof is plumbing only, not
  production semantic quality.
- `Kansas Court Decisions` vector store:
  `vs_6427c56d17a4434e802c5e7f`.
- Marker fallback is opt-in with `--marker-fallback-limit`; the importer prints
  `REMOTE_MARKER_FALLBACK_WARNING` before any fallback-enabled run, loads only
  configured Marker env names from the cell/process, preserves Kansas legal
  metadata in the `/documents/ingest` payload, and records `marker_failed` rows
  in the failure report if remote conversion cannot finish.
- GraphRAG readiness follow-up drafted as
  `tickets/WAVE-112-kansas-court-decisions-graphrag-readiness.md`.

Verified commands:

```powershell
python scripts\release\kscourts-ingest.py --cell local --dry-run
python scripts\release\kscourts-ingest.py --cell local --full-corpus --skip-search-proof
python scripts\release\kscourts-ingest.py --cell local --pilot-limit 32 --state .release\cells\local\kscourts-ingest\progress.jsonl --vector-store-name "Kansas Court Decisions"
python scripts\release\kscourts-ingest.py --cell local --pilot-limit 32 --state .release\cells\local\kscourts-ingest\progress.jsonl --vector-store-name "Kansas Court Decisions" --skip-search-proof
python -m py_compile scripts\release\kscourts-ingest.py
```

Observed proof:

- Dry-run inventory: `16,728` PDFs, `1.602` GB, `0` missing PDFs,
  `12,501` Court of Appeals, `4,227` Supreme Court, `7,836` Published,
  `8,892` Unpublished, years `1986` through `2026`.
- Full-corpus mode refused while `DEFAULT_EMBEDDING_PROVIDER=hash_mock` unless
  `--allow-hash-mock` is provided.
- Pilot sample selected 32 rows across court/status/year buckets.
- Indexed result: `29` documents, `248` active chunks, `248` indexed chunks,
  `0` active jobs, `0` failed jobs.
- Resume proof: rerunning the same `--pilot-limit 32` submitted `0` new rows
  and kept the vector store at `29` documents / `248` indexed chunks.
- Failure report:
  `.release\cells\local\kscourts-ingest\failures.json`; current failure count
  is `3`, all local `pypdf` AES extraction failures requiring a bounded
  `--retry-failed --marker-fallback-limit N` retry or another PDF extraction
  dependency path. Live Marker fallback was not executed because this local cell
  proof did not include remote Marker credentials or an approved remote-cost run.
- Search proof returned top hits for title, filtered docket, substantive legal
  terms, Court of Appeals/Published filter, Supreme Court filter, and
  Unpublished filter.

Full-corpus runbook:

1. Configure a real embedding provider before full ingestion; do not use
   `hash_mock` except for plumbing proof.
2. Ensure a seeded target knowledge base exists; local pilot used `kb_dev`.
   A dedicated Kansas civics VPS cell should seed its own `kb_ks_civics` or
   equivalent before running this script with `--knowledge-base-id`.
3. Keep the source corpus read-only and mount or point `--source-root` at the
   collector repo. The script only writes local state under `.release`.
4. Start with a bounded pilot, then increase `--pilot-limit` in tranches until
   extraction/fallback rates are understood.
5. For full corpus, run with `--full-corpus` only after selecting the provider:
   `python scripts\release\kscourts-ingest.py --cell local --full-corpus --allow-hash-mock`
   is allowed only for plumbing proof; omit `--allow-hash-mock` with a real
   provider.
6. Expected full scale from the pilot is roughly `16,728` documents and on the
   order of `140,000` chunks, depending on extraction text volume and chunking.
   Runtime will be dominated by embedding throughput and worker count; scale
   workers before the full run.
7. Resume behavior is state plus SHA reconciliation against
   `vector_store_files`; reruns skip already-indexed rows and append proof
   events to `.release\cells\<cell>\kscourts-ingest\progress.jsonl`.
8. Cleanup is deleting the target vector store through the API, removing the
   local state folder if a fresh pilot is desired, and preserving
   `failures.json` for fallback planning.
