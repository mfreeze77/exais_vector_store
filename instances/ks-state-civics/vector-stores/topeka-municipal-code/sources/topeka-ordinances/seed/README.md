# Topeka Ordinance PDF Seed

This folder is the local seed root for official Topeka ordinance PDFs.

Expected layout:

```text
seed/
  raw/
    pdfs/                   # downloaded ordinance PDFs from city document URLs
  extracted/                # retained Marker/local PDF extraction outputs
  manifests/                # ordinances.jsonl and crawl/download reports
  citation-url-map.jsonl    # optional source identity -> caller-hosted URL mapping
```

Current local proof from 2026-08-28:

- `364` official ordinance PDFs are retained under `raw/pdfs/`.
- `364` Markdown extractions from the external RunPod Marker path are retained under `extracted/`.
- `manifests/ordinances.jsonl` and `manifests/ordinance-extractions.jsonl` record stable source identity, PDF SHA-256, Markdown paths, and extraction status.
- The local vector store `vs_d4185d1004604f08a55299fa` has `364` ordinance documents and `3,154` ordinance chunks indexed.
- `5/5` ordinance PDF recall checks pass through the live local ExAIS API with official PDF citations.

Each manifest row keeps the official PDF URL in `pdf_url`. The ingestion path sets document `source_uri` from that field so caller-side citations remain clickable without hosting scraped code text. The raw PDFs and extracted Markdown are bulky reproducible artifacts and are intentionally ignored by Git; the committed manifests and lock file are the durable proof contract.
