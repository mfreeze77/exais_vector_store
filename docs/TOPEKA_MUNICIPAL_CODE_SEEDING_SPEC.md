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

This solves root discovery and graph hierarchy. It does not fully solve publisher challenge behavior. Full production seeding still needs a retry/resume acquisition pass or an operator-owned authorized export that satisfies the same artifact contract.

Current operating rule: produce JSON/JSONL source artifacts only until the artifact quality gate passes. Do not call ExAIS document ingestion, embedding providers, Qdrant, or vector-store write paths for additional Topeka records until `scripts/release/topeka-code-artifact-quality.py` reports `passed: true`.

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

### 4. Official Topeka Ordinance PDF Collector

The City of Topeka Ordinances page exposes recent ordinance documents through the city document center. Build a collector that:

- discovers ordinance and charter ordinance PDF links;
- writes `ordinances.jsonl` with ordinance number, title, year/category, `pdf_url`, saved path, byte count, and SHA-256;
- stores PDFs under `seed/raw/pdfs/`;
- extracts markdown using the existing PDF path, with RunPod Marker as the external OCR/Marker endpoint for hard PDFs;
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
- `filename`: ordinance number/title markdown filename
- attributes: jurisdiction, ordinance number, category/year, title, PDF hash, extraction parser, page count

## GraphRAG Plan

Load codified scraper graph rows first, then add ordinance-derived cross-source edges:

- `ORDINANCE_AMENDS_SECTION`
- `ORDINANCE_REPEALS_SECTION`
- `ORDINANCE_ADOPTS_CODE`
- `SECTION_HAS_HISTORY`

Graph expansion remains secondary to semantic search. The caller asks a question, semantic search finds candidate sections/ordinances, then graph expansion pulls the legal neighborhood.

GraphRAG citation rule: every graph-expanded section, definition, reference target, or ordinance-history edge must expose a `citation_url` when the source material provides one. For codified-code graph rows that URL is the canonical TMC section URL. For ordinance-derived rows that URL is the official PDF URL until a better section-specific ordinance URL exists.

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
- Zero fetched pages exits nonzero and cannot produce a successful seed manifest.
- Zero extracted sections exits nonzero unless explicitly allowed for diagnostics.
- A seeded pilot returns clickable citations for both `source_url` and `pdf_url`.
- Graph proof shows section-reference edges, ordinance-history edges, and `citation_url` properties on graph-expanded results.
- Recall proof includes current-law queries and amendment-history queries.
