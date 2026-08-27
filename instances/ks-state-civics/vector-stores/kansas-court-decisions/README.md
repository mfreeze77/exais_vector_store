# Kansas Court Decisions Source Package

This vector store is the KS State Civics court-decision corpus. The source
package records how the source archive is collected, how updates are diffed,
and how ingestion must run through the ExAIS API.

Production rule: do not update Postgres, Qdrant, MinIO, or graph tables
directly from this package. Use the API ingestion runner and record proof
artifacts after each update.

Runtime boundary: this source package does not make the customer VPS a PDF/OCR
or embedding-model host. Raw PDF conversion belongs to the configured remote
RunPod Marker endpoint when needed. Embeddings belong to the configured external
embedding provider. The VPS runs ExAIS API/workers, metadata, object storage,
Qdrant, graph tables, retrieval, and proof orchestration.

Current embedding contract: the loaded vector collection is
`ks_civics_biz_ks_state_civics_voyage_4_docs_1024`, which means Voyage
`voyage-4` at 1024 dimensions. Changing provider, model, or dimensions requires
a new collection/vector-store rebuild and recall proof; do not point OpenAI
query embeddings at this Voyage collection.

Caller artifact contract: retain the converted Markdown/HTML output for each
source PDF and publish it at a stable caller-controlled HTTPS URL when the
caller app needs clickable citations. Ingest that URL as the document
`source_uri` so ExAIS native citations can return `citation.url` along with page
and heading metadata. Internal object-store keys are still required for audit
and restore, but they are not enough for a user-facing citation link.

Seed-folder contract: each instance source package should declare a portable
seed folder in `source.yaml`. The folder tracks raw source pointers, retained
extracted Markdown/HTML, manifest snapshots, and optional
`citation-url-map.jsonl` rows for caller-hosted evidence URLs. Scraped web pages
may keep their canonical source URL as `source_uri` while the extracted snapshot
stays internal.

Initialize or refresh the local seed skeleton with:

```bash
python scripts/release/prepare-instance-source-seeds.py \
  --instance ks-state-civics \
  --vector-store kansas-court-decisions \
  --source kscourts-decisions \
  --production \
  --execute
```

Existing-seed note: the current Kansas Court Decisions importer sets
`source_uri` from the official PDF URL when available. That is enough for
PDF-link citations and current search, but it does not point citations at
caller-hosted extracted Markdown/HTML. To add caller-side evidence pages for the
already indexed corpus, export/publish the retained converted artifacts, record
a stable URL map keyed by manifest identity/checksum, and run a controlled
source-URI remap or metadata-refresh proof. Do not re-vectorize solely to change
the citation URL target.

Current local proof:

- Vector store: `vs_a0d3ac76893e4f6f83bf2992`
- Documents: `16484`
- Chunks: `116200`
- Graph edges: `2569`
- Source manifest rows: `16728`

Before the first VPS rollout, validate this package:

```bash
python scripts/release/validate-instance-source-packages.py \
  --instance ks-state-civics \
  --production
```

Preview an update plan:

```bash
python scripts/release/instance-source-update.py \
  --instance ks-state-civics \
  --vector-store kansas-court-decisions \
  --source kscourts-decisions \
  --dry-run \
  --production
```
