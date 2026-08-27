# KS Courts Seed Folder

This folder documents the portable seed layout for the `kscourts-decisions`
source. Large artifacts are not committed here; production copies live in object
storage under the URIs declared in `source.yaml`.

Expected layout:

```text
seed/
  raw/                  # copied or mirrored source PDFs when included in a bundle
  extracted/            # retained Markdown/HTML extracted from each source PDF
  manifests/            # source manifest snapshots and checksum reports
  citation-url-map.jsonl # optional source identity -> caller-hosted URL mapping
```

Citation policy:

- Current seeded records use the official PDF URL as `source_uri`.
- Extracted Markdown/HTML artifacts are retained for audit, recall debugging,
  graph rebuilds, and optional caller-hosted evidence pages.
- If StateCivics hosts extracted evidence pages later, add rows to
  `citation-url-map.jsonl` keyed by stable source identity/checksum, then run a
  controlled source-URI remap proof. Do not re-vectorize solely to change a
  citation URL.
