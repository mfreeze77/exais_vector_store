# Hetzner Sizing

## Micro-production

Small shared cell:

- 16–64 GB RAM depending instance count.
- Dedicated vCPU instance where possible.
- Local SSD/NVMe preferred for hot DB/index paths.
- Object-storage backups.

Dedicated business cell:

- 64–128 GB RAM.
- 16+ vCPU/threads.
- Local NVMe.
- Separate Qdrant/OpenSearch/Postgres data paths.

Serious 2 TB retrieval cell:

- Dedicated server preferred.
- 128–256 GB RAM.
- 16–32+ CPU threads.
- 4 × 3.84 TB NVMe RAID10 or 2 × 7.68 TB mirror.
- Remote object storage for originals/snapshots/backups.

2 TB active retrieval does not mean a 2 TB disk. Plan for active corpus, vector overhead, sparse index overhead, originals, parsed artifacts, snapshots, WAL/base backups, rebuild headroom, and replicas.
