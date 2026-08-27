# Kansas Court Decisions Source Package

This vector store is the KS State Civics court-decision corpus. The source
package records how the source archive is collected, how updates are diffed,
and how ingestion must run through the ExAIS API.

Production rule: do not update Postgres, Qdrant, MinIO, or graph tables
directly from this package. Use the API ingestion runner and record proof
artifacts after each update.

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
