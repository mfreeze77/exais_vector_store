# Topeka Codified Code Seed

This folder is the local seed root for the `topeka-codified-code` source package.

Expected layout:

```text
seed/
  raw/
    vendor/                 # original scraper ZIP and other acquisition evidence
    html/                   # archived source HTML when a crawl succeeds
    network/                # optional Playwright network logs and endpoint discovery artifacts
  extracted/                # retained markdown/html artifacts sent to ExAIS
  manifests/                # sections.jsonl, definitions.jsonl, nodes.jsonl, edges.jsonl, crawl_report.json
  citation-url-map.jsonl    # optional source identity -> caller-hosted URL mapping
```

Current status: the upstream scraper ZIP is preserved in `raw/vendor/`, and the operator-provided URL manifest is preserved as `raw/topeka_municipal_code_urls.csv`. Plain HTTP and broad stock Playwright acquisition were blocked by publisher challenge behavior, but the scraper supports manifest-only `Section`/`Subsection` fetching, Decodo-backed operator acquisition, and CSV-derived `CONTAINS` GraphRAG hierarchy.

Full local artifact proof on 2026-08-28 lives under `.tmp/topeka-decodo-window-batches-20260827220454/combined-full-corpus-20260828-v2`: 2,702 required fetch URLs, 2,702 fetched sections, zero missing URLs, zero failed URLs, 2,702 raw HTML evidence files, 2,702 network evidence files, 980 definitions, and a passing combined artifact quality gate. The clean local vector store `vs_d4185d1004604f08a55299fa` has been ingested and recall-verified. The source package remains `productionReady: false` until graph load/search and production/VPS promotion gates are run and accepted.
