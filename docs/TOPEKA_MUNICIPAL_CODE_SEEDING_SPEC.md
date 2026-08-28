# Topeka Municipal Code Seeding Spec

## Goal

Seed a `topeka-municipal-code` vector store under the `ks-state-civics` instance with both current codified code sections and official ordinance PDFs. The store must support semantic search, graph expansion, source citations, and reproducible source refreshes.

## Corpus Model

Use one vector store with two source packages:

- `topeka-codified-code`: current TMC sections. Citation URL field: `source_url`.
- `topeka-ordinances`: official ordinance PDFs. Citation URL field: `pdf_url`.

The codified-code source answers current-law questions. The ordinance source supplies legal provenance and amendment history. A caller agent should search the vector store semantically first, then expand through graph edges for definitions, internal references, and ordinance history.

## Acquisition Adapters

### 1. Existing HTTP Scraper

The vendored `topeka-code-scraper` package remains the baseline parser and graph exporter. It already emits:

- `sections.jsonl`
- `definitions.jsonl`
- `nodes.jsonl`
- `edges.jsonl`
- `citation-url-map.jsonl`
- `manifest.json`
- `crawl_report.json`

The ExAIS ingestion layer consumes those files instead of coupling directly to the publisher.

### 2. Compliant Playwright Headless Adapter

Add a Playwright fetch mode to the scraper only for normally accessible rendered pages and endpoint discovery:

- launch Chromium headless with a fresh isolated browser context per run;
- record request and response metadata for HTML, JSON, XHR, and fetch requests;
- disable service workers for reliable network observation;
- archive rendered HTML and network logs into `seed/raw/html/` and `seed/raw/network/`;
- continue to use the existing parser/exporter output contract;
- fail closed if the response is a publisher challenge, captcha page, empty page, or zero-section crawl.

This is not a Cloudflare bypass. The repository should not contain stealth plugins, anti-detection patches, captcha solving, rotating proxy logic, or challenge-circumvention code.

Useful upstream patterns:

- Playwright network events can observe browser requests/responses and API/XHR traffic.
- Playwright browser contexts provide isolated browser state for reproducible runs.
- Playwright storage state can contain sensitive cookies, so no storage-state file belongs in Git.

Probe result from 2026-08-27:

- Plain HTTP from Docker returned `403` with `cf-mitigated: challenge`.
- Stock Playwright Chromium loaded `https://topeka.municipal.codes/TMC` with HTTP `200`, title `Topeka Municipal Code`, and visible TMC contents.
- Stock Playwright Chromium loaded `https://topeka.municipal.codes/TMC/18.55.010` with HTTP `200`.
- The existing parser extracted section `18.55.010`, 92,429 section-text characters, 326 definitions, 84 internal links, 336 graph nodes, 343 graph edges, and 17 numbered ordinance-history entries from the rendered HTML after tightening ordinance-history extraction to reject non-number word fragments.
- The page still loaded Cloudflare challenge-platform scripts, so the crawler must distinguish "content loaded with browser verification scripts present" from "blocked challenge page."
- The implemented Playwright fetch mode emits rendered HTML, network logs, and `citation-url-map.jsonl` without adding stealth, proxy, captcha, or challenge-bypass code.

### 2A. CSV URL Manifest Adapter

The operator-provided `topeka_municipal_code_urls.csv` is preserved under the codified-code seed folder at `seed/raw/topeka_municipal_code_urls.csv`. It contains 3,204 rows:

- 2,675 `Section` rows;
- 27 `Subsection` rows;
- 502 hierarchy rows across code, index, titles, appendices, divisions, chapters, articles, subarticles, and tables.

The scraper supports:

- `--url-list` for the CSV manifest;
- `--url-list-levels Section,Subsection` to fetch only content-bearing section URLs;
- `--manifest-only` to avoid following publisher navigation links;
- `--isolate-playwright-context` to create a fresh browser context per section page;
- CSV-derived `CONTAINS` graph nodes/edges so hierarchy does not depend on fetching challenged title/container pages.

Proof from 2026-08-28:

- A 10-page manifest-only Playwright run without isolated contexts fetched 1 section and failed 9 challenge pages.
- A 10-page manifest-only Playwright run with isolated contexts fetched 8 sections and failed 2 challenge pages.
- A 50-page manifest-only Playwright run with isolated contexts and one retry fetched 31 sections, failed 19 challenge pages, emitted 3,203 `CONTAINS` edges from the CSV hierarchy, and emitted 37 `HAS_ORDINANCE_HISTORY` edges from fetched section text.
- A 200-page manifest-only Playwright run with isolated contexts and one retry fetched 141 sections, failed 59 challenge pages, emitted 3,203 `CONTAINS` edges, 22 `DEFINES` edges, and 244 `HAS_ORDINANCE_HISTORY` edges. The artifact quality gate reported `passed: false`, `vectorization_allowed: false`, `5.218%` coverage, `2,561` missing required URLs, `59` failed crawl URLs, and zero section text/citation issues on fetched pages.

This solved root discovery and graph hierarchy but did not fully solve publisher challenge behavior. The later complete corpus acquisition used the operator-owned Decodo route and still had to satisfy the same artifact contract and quality gate.

Current status as of 2026-08-28: the Decodo-acquired full codified-code corpus passed the artifact quality gate and was ingested through the ExAIS API into clean local vector store `vs_d4185d1004604f08a55299fa` (`City of Topeka Municipal Code`) for the `https://topks.statecivics.ai/local` surface. The official ordinance PDF source was also collected, externally extracted through the RunPod Marker path, and ingested into the same local vector store. Database proof shows `3,066` documents, `3,066` distinct official source URLs, `6,153` active chunks, and `6,153` indexed chunks: `2,702` codified-code documents plus `364` ordinance PDF documents.

Official ordinance PDF proof from 2026-08-28:

- `364` official PDF records in `topeka-ordinances/seed/manifests/ordinances.jsonl`.
- `364` retained PDFs under `topeka-ordinances/seed/raw/pdfs/`.
- `364` retained Markdown extractions under `topeka-ordinances/seed/extracted/`.
- `0` extraction failures in `topeka-ordinances/seed/manifests/ordinance-extraction-report.json`.
- `5/5` ordinance PDF recall checks passed through the live local ExAIS API with official PDF citations. Proof artifact: `.release/cells/ks-state-civics/evals/topeka-ordinance-recall-20260828.json`.

Deep-search proof from 2026-08-28 completed 24 live Topeka API searches against `vs_d4185d1004604f08a55299fa` with zero API errors after route hardening. The proof artifact is `.release/cells/ks-state-civics/evals/topeka-code-deep-search-20260828.json`; 19 searches passed the basic citation/content gate and five were marked for review because broad legal topics needed tighter query terms or caller-side answer framing.

The Topeka store must not use the Kansas court-decision query planner. That planner extracts docket numbers, decision years, court names, and publication status for court cases. On municipal code text, ordinance numbers and passed dates can otherwise be misread as court filters. The API route now disables that planner when vector-store attributes identify a non-court corpus such as `topeka_municipal_code`, and store-scoped searches no longer fall back to unavailable private embedding profiles when a planned filter matches zero indexed rows.

Current operating rule: codified-code and ordinance PDF vectorization are allowed only from artifact-quality-passed source outputs. Official ordinance PDF ingestion is complete in the local KS Civics cell. Topeka graph artifact extraction/eval, graph API load, and explicit graph-lens search are locally verified for the clean store. Keep production/VPS promotion and the public `https://topks.statecivics.ai/local` caller route behind their own proof gates.

Public-access escalation packet: `docs/TOPEKA_PUBLIC_LAW_ACCESS_PACKET.md`.

### 2B. Operator Capture Import Shim

The scraper also supports a local capture manifest import path for operator-owned acquisition routes. This is the integration point for an authorized export, authenticated browser capture, records-response bundle, Cloudflare Worker route, or separately operated route that returns source HTML. The route itself stays outside this repository.

The capture manifest is JSONL. Each row must include:

- canonical TMC `url`;
- inline `html` or `html_path` relative to the capture root;
- optional `status_code`, `headers`, `retrieved_at`, `network_events`, and `source`.

Run shape:

```bash
python -m topeka_code_scraper \
  --capture-manifest ./captures/pages.jsonl \
  --capture-root ./captures \
  --url-list seed/raw/topeka_municipal_code_urls.csv \
  --url-list-levels Section,Subsection \
  --manifest-only \
  --archive-raw \
  --archive-network \
  --output ${TOPEKA_CODE_OUTPUT}
```

This path reuses the same parser, graph builder, citation map, manifest augmentation, and JSON quality gate as live HTTP/Playwright fetching. It still rejects challenge-only captures and records them in `crawl_report.json`. Do not commit acquisition-route code, cookies, credentials, storage state, proxy logic, captcha solving, stealth plugins, or challenge-circumvention code.

The artifact quality gate can write complete worklists with `--worklist-dir`. These worklists are the handoff to the external capture route or public-access/export request:

- `missing-required-urls.jsonl`;
- `failed-crawl-urls.jsonl`;
- `section-quality-issues.jsonl`;
- `unexpected-section-urls.jsonl`.

### 3. Operator-Owned Publisher-Gated Acquisition Slot

If an operator obtains a legally authorized export, API access, records request, licensed data feed, or an out-of-band publisher-gated acquisition method, it plugs in by producing the same artifact contract:

```text
sections.jsonl
definitions.jsonl
nodes.jsonl
edges.jsonl
manifest.json
crawl_report.json
raw evidence files or export receipts
```

Required metadata per section:

- `id`
- `citation`
- `title`
- `source_url`
- `text`
- `content_hash`
- `source_html_hash` or export hash
- `retrieved_at`
- `version.ordinance` when available
- `version.passed_date` when available

Required citation map output:

- one row per page, section, and definition;
- stable record `id`;
- `record_type`;
- `source_url`;
- `citation_url`;
- `content_hash` and/or `source_html_hash` when available.

Required graph output:

- `CONTAINS`
- `REFERENCES`
- `DEFINES`
- `HAS_ORDINANCE_HISTORY`

Graph node and edge properties must preserve `source_url` and `citation_url` where available. GraphRAG expansion should return those URLs alongside node/edge matches so caller-side citations can be rendered from graph results as well as semantic results.

The adapter boundary is artifact-level by design. The ExAIS repo can validate and ingest artifacts without owning acquisition code that bypasses publisher access controls.

### 3A. Batch Consolidation

When acquisition runs in paid or rate-limited windows, combine completed batch
folders into one source-output folder before full-corpus quality, workbench
projection, ingestion, or GraphRAG extraction:

```bash
python scripts/release/topeka-code-combine-batches.py \
  --batch-root ${TOPEKA_CODE_BATCH_ROOT} \
  --output-dir ${TOPEKA_CODE_OUTPUT}
```

The combiner requires every batch to have a passing `quality-report.json`,
deduplicates the repeated URL-manifest graph, copies `raw/` and `network/`
evidence files, and writes one combined artifact set with `sections.jsonl`,
`definitions.jsonl`, `nodes.jsonl`, `edges.jsonl`, `citation-url-map.jsonl`,
`url-manifest.jsonl`, `expected-fetch-urls.jsonl`, `manifest.json`, and
`crawl_report.json`.

This is still an artifact-only step. It does not call ExAIS ingestion, model
gateways, embedding providers, Qdrant, Postgres, MinIO, OpenSearch, or graph
write paths.

### 3B. Workbench Canonical Projection

Saved codified-code captures must support more than vector search. Before the
Topeka corpus is represented as editable law, generate a separate workbench
projection from the saved JSON/JSONL artifacts and archived HTML.

The projection command is:

```bash
python scripts/release/topeka-code-workbench-project.py \
  --source-output ${TOPEKA_CODE_OUTPUT} \
  --output-dir ${TOPEKA_CODE_OUTPUT}/workbench
```

It writes:

- `workbench/canonical-document.json`
- `workbench/components.jsonl`
- `workbench/component-projection.jsonl`
- `workbench/component-relations.jsonl`
- `workbench/slices.jsonl`
- `workbench/workbench-import-manifest.json`

This is a projection-only step. It does not call ExAIS ingestion, model
gateways, embedding providers, Qdrant, Postgres, MinIO, OpenSearch, or graph
write paths.

The `topeka_municipal_code_v1` projection keeps two identities:

- `source_component_key`: stable Topeka/source identity, for example
  `ks-topeka:tmc:1.10.020` or
  `ks-topeka:tmc:1.10.020:marker:a`.
- `workbench_component_id`: deterministic UUIDv5 derived from the source
  component key for compatibility with the StateCivics legislative workbench
  canonical-document schema.

The projection maps:

- URL-manifest/GraphRAG hierarchy into code, title, chapter, article, appendix,
  section, and container components.
- Section blocks into paragraph/table child components with ordinals,
  citations, `content_hash`, `source_url`, and `source_html_hash`.
- Extracted definitions into definition child components and `DEFINES`
  relations.
- Section references and ordinance history into relation rows with citation URL
  provenance.
- Title/chapter/appendix/article slices into `slices.jsonl` so the workbench can
  import a focused portion of the municipal code instead of loading the whole
  corpus.

The source of truth remains the saved capture/archive and component hashes.
Embeddings, Qdrant rows, graph rows, rendered HTML, and workbench import files
are derived projections that can be regenerated.

### 4. Official Topeka Ordinance PDF Collector

The City of Topeka Ordinances page exposes recent ordinance documents through the city document center. The collector:

- discovers ordinance and charter ordinance PDF links;
- writes `ordinances.jsonl` with ordinance number, title, year/category, `pdf_url`, saved path, byte count, and SHA-256;
- stores PDFs under `seed/raw/pdfs/`;
- extracts markdown using the existing external RunPod Marker path for hard PDFs;
- sets ExAIS document `source_uri` to `pdf_url`.

## Ingestion Path

All writes go through the ExAIS API. No source package may write directly to Postgres, Qdrant, MinIO, or OpenSearch.

Codified section payload:

- `mode`: `markdown_docs_v1`
- `source_uri`: section `citation_url` from `citation-url-map.jsonl`
- `filename`: stable TMC citation path
- attributes: jurisdiction, code, citation, title, version ordinance, version passed date, source collection, content hash

Ordinance PDF payload:

- `mode`: `pdf_markdown_external_v1`
- `source_uri`: `pdf_url`
- `filename`: ordinance number/title markdown filename, with charter ordinances normalized as `CharterOrdinance{number}.md`
- attributes: jurisdiction, ordinance number, source record ID, category/year, title, PDF hash, extraction parser, and retained Markdown path

## GraphRAG Plan

Load codified scraper graph rows first, then add ordinance-derived cross-source
edges through `POST /v1/vector_stores/{vector_store_id}/graph`. Direct Postgres
graph writes remain forbidden for Topeka source packages.

Current local graph relation types:

- `CONTAINS`
- `REFERENCES`
- `DEFINES`
- `HAS_ORDINANCE_HISTORY`
- `ORDINANCE_AMENDS_SECTION`
- `SAME_ORDINANCE`

Graph expansion remains secondary to semantic search. The caller asks a question, semantic search finds candidate sections/ordinances, then graph expansion pulls the legal neighborhood.

GraphRAG citation rule: every graph-expanded section, definition, reference
target, or ordinance-history edge must expose a `citation_url` when the source
material provides one. For codified-code graph rows that URL is the canonical
TMC section URL. For ordinance-derived rows that URL is the official PDF URL
until a better section-specific ordinance URL exists. Caller renderers should
prefer result-level `citation.url` for the clickable source, and may use
`citation.graph_expansion.relationship_source_url` /
`relationship_target_url` for explaining the graph relationship.

## GitHub Research Notes

Observed patterns from open source municipal-code projects:

- `docxology/crescent-city`: Playwright-driven eCode360 scraping architecture with TOC endpoint interception, article/page extraction, per-article manifest resume, retries, and rate limiting.
- `krishangMittal/GovNavigator`: Playwright plus BeautifulSoup for JavaScript-rendered municipal code pages, followed by search/MCP exposure.
- `noclocks/municode-scraper`: provider-specific municipal-code scraper shape; useful as a reminder that each publisher family may need its own adapter.
- `datamade/chicago-council-scrapers`: civic data pipeline pattern with reproducible exports and archived source evidence.

Do not copy evasion code into this repo. Treat any publisher-gated acquisition as operator-owned input that must satisfy the artifact contract above.

## Acceptance Gates

- `topeka-code-scraper` tests pass from the vendored connector path.
- Source-package validation passes while the source is explicitly marked `productionReady: false`.
- Artifact generation emits JSON/JSONL files first; vectorization is blocked until the JSON artifact quality report passes.
- Artifact quality runs write complete missing/failure/section-issue worklists for the next acquisition pass.
- Zero fetched pages exits nonzero and cannot produce a successful seed manifest.
- Zero extracted sections exits nonzero unless explicitly allowed for diagnostics.
- The seeded local store returns clickable citations for both `source_url` and `pdf_url`.
- Semantic recall proof includes current-law, amendment-history, and official ordinance PDF queries.
- Graph artifact proof shows section-reference edges, ordinance-history edges, ordinance-to-section edges, and `citation_url` properties.
- Local GraphRAG proof loads the artifact through `POST /v1/vector_stores/{vector_store_id}/graph` and verifies `municipal_code_structure`, `municipal_code_cross_reference`, and `municipal_code_history` through the caller-facing search route.
- Production GraphRAG is not claimed live until the VPS/public API route repeats those graph-load/search checks after deployment.
