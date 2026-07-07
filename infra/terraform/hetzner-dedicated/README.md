# Hetzner Dedicated Production Cell

For serious 2 TB retrieval, prefer dedicated local NVMe over cloud volumes.

Suggested shape:

- 128–256 GB RAM
- 16–32+ CPU threads
- 4 × 3.84 TB NVMe RAID10 or 2 × 7.68 TB mirror
- object-storage backups
- Qdrant/OpenSearch/Postgres hot paths on local NVMe
