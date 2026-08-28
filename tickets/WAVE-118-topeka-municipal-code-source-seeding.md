# WAVE-118 Topeka Municipal Code Source Seeding

## Summary

Create the Topeka Municipal Code vector-store source pipeline for the `ks-state-civics` instance, including codified TMC sections, official ordinance PDFs, reproducible seed folders, compliant Playwright endpoint discovery, API-only ingestion, and GraphRAG proof.

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
- Implement API-only ingestion for codified sections and ordinance PDFs into one `topeka-municipal-code` vector store.
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
- `scripts/release/topeka-ordinances-collect.py`
- `scripts/release/topeka-ordinance-pdf-ingest.py`
- `scripts/release/topeka-code-graphrag-extract.py`
- `scripts/release/topeka-code-graphrag-load.py`
- `scripts/release/topeka-code-graphrag-eval.py`
- `scripts/release/topeka-code-recall-eval.py`

## Implementation Notes 2026-08-27

- Added offline-testable Topeka release scripts for official ordinance PDF collection, codified-code API ingestion, ordinance markdown/PDF API ingestion, GraphRAG extraction, GraphRAG load/eval, and recall eval.
- The ingestion scripts use ExAIS API document ingestion and keep `source_uri` mapped to section `citation_url` or official ordinance `pdf_url`.
- The Topeka API scripts now honor `--api-transport` for host curl, API-container, and Docker-network calls; source-package commands use Docker-network transport for live cell execution.
- The ordinance PDF ingestion script does not run Marker locally; it consumes precomputed markdown from the existing external RunPod Marker/operator extraction path.
- The GraphRAG loader validates artifacts and can submit through a configured ExAIS graph API path. No such endpoint is currently present in the repo, so the loader fails closed with `blocked_no_graph_api` instead of using the older KS courts direct-Postgres loader.
- The codified-code parser now rejects non-number word fragments as ordinance history and preserves distinct ordinance-history graph edges by ordinance/section/date/raw value.
- Bounded live proof on `https://topeka.municipal.codes/TMC/18.55.010` produced 1 section, 326 definitions, 17 numbered ordinance-history rows, 336 graph nodes, 343 graph edges, and 328 citation URL rows.
- Bounded live ordinance collector proof against the official City of Topeka ordinance page with `--limit 2` wrote two ordinance PDF records with no failures.
- Topeka source packages remain `productionReady: false`; the local pilot vector store is `vs_268b119a2cd84b568af62155`, but broad recall is still blocked until the full codified corpus can be acquired.
- Operator URL manifest `seed/raw/topeka_municipal_code_urls.csv` is preserved and wired into the scraper. Manifest-only Playwright fetching of `Section`/`Subsection` rows now bypasses root discovery and emits CSV-derived `CONTAINS` graph hierarchy.
- Isolated Playwright browser contexts materially improve batch acquisition but do not fully defeat publisher challenge behavior: 2026-08-28 proof fetched 31 of the first 50 section URLs and failed 19 challenge pages.
- Current operator rule: generate JSON/JSONL artifacts and run the artifact quality gate only. Do not ingest/vectorize additional Topeka records until artifact quality passes.
- Operator-owned acquisition routes can now plug in through `--capture-manifest` by providing authorized HTML captures. The route implementation, cookies, credentials, proxy logic, captcha solving, stealth plugins, and challenge bypass code remain out of scope for this repository.
- Public-access/export escalation is documented in `docs/TOPEKA_PUBLIC_LAW_ACCESS_PACKET.md`, and the artifact quality gate now emits complete worklists for missing URLs and capture failures.
- Larger stock-Playwright proof on 2026-08-28 fetched 141 of the first 200 section/subsection URLs and failed 59 publisher-challenge pages. The artifact gate reported `vectorization_allowed: false`, 5.218 percent coverage, 2,561 missing required URLs, and zero section text/citation issues on fetched pages.
- Operator provided a Decodo Web Scraping API credential as a local runtime secret. The codified-code scraper now supports `--fetcher decodo`, defaulting to Decodo's minimal universal request after live proof showed Topeka HTML succeeds without explicit JS/proxy parameters while `headless: html` and `proxy_pool: standard` returned provider status 613. The route still writes only JSON/JSONL/raw/network artifacts for the existing quality gate. The Decodo credential remains env-only and must not be committed or written into artifacts.
- The scraper now supports `--url-list-offset` and `--url-list-limit` so paid acquisition can run in 200-page windows without discarding the full URL manifest hierarchy needed for `CONTAINS` GraphRAG edges.
- WAVE-119 adds a projection-only workbench lane from saved Topeka artifacts to stable canonical components, component relations, and title/chapter slices. This keeps future legislative redline/import work separate from vectorization and ingestion.
- Decodo batch window proof on 2026-08-28 reached 600 fetched pages across batches 001-003 with zero failed URLs. Batch 003 at offset 400/limit 200 produced 200 sections, 55 definitions, 3,313 graph nodes, 3,438 graph edges, complete section citation coverage, zero quality worklist rows, and `vectorization_allowed: true` for that 200-page window only.

## Acceptance Criteria

- The source-package validator passes for `ks-state-civics`.
- Both Topeka source packages remain `productionReady: false` until a real corpus and vector store ID are proven.
- Codified-code artifact generation and quality check run before any additional vectorization.
- Operator capture import parses supplied HTML captures through the same JSON artifact, citation, graph, and quality-gate path as live fetching.
- Quality-gate worklists identify every missing required URL, crawl failure, unexpected section URL, and section-level text/citation issue.
- Full codified-code crawl writes nonempty `sections.jsonl`, `definitions.jsonl`, `nodes.jsonl`, `edges.jsonl`, `citation-url-map.jsonl`, `manifest.json`, and `crawl_report.json`.
- Full codified-code crawl stores rendered HTML and network proof for fetched pages.
- Full codified-code crawl fails closed on zero pages or zero sections.
- Full codified-code crawl records per-page failures and treats challenge-only pages as failures, not successful source records.
- `citation-url-map.jsonl` has a section row for every section document to be ingested, and every section row has `source_url` and `citation_url`.
- The ordinance collector writes a nonempty `ordinances.jsonl` with stable identity fields, SHA-256, PDF URL, and saved path.
- API ingestion creates or finds the real Topeka vector store and writes both source types with clickable citations.
- Graph proof includes `CONTAINS`, `REFERENCES`, `DEFINES`, `HAS_ORDINANCE_HISTORY`, and at least one ordinance-to-section edge when data supports it.
- GraphRAG rows preserve `source_url`/`citation_url` so graph-expanded context can render clickable citations.
- Recall proof includes at least five current-code questions and five amendment-history questions.

## Dependencies

- WAVE-117 source-package contract and seed layout.
- Existing RunPod Marker endpoint for hard PDF extraction.
- Operator-created real vector store ID before production seeding.
- Playwright runtime with Chromium matching the pinned scraper browser dependency.

## Implementation Order

1. Run a bounded Playwright full-corpus discovery crawl and inspect skipped/challenge-only URLs.
2. Produce codified-code seed artifacts and verify section count, citation URL count, graph node/edge count, and failure list.
3. Build and test the official ordinance PDF collector and manifest.
4. Full-corpus gate: keep `productionReady: false` until the codified-code acquisition path can crawl all required source pages and broad recall passes.
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
