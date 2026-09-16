# WAVE-118 Topeka Municipal Code Source Seeding

## Summary

Create reproducible Topeka source pipelines for the `ks-state-civics` instance,
with quality-gated structured artifacts feeding collection-specific vector
stores, cited GraphRAG and the StateCivics jurisdiction document UI. Reuse the
retained codified TMC sections, official ordinance PDFs and their extractions.

## 2026-09-15 owner direction: master collections and the KS-539 handoff

Status of this extension: specified; implementation and activation pending.
The prior combined-store receipts below remain historical evidence. They do
not prove the new collection split, additional sources or jurisdiction UI
handoff. This direction concerns Topeka source/document publication; the
paused Kansas fiscal/appropriations work is not resumed by it.

Execution brief: [ExAIS-only manager/worker handoff](../runbooks/topeka-source-pipeline-manager-handoff.md).
It assigns no StateCivics repository or deployment work. Deliver the validated
schema and starter artifact release first so the StateCivics developer can
implement that consumer independently.

The product acceptance ticket is
[StateCivics KS-539](https://github.com/mfreeze77/state-civics-ai/blob/main/tickets/KS-539-publish-complete-topeka-meeting-corpus.md).
WAVE-117 and the [jurisdiction playbook](../docs/JURISDICTION_VECTOR_STORE_PLAYBOOK.md)
already establish source packages and artifact quality before vectorization.
Extend those paths rather than building a second source store or extractor
inside StateCivics.

### Collection granularity — explicit owner correction

One vector store belongs to one registered master collection. A unique PDF
or page URL is a member document, NEVER a reason to create another store.
Collection boundaries are the publisher's master lists/categories, not the
number of links, files, source pages, or download attempts.

| Master collection | Discovery source | Member records |
| --- | --- | --- |
| Topeka Municipal Code | `https://topeka.municipal.codes/TMC` | Code sections/subsections and source structure, including Title 18 and local amendments |
| Topeka ordinances | `https://topeka.gov/community/ordinances/index.php`, Ordinances category | Individual ordinary ordinance PDFs |
| Topeka charter ordinances | Same page, Charter Ordinances category | Individual charter ordinance PDFs |
| Topeka resolutions | `https://topeka.gov/community/resolutions/index.php` | Individual resolutions across the library's year categories |

Charter ordinances and resolutions each get their own vector store. The
`#undefined` UI fragment is not a source identity or an additional store.
Two categories on the same page remain distinct collections; pagination/year
navigation does not split a collection into per-page/per-year stores. A code
hub linking an already-known amendment adds a source relationship without
minting another document/store for those same bytes.

The owner's concrete member-document examples must be retained in the
collection-routing acceptance test:

| Individual PDF | Parent vector store |
| --- | --- |
| `https://s3.us-east-1.amazonaws.com/files.topeka.gov/community/resolutions/2026/Resolution09749.pdf` | Topeka Resolutions |
| `https://files.topeka.gov/community/ordinances/charter/CharterOrdinance126.pdf` | Topeka Charter Ordinances |

Each PDF is downloaded/versioned and extracted into structured content by its
parent collection's pipeline. Neither creates a new store or bespoke pipeline.
Their released content feeds both retrieval and the Topeka document UI.

Assign explicit collection IDs, vector-store IDs and WAVE-117 source packages.
Additional master collections (meeting-document collections by body, budgets,
plans, applications, GIS and other registered sources) must declare their
boundaries before activation. Reuse shared connector code across collections.
Do not generate collections from arbitrary discovered links or search keywords.

The existing `vs_d4185d1004604f08a55299fa` combines TMC and ordinance data.
Prepare its split from the retained manifests, including a destination for
the unnumbered STO document; it must not disappear because it is not a numbered
ordinary ordinance. Reconcile all records, verify destination retrieval and
citations, then switch routing. Keep the old store available for rollback;
this ticket update does not migrate or delete it.

### One released artifact feeds both products

```text
master collection -> discover/download/version -> extract and structure
  -> validate source content, schema, coverage and evidence
  -> immutable clean JSON/JSONL + readable text + original-file/citation manifest
       -> ExAIS API ingest -> semantic/vector index and cited graph/lens search
       -> StateCivics import -> Topeka document reader, FTS and scoped agent context
```

- Inventory every PDF and supported non-PDF item within the declared collection
  scope. Preserve inline agenda HTML, spreadsheets, tables, maps and exhibits;
  title-only discovery does not count as extraction. Record missing/failed/
  visual/review-needed outcomes and reconcile all discovered records to them.
- Reuse validated raw captures and existing Marker results by source identity
  and hash. New/changed PDFs use the configured bounded remote extraction path.
  Do not re-spend on unchanged verified files or blindly trust an existing path.
- Preserve original bytes/hash, extracted-content hash, structured payload hash,
  source/extractor/schema versions, document identity/version, timestamps and
  evidenced page/block/table references. JSON must contain usable content, not
  only a filename/URL. Missing page coordinates remain explicit; do not infer
  PDF page numbers from Markdown line numbers or apparent headings.
- Retain existing structured TMC blocks, sections, definitions, tables and
  ordinance history. Keep proposed/adopted/superseded status, known effective
  dates, local amendments and incorporated editions distinct. Extracted text
  is not automatically a reviewed legal fact. Resolutions can record operative
  approvals/funding decisions and must not all be labeled mere commentary.
- Derive graph nodes/edges with stable source identities and evidence references;
  validate graph artifacts before graph loading. An empty/unavailable graph
  lens must not be reported as graph-backed retrieval. Pin embedding profile
  and routing per target store through the existing guards.
- Publish a versioned artifact manifest in durable storage with backup and
  portable pointers. Both consumers record the same artifact release and
  document/payload hashes. StateCivics imports the released source data through
  its supported publication boundary under `ks:city:topeka`, not via direct
  ExAIS database access or reconstruction from search chunks.
- Keep extraction/release, vector indexing, graph readiness and local publication
  statuses independent. The Topeka reader can display validated documents while
  embedding/graph jobs are pending. A failed graph build cannot erase usable
  document content. Changes retain earlier versions and identify stale consumers.
- The document/matter model must support cross-meeting applications, staff
  recommendations, hearings, commission votes, council action and final
  instruments. Meeting-date body membership and late minutes/decisions are
  evidenced inputs, not values guessed from the current roster or event title.

### Acceptance for the extension

- A manifest-driven split assigns every retained item to its declared master
  collection with no per-PDF stores, unexplained omissions or duplicate active
  versions. Counts are derived from the manifests and actual destination runs.
- Audit the reusable inputs before publishing. KS-539's measured inventory is
  2,702 TMC section records and 364 retained PDFs (322 numbered ordinances,
  41 charter ordinances, one STO). All raw PDF hashes matched on 2026-09-15;
  the STO Markdown hash differs from its extraction manifest. Resolve and
  document that transformation/provenance before accepting it. The current city
  library comparison is not yet a complete added/changed/removed worklist.
- Through real ExAIS and StateCivics entrypoints, the same document/version/hash
  is retrievable, opens in the Topeka reader, has working evidence references
  and reaches scoped meeting context. Test fresh and repair agent paths;
  KS-539 records the currently missing fresh-path tools and packet-discard bug.
- Prove one real Planning Commission matter end to end and repeat on another
  body. Account for every attachment and link only evidenced outcomes; unknown
  or pending decisions remain explicit. A source registration alone is no proof.
- Exercise a changed source, a late-published document and repeat processing:
  old versions survive, changed consumers refresh, unchanged work is reused,
  duplicate documents are not created, and pending/failed work is reported.
- Report artifact/code versions, collection assignments, acquisition/extraction
  coverage, actual vector/graph results and StateCivics UI/search/context proof.
  Package configuration or this documentation commit is not an execution proof.

## Background

The Topeka corpus needs both current codified code and ordinance history. The codified code host provides current section text, while the City of Topeka Ordinances page provides official PDFs for amendments, adoptions, repeals, and legislative trail. The existing scraper ZIP has parser and graph output value. Plain HTTP is blocked by publisher protection, but stock Playwright Chromium can load real root and section content. The package must stay fail-closed until the full corpus crawl, source manifests, API ingestion, graph load, and recall proof are complete.

## Completed Prework

- Source packages are present for `topeka-codified-code` and `topeka-ordinances`.
- The original `topeka-code-scraper-v0.1.1.zip` is preserved under the codified-code seed folder.
- The vendored scraper has `--fetcher playwright`, rendered HTML archive support, network archive support, challenge-only detection, and zero-section fail-closed behavior.
- The scraper emits `citation-url-map.jsonl` for pages, sections, and definitions.
- Codified-code graph nodes and graph-edge properties preserve `source_url` and `citation_url`.
- Direct Playwright section proof for `https://topeka.municipal.codes/TMC/18.55.010` produced one section, 326 definitions, 336 graph nodes, 343 graph edges, 17 numbered ordinance-history rows, and 328 citation URL rows after ordinance-history extraction rejected non-number word fragments.
- Source-package validation passes with three KS Civics packages while both Topeka sources remain `productionReady: false`.

## Scope

- Run and harden the Playwright codified-code crawler for the full TMC corpus, starting from `/TMC` but avoiding false success on title/container-only pages.
- Preserve rendered HTML, network logs, manifest files, `citation-url-map.jsonl`, and graph JSONL files in the codified-code seed layout.
- Implement the official Topeka ordinance PDF collector.
- Implement API-only ingestion using the master-collection store boundaries
  above. The combined `topeka-municipal-code` store in earlier receipts is the
  historical arrangement to reconcile, not the target for new collection work.
- Implement graph extraction/loading/eval for TMC references, definitions, ordinance history, and ordinance-to-section relationships.
- Add recall tests covering current-code questions and amendment-history questions.

## Out Of Scope

- Cloudflare evasion or anti-bot bypass code in this repository.
- Direct writes to Postgres, Qdrant, MinIO, or OpenSearch.
- Treating ordinance PDFs as a complete replacement for the codified code.
- Treating codified code as legally complete without ordinance provenance.

## Deliverables

- `instances/ks-state-civics/vector-stores/topeka-municipal-code/store.yaml`
- `instances/ks-state-civics/vector-stores/topeka-municipal-code/sources/topeka-codified-code/source.yaml`
- `instances/ks-state-civics/vector-stores/topeka-municipal-code/sources/topeka-ordinances/source.yaml`
- `docs/TOPEKA_MUNICIPAL_CODE_SEEDING_SPEC.md`
- Full codified-code seed artifacts under `instances/ks-state-civics/vector-stores/topeka-municipal-code/sources/topeka-codified-code/seed/` or the configured object-store URI.
- Full ordinance PDF seed artifacts under `instances/ks-state-civics/vector-stores/topeka-municipal-code/sources/topeka-ordinances/seed/` or the configured object-store URI.
- `scripts/release/topeka-code-ingest.py`
- `scripts/release/topeka-code-combine-batches.py`
- `scripts/release/topeka-ordinances-collect.py`
- `scripts/release/topeka-ordinance-pdf-extract.py`
- `scripts/release/topeka-ordinance-pdf-ingest.py`
- `scripts/release/topeka-code-graphrag-extract.py`
- `scripts/release/topeka-code-graphrag-load.py`
- `scripts/release/topeka-code-graphrag-eval.py`
- `scripts/release/topeka-code-recall-eval.py`
- `scripts/release/topeka-ordinance-recall-eval.py`

## Implementation Notes 2026-08-27

- Added offline-testable Topeka release scripts for official ordinance PDF collection, codified-code API ingestion, ordinance markdown/PDF API ingestion, GraphRAG extraction, GraphRAG load/eval, and recall eval.
- The ingestion scripts use ExAIS API document ingestion and keep `source_uri` mapped to section `citation_url` or official ordinance `pdf_url`.
- The Topeka API scripts now honor `--api-transport` for host curl, API-container, and Docker-network calls; source-package commands use Docker-network transport for live cell execution.
- The ordinance PDF ingestion script does not run Marker locally; it consumes precomputed markdown from the existing external RunPod Marker/operator extraction path.
- The GraphRAG loader validates artifacts and submits through the ExAIS vector-store graph API path. Direct Postgres graph writes remain forbidden for Topeka source packages.
- The codified-code parser now rejects non-number word fragments as ordinance history and preserves distinct ordinance-history graph edges by ordinance/section/date/raw value.
- Bounded live proof on `https://topeka.municipal.codes/TMC/18.55.010` produced 1 section, 326 definitions, 17 numbered ordinance-history rows, 336 graph nodes, 343 graph edges, and 328 citation URL rows.
- Bounded live ordinance collector proof against the official City of Topeka ordinance page with `--limit 2` wrote two ordinance PDF records with no failures.
- Topeka source packages remain `productionReady: false`; the local pilot vector store is `vs_268b119a2cd84b568af62155` and should not be used as the caller-facing full Topeka store.
- Operator URL manifest `seed/raw/topeka_municipal_code_urls.csv` is preserved and wired into the scraper. Manifest-only Playwright fetching of `Section`/`Subsection` rows now bypasses root discovery and emits CSV-derived `CONTAINS` graph hierarchy.
- Isolated Playwright browser contexts materially improve batch acquisition but do not fully defeat publisher challenge behavior: 2026-08-28 proof fetched 31 of the first 50 section URLs and failed 19 challenge pages.
- Current operator rule: generate JSON/JSONL artifacts and run the artifact quality gate only. Do not ingest/vectorize additional Topeka records until artifact quality passes.
- Operator-owned acquisition routes can now plug in through `--capture-manifest` by providing authorized HTML captures. The route implementation, cookies, credentials, proxy logic, captcha solving, stealth plugins, and challenge bypass code remain out of scope for this repository.
- Public-access/export escalation is documented in `docs/TOPEKA_PUBLIC_LAW_ACCESS_PACKET.md`, and the artifact quality gate now emits complete worklists for missing URLs and capture failures.
- Larger stock-Playwright proof on 2026-08-28 fetched 141 of the first 200 section/subsection URLs and failed 59 publisher-challenge pages. The artifact gate reported `vectorization_allowed: false`, 5.218 percent coverage, 2,561 missing required URLs, and zero section text/citation issues on fetched pages.
- Operator provided a Decodo Web Scraping API credential as a local runtime secret. The codified-code scraper now supports `--fetcher decodo`, defaulting to Decodo's minimal universal request after live proof showed Topeka HTML succeeds without explicit JS/proxy parameters while `headless: html` and `proxy_pool: standard` returned provider status 613. The route still writes only JSON/JSONL/raw/network artifacts for the existing quality gate. The Decodo credential remains env-only and must not be committed or written into artifacts.
- The scraper now supports `--url-list-offset` and `--url-list-limit` so paid acquisition can run in 200-page windows without discarding the full URL manifest hierarchy needed for `CONTAINS` GraphRAG edges.
- WAVE-119 adds a projection-only workbench lane from saved Topeka artifacts to stable canonical components, component relations, and title/chapter/appendix/article slices. This keeps future legislative redline/import work separate from vectorization and ingestion.
- Decodo batch window proof on 2026-08-28 reached 600 fetched pages across batches 001-003 with zero failed URLs. Batch 003 at offset 400/limit 200 produced 200 sections, 55 definitions, 3,313 graph nodes, 3,438 graph edges, complete section citation coverage, zero quality worklist rows, and `vectorization_allowed: true` for that 200-page window only.
- Full Decodo batch acquisition proof on 2026-08-28 reached all 2,702 required Section/Subsection fetch URLs across batches 001-014 with zero failed URLs, zero missing URLs, 2,702 raw HTML evidence files, 2,702 network evidence files, 2,702 section artifacts, 980 definition artifacts, and zero quality worklist rows. This remains artifact-only proof; no vectorization, ingestion, ExAIS API writes, Qdrant, Postgres, MinIO, OpenSearch, or graph writes were run.
- Full batch consolidation proof on 2026-08-28 used `scripts/release/topeka-code-combine-batches.py` to create `.tmp/topeka-decodo-window-batches-20260827220454/combined-full-corpus-20260828-v2`. The combined source output has 2,702 sections, 980 definitions, 4,606 graph nodes, 6,909 deduped graph edges, 6,384 citation URL rows, 3,204 URL-manifest rows, 2,702 expected fetch URLs, 2,702 raw HTML files, and 2,702 network files.
- Combined full-corpus artifact quality passed with 100 percent coverage, zero missing URLs, zero failed URLs, zero duplicate section IDs/URLs, zero empty-text sections, zero missing section citation URLs, and zero worklist rows. Combined graph edge types are `CONTAINS=3,203`, `DEFINES=980`, and `HAS_ORDINANCE_HISTORY=2,726`; the current parsed source artifacts produced zero `REFERENCES` edges.
- Full codified-code API ingestion proof on 2026-08-28 loaded the clean caller-facing vector store `vs_d4185d1004604f08a55299fa` (`City of Topeka Municipal Code`) for `https://topks.statecivics.ai/local`. The API reported 2,702 completed files, 0 failed files, 3,469,765 usage bytes, and database proof showed 2,702 documents, 2,702 distinct official source URLs, 2,999 active chunks, and 2,999 indexed chunks.
- Recall proof on 2026-08-28 passed 10/10 live Topeka searches against `vs_d4185d1004604f08a55299fa`: five current-code checks and five amendment-history checks, all with public citations. Proof artifact: `.release/cells/ks-state-civics/evals/topeka-code-recall-20260828-012315.json`.
- The original pilot store `vs_268b119a2cd84b568af62155` now contains partial data and should not be used as the full Topeka caller-facing store. Attempting to replace its one-section proof exposed a chunk deactivation RLS bug; the full load used a clean store and the codified-code ingest script now scopes idempotency keys by `vector_store_id` so the same public source can be loaded into multiple stores.
- Deeper API search proof on 2026-08-28 ran 24 Topeka legal-search queries against `vs_d4185d1004604f08a55299fa` with zero API errors after route hardening. `19/24` passed a basic citation/content gate and `5/24` were marked for review because broad phrasing needed tighter legal terms or caller-side answer framing. Proof artifact: `.release/cells/ks-state-civics/evals/topeka-code-deep-search-20260828.json`.
- Deep search exposed a route-level bug: with `SVS_QUERY_PLANNER_PROFILE_ID=ks_civics_legal_v1`, Topeka ordinance numbers and dates could be interpreted as Kansas court-decision filters, and zero-row filtered profile resolution could fall back to the unavailable `runpod_serverless_or_local` embedding provider. The API now disables the Kansas court planner for non-court vector-store corpora such as `topeka_municipal_code`, and store-scoped searches do not fall back to private embedding profiles when no indexed chunks match planned filters.
- The `https://topks.statecivics.ai/local` surface is an intended consumer route recorded in metadata. It is not yet wired or DNS-verified from this machine; current proof is against the ExAIS API in the local KS Civics Docker cell.
- Seed-folder audit on 2026-08-28 found the ordinance source package had only the committed skeleton while the downloaded ordinance PDFs lived in a temp run. The full ordinance seed was promoted into `instances/ks-state-civics/vector-stores/topeka-municipal-code/sources/topeka-ordinances/seed/`: `364` official PDFs, `364` Marker Markdown extractions, `ordinances.jsonl`, `ordinance-extractions.jsonl`, `ordinance-extraction-report.json`, and `citation-url-map.jsonl`. Raw PDFs and extracted Markdown remain in the instance seed folder for reproducibility but are ignored by Git.
- Official ordinance PDF extraction proof on 2026-08-28 produced `364/364` Markdown artifacts with `0` failures through the existing external RunPod Marker/operator path. No local Marker install, Qdrant, Postgres, MinIO, OpenSearch, or graph writes were used by the extraction stage.
- Official ordinance PDF API ingestion proof on 2026-08-28 loaded all `364` ordinance PDF Markdown documents into clean vector store `vs_d4185d1004604f08a55299fa`. Database proof showed combined store totals of `3,066` documents, `3,066` distinct official source URLs, `6,153` active chunks, and `6,153` indexed chunks, including `364` ordinance documents and `3,154` ordinance chunks.
- The ordinance ingest path now preserves charter ordinance filenames as `CharterOrdinance{number}.md`, keeps unnumbered records such as `STO.pdf` out of the `ordinance_number` field, stores a separate `source_record_id`, and uses a vector-store/source payload fingerprint idempotency key. The shared ingestion service now refreshes existing document and vector-store-file metadata on idempotent re-ingest, which fixed stale citation/filename/source metadata in the local store.
- Ordinance-specific recall proof on 2026-08-28 passed `5/5` live ExAIS API searches with official PDF citations. Proof artifact: `.release/cells/ks-state-civics/evals/topeka-ordinance-recall-20260828.json`.
- Aggregate Topeka GraphRAG artifact extraction/eval proof on 2026-08-28 now passes artifact-level gates with `4,969` nodes, `10,167` edges, `2,646` parsed internal `REFERENCES` edges, `2,726` `HAS_ORDINANCE_HISTORY` edges, `536` ordinance-to-section edges, no dangling edges, and citation URLs on all edges. WAVE-122 added the ExAIS graph load/search API handler and locally loaded the graph through `POST /v1/vector_stores/vs_d4185d1004604f08a55299fa/graph`.

## Acceptance Criteria

- The source-package validator passes for `ks-state-civics`.
- Both Topeka source packages remain `productionReady: false` until production/VPS promotion gates complete. Official ordinance PDF extraction/local API ingestion, artifact-level graph proof, local graph API load, and local graph-lens search proof completed on 2026-08-28.
- Codified-code artifact generation and quality check run before vectorization.
- Operator capture import parses supplied HTML captures through the same JSON artifact, citation, graph, and quality-gate path as live fetching.
- Quality-gate worklists identify every missing required URL, crawl failure, unexpected section URL, and section-level text/citation issue.
- Full codified-code crawl writes nonempty `sections.jsonl`, `definitions.jsonl`, `nodes.jsonl`, `edges.jsonl`, `citation-url-map.jsonl`, `manifest.json`, and `crawl_report.json`.
- Full codified-code crawl stores rendered HTML and network proof for fetched pages.
- Full codified-code crawl fails closed on zero pages or zero sections.
- Full codified-code crawl records per-page failures and treats challenge-only pages as failures, not successful source records.
- `citation-url-map.jsonl` has a section row for every section document to be ingested, and every section row has `source_url` and `citation_url`.
- The ordinance collector writes a nonempty `ordinances.jsonl` with stable identity fields, SHA-256, PDF URL, and saved path.
- API ingestion creates or finds the real Topeka vector store and writes source records with clickable citations.
- Graph artifact proof includes `CONTAINS`, `REFERENCES`, `DEFINES`, `HAS_ORDINANCE_HISTORY`, and at least one ordinance-to-section edge when data supports it.
- Local graph load/search is complete when the supported ExAIS municipal-code graph API handler is verified through the caller-facing search route; VPS/public-route proof remains a separate production gate.
- GraphRAG rows preserve `source_url`/`citation_url` so graph-expanded context can render clickable citations.
- Recall proof includes at least five current-code questions and five amendment-history questions.
- Topeka vector-store search does not inherit Kansas court-decision query filters.
- Store-scoped searches with no matching indexed chunks do not fall back to an unavailable embedding provider.

## Dependencies

- WAVE-117 source-package contract and seed layout.
- Existing RunPod Marker endpoint for hard PDF extraction.
- Operator-created real vector store ID before production seeding.
- Playwright runtime with Chromium matching the pinned scraper browser dependency.

## Implementation Order

1. Run a bounded Playwright full-corpus discovery crawl and inspect skipped/challenge-only URLs.
2. Produce codified-code seed artifacts and verify section count, citation URL count, graph node/edge count, and failure list.
3. Build and test the official ordinance PDF collector and manifest.
4. Full-corpus gate: keep `productionReady: false` until codified-code acquisition, ordinance PDF extraction/ingestion, graph load/search, broad recall, and production promotion gates are run and accepted. As of WAVE-122, the local graph load/search gate has passed; production promotion remains separate.
5. Implement codified-code and ordinance API ingestion, using `citation_url`/`pdf_url` as document `source_uri`.
6. Implement graph load/eval proof for codified references, definitions, ordinance history, and ordinance-to-section edges.
7. Run recall proof for current-law and amendment-history questions.

## Verification

```powershell
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_instance_source_packages.py tests/test_openai_compat_search.py -k "source_package or source_uri or citation_policy or seed"

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python scripts/release/validate-instance-source-packages.py --instance ks-state-civics --production

docker run --rm -v "${PWD}/instances/ks-state-civics/vector-stores/topeka-municipal-code/sources/topeka-codified-code/connector/topeka-code-scraper:/src" -w /src python:3.11 bash -lc "python -m pip install -q -e '.[dev]' && pytest -q"

docker run --rm -v "${PWD}/instances/ks-state-civics/vector-stores/topeka-municipal-code/sources/topeka-codified-code/connector/topeka-code-scraper:/src" -v "${PWD}/.tmp:/out" -w /src mcr.microsoft.com/playwright/python:v1.55.0-noble bash -lc "python -m pip install -q -e '.[browser]' && python -m topeka_code_scraper --fetcher playwright --root-url https://topeka.municipal.codes/TMC/18.55.010 --max-pages 1 --delay 0.1 --render-wait-ms 1500 --archive-raw --archive-network --output /out/topeka-playwright-section-cli-final"
```

## Notes

- GitHub research is summarized in `docs/TOPEKA_MUNICIPAL_CODE_SEEDING_SPEC.md`.
- Playwright implementation proof is recorded in `instances/ks-state-civics/vector-stores/topeka-municipal-code/sources/topeka-codified-code/source.lock.json`.
- The scraper now emits `citation-url-map.jsonl`; ingestion should set codified-code document `source_uri` from each section row's `citation_url`.
- The operator-owned publisher-gated acquisition slot plugs in only by producing the same JSONL artifacts as the compliant scraper. The ExAIS repo validates and ingests those artifacts, but does not own bypass logic.

## Implementation 2026-09-15: assignment 1, document release contract

Branch `feat/WAVE-118-jurisdiction-document-release-contract`, commits
`5191794` (contract, exporter, validator, audit, tests) and `b3b7ccb`
(starter release, source-package wiring). Not pushed; no main commits.

### Delivered

| Item | Path |
| --- | --- |
| Release manifest schema v1.0.0 | `contracts/jurisdiction-document-release.schema.json` |
| Source document schema v1.0.0 | `contracts/jurisdiction-source-document.schema.json` |
| Shared contract code | `scripts/release/jurisdiction_release_contract.py` |
| Exporter | `scripts/release/topeka-source-release-export.py` |
| Validator | `scripts/release/jurisdiction-release-validate.py` |
| Retained-input audit | `scripts/release/topeka-retained-input-audit.py` |
| Contract documentation | `docs/JURISDICTION_DOCUMENT_RELEASE_CONTRACT.md` |
| Starter release | `instances/ks-state-civics/vector-stores/topeka-municipal-code/releases/topeka-source-2026-09-15-r1/` |
| Tests | `tests/test_jurisdiction_release_contract.py` (38 cases) |

Both schemas are jurisdiction-neutral; Topeka is a producer, not a schema
variant. `contracts/vector-store-source-package.schema.json` gained an optional
`documentRelease` block rather than a second package format, and both Topeka
source packages now declare the contract, the four registered collections and
the exporter/validator/audit commands.

All four scripts are stdlib-only and run with no embeddings, no ExAIS API and
no StateCivics database.

### Starter release

`topeka-source-2026-09-15-r1`, bundle kind `starter`, producer commit
`51917941852d07cc1ac26f80a93149cf38777426` from a clean worktree.

| | |
| --- | --- |
| manifest SHA-256 | `666bfa7f2f88d852f727acff984c68f1fd34894ee340649b1ee4d72ce9242faf` |
| `inventory_sha256` | `99de2e5f0fd302c2237a8a61365a75e9ccfcd5e6183d1c7698c33352263ab7b5` |
| documents / files | 3 / 15 |
| validation | PASS, 0 errors, 0 warnings |

| Document | Collection | `document_version_id` | `payload_sha256` (16) |
| --- | --- | --- | --- |
| TMC 14.40.010 | `ks:city:topeka:municipal-code` | `…:tmc:14.40.010@b4402bc01b8101bf` | `878470877ad5b2b8` |
| Ordinance 20407 | `ks:city:topeka:ordinances` | `…:ordinance:20407@1c2df1f61e25ddf4` | `9d7a4a6a25b0518e` |
| Charter Ordinance 126 | `ks:city:topeka:charter-ordinances` | `…:charter-ordinance:126@f4754ab0c48657d5` | `ebc2e38d81d9f996` |

39 evidence spans resolve byte-for-byte against the delivered artifacts.
3 coordinates are published as explicitly unavailable, all of them PDF page
coordinates: the retained Markdown has no page markers and Markdown line
numbers are not converted into page numbers.

Resolution 9749 is **not** in this release; it joins as soon as the resolutions
collector exists. The three-document handoff was not held for it.

### STO provenance, resolved

The extraction manifest records `308ea5ee…` for
`extracted/topeka-ordinance-b03282aaf10640134b3ac4a4.md`; the file on disk
hashes to `55f552ab…`. The difference is exactly one appended terminal LF:
re-hashing the file without its final byte reproduces `308ea5ee…` (566,900 vs
566,901 bytes). Content is otherwise byte-identical.

Both hashes are retained. The transformation publishes as a
`terminal_newline_appended` lineage step on the document record. The expected
hash was not edited. Any extraction mismatch that is *not* this transformation
fails the export closed.

The STO also now has a stable identity despite carrying no ordinance number:
`ks:city:topeka:ordinances:ordinance:sto`, derived from the publisher's file
stem, with `publisher_number: null` recording a determined absence rather than
an unknown.

### Retained-input audit, re-measured 2026-09-15

Proof: `instances/ks-state-civics/vector-stores/topeka-municipal-code/releases/proofs/topeka-retained-input-audit-20260915.json`

| Measure | Value |
| --- | --- |
| TMC section records | 2,702 (332 in Title 18, 64 in chapter 14.55) |
| TMC captures hash-verified | 2,702 of 2,702; 0 missing, 0 mismatched |
| Retained PDFs | 364 — 323 `ordinance` category (322 numbered + the STO), 41 `charter_ordinance` |
| Raw PDF hashes | 364 matched, 0 unexplained, 0 missing |
| Extraction hashes | 363 matched, 1 `terminal_newline_appended`, 0 unexplained |
| Routing | 323 → `ks:city:topeka:ordinances`, 41 → `ks:city:topeka:charter-ordinances`, 0 unrouted |

Captures resolve by content hash, not by rebuilding the crawler's filename:
appendix citations such as `AxB Art. III § 1` are sanitised into names no rule
here reproduces, and a filename-based lookup under-reports 295 sections as
missing when all 2,702 are present and verifiable.

### Routing acceptance

Both owner examples are covered by parametrised tests, alongside ordinary and
code controls:

| Input | Collection |
| --- | --- |
| `…s3.us-east-1.amazonaws.com/files.topeka.gov/community/resolutions/2026/Resolution09749.pdf` | `ks:city:topeka:resolutions` |
| `…files.topeka.gov/community/ordinances/charter/CharterOrdinance126.pdf` | `ks:city:topeka:charter-ordinances` |
| `…files.topeka.gov/community/ordinances/2023/Ordinance20407.pdf` | `ks:city:topeka:ordinances` |
| `…files.topeka.gov/community/ordinances/other-ordinances/STO.pdf` | `ks:city:topeka:ordinances` |
| `https://topeka.municipal.codes/TMC/14.40.010` | `ks:city:topeka:municipal-code` |

Host aliases and the `#undefined` fragment canonicalise away. A URL matching no
registered collection is refused rather than given a store of its own.

### Test regime and baseline

Docker image `exais-grant-intelligence/exai-vector-store-api:0.9.8-production-candidate`
(the `localhost:5000/expertaiservices/…` image named in WAVE-119 is not present
on this host).

| Run | Result |
| --- | --- |
| New contract suite | 38 passed |
| Contract + projection + source-package + artifact-quality | 55 passed |
| Full suite, baseline `f44c97f` | 10 failed, 918 passed, 67 skipped, 106 errors, 27 collection errors |
| Full suite, candidate `b3b7ccb` | 10 failed, **956** passed, 67 skipped, 106 errors, 27 collection errors |

No regression: identical failure and error counts, +38 passing. Every one of the
27 collection errors is `ModuleNotFoundError: No module named 'jsonschema'` —
an image gap, not a code defect, and the reason the contract validator
deliberately carries its own stdlib evaluator.

`validate-instance-source-packages.py --instance ks-state-civics`: PASS,
5 packages, 0 issues.

Roughly half the new tests are negative controls asserting specific rejection
codes. An adversarial check confirmed the validator catches a one-character
shift in the reading text *after* every dependent hash was honestly re-stamped,
because it re-resolves each evidence span against the delivered bytes.

### Hosted CI

Checked 2026-09-15 on `main`: `ci` **cancelled** (run 34924799222),
`image-release` **cancelled** (34924799117), `migration-tests` **success**
(34924799097). The `ci-repair-post-8c7eecc` branch's `ci` run is a **failure**
and remains that separate branch's work, not absorbed here. The feature branch
is unpushed, so it has no hosted run of its own.

### Still open

- Assignment 2: complete ordinary/charter/resolution discovery. `topeka.gov`
  listings answer 200; `topeka.municipal.codes` answers 403 to plain HTTP, as
  before.
- Assignment 3/4: no `ks-state-civics` cell is running on this host. API
  ingestion, vector retrieval and graph proof need the cell up and incur
  embedding spend, so they need owner authorization before execution.
- Every document reports `vector_indexing` and `graph` as `pending`, and every
  collection reports `coverage.state: partial`. Nothing here claims otherwise.
- StateCivics KS-539/KS-540 A-side acceptance (importer, Topeka reader, FTS,
  agent context, packet handling) remains open and is not ExAIS work.

## Implementation 2026-09-15: assignment 2, collection discovery and acquisition

Commit `cae5293` on `feat/WAVE-118-jurisdiction-document-release-contract`.
Assignments 3 and 4 are prepared and unfired; see
[the prepared activation runbook](../runbooks/topeka-collection-activation-prepared.md).

### Delivered

| Item | Path |
| --- | --- |
| Listing discovery | `scripts/release/topeka-collection-discover.py` |
| Resumable acquisition | `scripts/release/topeka-collection-acquire.py` |
| Store-split planner | `scripts/release/topeka-store-split-plan.py` |
| Discovery manifests | `instances/.../topeka-municipal-code/discovery/` |
| Acquisition checkpoint and reports | `instances/.../topeka-municipal-code/acquisition/` |
| Tests | `tests/test_topeka_collection_discovery.py` (29 cases) |

### Discovery, reconciled against the publisher's own counts

Both listings are Revize document centres that print their own per-category and
per-year document counts. Those counts are independently authored, so the run
checks the parse against them instead of trusting itself. Every declared group
matched exactly on 2026-09-15:

| Listing | Category | Group | Publisher count | Parsed entries | Distinct documents |
| --- | --- | --- | --- | --- | --- |
| ordinances | Charter Ordinances | — | 41 | 41 | 41 |
| ordinances | Ordinances | 2026 | 59 | 59 | 58 |
| ordinances | Ordinances | 2025 | 83 | 83 | 83 |
| ordinances | Ordinances | 2024 | 67 | 67 | 67 |
| ordinances | Ordinances | 2023 | 73 | 73 | 73 |
| ordinances | Ordinances | 2022 | 67 | 67 | 67 |
| resolutions | 2026 | — | 91 | 91 | 91 |
| resolutions | 2025 | — | 136 | 136 | 136 |
| resolutions | 2024 | — | 119 | 119 | 119 |
| resolutions | 2023 | — | 109 | 109 | 109 |
| resolutions | 2022 | — | 93 | 93 | 87 |

**935 distinct documents**: 41 charter ordinances, 351 ordinances, 543
resolutions. Where distinct is below the publisher's count, repeated listing
entries account for the difference and are named. A declared group that parses
empty is an error, never an empty successful listing.

The Ordinances category counter (350) is one higher than its year counters (349)
because Ordinance 20684 is listed directly under the category, in no year group.
That is reported, not smoothed over.

### What the live listings actually contained

These are findings, not assumptions, and none of them is visible to a PDF-only
parse of the page:

- **25 instruments are published only as `.docx`** (14 ordinances in 2026, 11
  resolutions). They are inventoried and acquired. Extraction support is stated
  as PDF-only rather than assumed, because the configured bounded remote path is
  Marker.
- **7 repeated listing entries** (1 in ordinances 2026, 6 in resolutions 2022)
  point at a document already listed in the same group. Each resolves to one
  identity; no duplicate active document is created.
- **The Standard Traffic Ordinance is linked twice**, once from the retired
  `cot-wp-uploads.s3.amazonaws.com` bucket. That location is registered as a
  legacy location of the ordinances collection, so it routes to the same
  identity and can never win as the official URL.
- **`s3.us-east-1.amazonaws.com/files.topeka.gov/...` aliases appear in the
  live HTML**, confirming the alias canonicalisation is load-bearing rather than
  hypothetical.
- **Two links sit outside the document centre** (the STO and a Topeka Way to
  Work program overview). Both are admitted as `review_needed`: a page link
  alone does not establish collection membership, and the program overview is
  not an instrument.
- **The city states that only ordinances from the last four years are published
  online.** The listing is therefore incomplete by publisher policy. A retained
  document absent from it is recorded as a listing window, never a repeal.

### Acquisition

Resumable, checkpointed after every item. Measured over all 935 worklist rows:

| Outcome | Count |
| --- | --- |
| `reused_verified` | 364 |
| `unchanged_remote` | 568 |
| `unavailable_at_source` | 3 |
| `downloaded_changed` | 0 |
| `failed` | 0 |

**All 364 retained originals still hash to the bytes the publisher serves
today**, so not one was re-downloaded. 568 new documents are held (131 MB, kept
out of Git; the manifests, checkpoint and reports are the committed proof).
Resolution 9749 — the owner's example — is acquired, 143,029 bytes,
`049b6f231af4079b9d4c6251f8daab77582503d6429894bdb1778f8924ca6a9f`.

Resume is not caching. A later run re-asks the publisher by default, so changed
bytes are detected; `--trust-checkpoint` skips that re-check and is opt-in
precisely because it trades change detection for speed. The retry after the
fix made exactly 1 publisher request across 935 rows.

Topeka writes some hrefs with `+` where the stored filename has a trailing space
— query-string semantics applied to a URL path. A 404 on the literal form
retries that single re-interpretation of the publisher's own href and records
`url_resolution=plus_decoded_as_space`; this recovered Ordinance 20670.

Three documents remain `unavailable_at_source`, all the publisher's own broken
links, and are **not** repaired:

| Document | Publisher link | Status |
| --- | --- | --- |
| Ordinance 20632 | `.../2026/Ordinancec.pdf` | 404 (href appears to be a typo; `Ordinance20632.pdf` answers 200, but substituting it would invent provenance for bytes we never retrieved through the listed link) |
| Topeka Way to Work overview | `.../2026 Internet TWTW Program Overview.docx` | 404; also `review_needed`, not an instrument |

A publisher 404 is a terminal, reportable outcome, distinct from a retryable
`failed`. The run passes with them recorded; it never counts them as acquired.

### Store split, planned not executed

`scripts/release/topeka-store-split-plan.py`, proof at
`releases/proofs/topeka-store-split-plan-20260915.json`:

| Destination | Planned documents |
| --- | --- |
| `ks:city:topeka:municipal-code` | 2,702 |
| `ks:city:topeka:ordinances` | 323 |
| `ks:city:topeka:charter-ordinances` | 41 |
| unassigned | **0** |

3,066 total, reconciling against `store.yaml`'s recorded 3,066 / 2,702 / 364
from the live 2026-08-28 ingestion — two independently derived numbers that
agree. The unnumbered STO has an explicit destination and is not dropped.
`vs_d4185d1004604f08a55299fa` is not mutated and stays queryable for rollback.

Both ingest dry-runs were executed offline and wrote nothing:
`topeka-code-ingest.py` reports `payload_count: 2702`, `submitted_count: 0`;
`topeka-ordinance-pdf-ingest.py` reports `payload_count: 364`,
`submitted_count: 0`. Both agree with the plan.

### Not done, and why

- **No cell was started, no store created or mutated, no embedding purchased,
  ExAIS routing unchanged.** No `ks-state-civics` cell exists on this host and
  activation/spend is gated on owner authorization.
- **Resolution 9749 is acquired but not released.** The contract refuses a
  document with empty extraction, and the 543 acquired resolutions have not been
  through the bounded remote extraction path. Acquisition complete, extraction
  pending, release pending.
- **The three new WAVE-117 source packages are not written.**
  `instance_source_packages.py` requires a non-empty `vectorStore.id`; writing
  them before the stores exist would commit a placeholder or break
  `validate-instance-source-packages.py` (still PASS, 5 packages, 0 issues).
- **`DECODO_API_TOKEN` is declared in `.env.example` but not populated** in the
  cell env. It is needed only to re-crawl `topeka.municipal.codes`, which
  answers 403 to plain HTTP. The retained TMC corpus is complete and
  hash-verified, so no re-crawl was required.

### Test regime

| Run | Result |
| --- | --- |
| New discovery/acquisition suite | 29 passed |
| Full suite, baseline `f44c97f` | 10 failed, 918 passed, 67 skipped, 106 errors |
| Full suite, candidate `cae5293` | 10 failed, **985** passed, 67 skipped, 106 errors |

No regression: identical failure and error counts, +67 passing (38 contract +
29 discovery). The starter release bundle still validates PASS after the
collection-registry change.

## Delivery 2026-09-16: display handoff transferred to StateCivics

Package `topeka-portable-2026-09-16`, 3,088 documents, self-contained.

| | |
| --- | --- |
| Destination | `/Users/mfrieson/Dropbox/AI_Projects/exai_projects/Statecivicsai/data/exais-handoffs/topeka-portable-2026-09-16/` |
| Archive | `topeka-portable-2026-09-16.tar.gz`, 119,541,658 bytes |
| Archive SHA-256 | `8ffa4d6d12b587724183be1b7ca3c8f633e2d64c4d56100624e167eac25b23d1` |
| Source/destination hash | match |
| Extracted to | `<destination>/package/` (297 MB) |

Re-verified **at the destination**, in a bare `python:3.12-slim` with
`--network none` and the package mounted read-only — no checkout, no network,
no installed dependency:

```
documents          3088
files verified     15447
citations resolved 3088
evidence spans     28284
result             PASS (0 errors)
```

The destination is under StateCivics' git-ignored `data/` tree, so this is a
data drop, not a change to that repository. Nothing in the StateCivics checkout
was modified.

### What the package contains

| Collection | Documents |
| --- | --- |
| `ks:city:topeka:municipal-code` | 2,702 |
| `ks:city:topeka:ordinances` | 335 |
| `ks:city:topeka:charter-ordinances` | 41 |
| `ks:city:topeka:resolutions` | 10 |

3,088 citations in `citations.jsonl`; both contract schemas; `IMPORT.md`;
`verify.py` (stdlib only); `package-manifest.json` with every file's hash.

**Resolutions is 10, not 542.** Only the DOCX resolutions are extracted; 532
resolution PDFs are among the 544 pending the unauthorized paid path. A reader
demo that expects a rich resolutions collection will not find one yet.

### Explicitly not in the package

- 544 documents pending extraction — 532 resolution PDFs, 12 ordinance PDFs.
- 3 documents held for review — `20520` and `20610` (`identity_ambiguous`),
  `sto` (`membership_review_needed`).
- Coverage is `partial` on every collection, and says so.
- No embeddings, no graph. `readiness.vector_indexing` and `readiness.graph`
  read `pending` on every document.

### Still outstanding

Package verification is complete. The consumer import and the live UI proof
under KS-539 are StateCivics' work and remain unproved. Activation, retrieval,
graph and scheduling remain open on the ExAIS side.

## Milestone closed 2026-09-16: data handoff

Independent review PASSED the display handoff at `0e485cb8`. WAVE-118 itself
stays open.

**Delivered and verified at the destination:** 3,088 documents and citations,
15,447 files, 28,284 evidence spans, zero verification errors, offline and
without the producer checkout. Import guide at
`Statecivicsai/data/exais-handoffs/topeka-portable-2026-09-16/IMPORT.md`.

### Coverage, kept visible

| | |
| --- | --- |
| Delivered | 2,702 code sections, 335 ordinances, 41 charter ordinances, **10 resolutions** |
| Pending extraction | 544 — **532 resolution PDFs** and 12 ordinance PDFs, awaiting the unauthorized paid path |
| Held for review | 3 — `20520`, `20610` (`identity_ambiguous`), `sto` (`membership_review_needed`) |

Ten resolutions, not 542. Anything built around the resolutions collection will
look thin until the paid extraction stage runs.

### Open, in the order the ticket's goal needs them

1. **KS-539 consumer proof** (StateCivics, not ExAIS): importer, readable
   document display, original downloads, search results, meeting-context access.
   Unblocked now — it does not wait on anything below.
2. **Paid extraction** of the 544. Enforced caps are wired and tested
   (`extraction_budget.py`); the pilot is 10 documents starting with Resolution
   9749. Needs authorization, and the actual billed pages must be reconciled
   against the ~2,647-page estimate before the bulk stage.
3. **Activation**: cell up, API ingestion, vector and graph retrieval proof per
   collection, then the routing switch. Blocked additionally by a host issue —
   the pinned images are gone and the local registry cannot bind port 5000,
   which macOS AirPlay Receiver holds.
4. **Scheduling**: the refresh runner exists and is proven; no scheduler entry
   is configured, and none should be claimed.
5. **Hosted CI merge gate**: the CI repair is merged into this branch and CI now
   fails at exactly one explicit gate — the absent `STATECIVICS_READ_TOKEN`
   repository secret. `migration-tests` and `image-release` pass.
