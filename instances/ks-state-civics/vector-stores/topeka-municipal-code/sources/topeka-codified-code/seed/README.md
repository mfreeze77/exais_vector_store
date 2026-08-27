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

Current status: the upstream scraper ZIP is preserved in `raw/vendor/`. Plain HTTP is blocked by the publisher challenge, but a normal Playwright Chromium probe loaded real TMC root and section content on 2026-08-27, and the existing parser successfully extracted section `18.55.010`. A full Playwright crawler has not been implemented yet. The source package must fail closed if `sections.jsonl` is missing or empty.
