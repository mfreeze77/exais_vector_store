# Topeka Codified Code Seed

This folder is the local seed skeleton for the `topeka-codified-code` source package.

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

Current status: the upstream scraper ZIP is preserved in `raw/vendor/`, and the operator-provided URL manifest is preserved as `raw/topeka_municipal_code_urls.csv`. Plain HTTP is blocked by the publisher challenge. Stock Playwright can fetch individual section pages, and the scraper now supports manifest-only fetching of `Section`/`Subsection` rows plus CSV-derived `CONTAINS` graph edges. Bounded proof on 2026-08-28 fetched 31 of the first 50 section URLs with isolated Playwright contexts; 19 still returned publisher challenge pages. The source package must remain `productionReady: false` and fail closed until a full seed has no required missing sections.
