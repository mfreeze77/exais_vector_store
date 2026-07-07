# Gate 2: Scale And Repair

This gate runs only after Gate 1 proves the cell boots from pulled registry
images. All commands must use `infra/docker/compose.cell.yml`; source-build
compose files do not count.

- [x] `python scripts/release/seed-scale.py --cell local --documents 10000 --headings-per-doc 8` submits 10,000 documents through the queued file-batch path and uses real Qdrant.
- [x] SQL output shows `0` `ingestion_jobs` in terminal `failed` status.
- [x] SQL output shows active chunks `>= 80000`.
- [x] SQL output shows active chunks with `dense_index_status='indexed'` and `sparse_index_status='indexed'` `>= 80000`.
- [x] `python scripts/release/search-bench.py --cell local --vector-store-id <id> --queries 200 --p95-ms 500` prints p50/p95, has `0` errors, and has p95 `< 500ms`.
- [x] `python scripts/release/qdrant-chaos-repair.py --cell local --documents 500` kills Qdrant during queued ingest, restarts it, runs the reindex repair endpoint, and SQL shows `0` active chunks in pending/failed/unindexed status.
- [x] `docker-compose ... ps` output during this gate shows the cell services are pulled-image services, not local build services.

## Proof Snapshot

```text
VECTOR_STORE_ID=vs_221e9fa2ae704898912b1bd5
  status   | count
-----------+-------
 completed | 10000
 failed_jobs | active_jobs | active_chunks | indexed_chunks
-------------+-------------+---------------+----------------
           0 |           0 |         90000 |          90000
queries=200
errors=0
p50_ms=221
p95_ms=371
avg_ms=239
VECTOR_STORE_ID=vs_a4a1a34865624dfb99970c39
repair_response={"action": "reindex_chunks", "details": {}, "ok": true, "processed": 0}
0|0|0|0|4500|4500
Qdrant chaos repair complete.
```
