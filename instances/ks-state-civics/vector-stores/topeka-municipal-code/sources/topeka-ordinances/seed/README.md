# Topeka Ordinance PDF Seed

This folder is the local seed skeleton for official Topeka ordinance PDFs.

Expected layout:

```text
seed/
  raw/
    pdfs/                   # downloaded ordinance PDFs from city document URLs
  extracted/                # retained Marker/local PDF extraction outputs
  manifests/                # ordinances.jsonl and crawl/download reports
  citation-url-map.jsonl    # optional source identity -> caller-hosted URL mapping
```

Each manifest row should keep the official PDF URL in `pdf_url`. The ingestion path must set document `source_uri` from that field so caller-side citations remain clickable without hosting scraped code text.
