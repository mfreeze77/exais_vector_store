# Backup/Restore Runbook

Backup bundle includes instance manifest, image digests, Postgres dump/WAL, Qdrant snapshots, OpenSearch snapshots, object manifest/checksums, profile configs, and audit pointer.

Restore order: verify checksums, provision cell, restore secrets/config, restore Postgres, restore object storage, restore/rebuild Qdrant, restore/rebuild OpenSearch, run migrations, run smoke retrieval, mark drill complete.
