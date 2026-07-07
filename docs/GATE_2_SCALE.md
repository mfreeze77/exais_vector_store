# Gate 2: Scale And Repair

This gate runs only after Gate 1 proves the cell boots from pulled registry
images. All commands must use `infra/docker/compose.cell.yml`; source-build
compose files do not count.

- [x] `python scripts/release/seed-scale.py --cell local --documents 10000 --headings-per-doc 8` submits 10,000 documents through the queued file-batch path and uses real Qdrant.
- [x] SQL output shows `0` `ingestion_jobs` in terminal `failed` status.
- [x] SQL output shows active chunks `>= 80000`.
- [x] SQL output shows active chunks with `dense_index_status='indexed'` and `sparse_index_status='indexed'` `>= 80000`.
- [x] `python scripts/release/search-bench.py --cell local --vector-store-id <id> --queries 200 --p95-ms 500` prints p50/p95, has `0` errors, and has p95 `< 500ms`.
- [x] `python scripts/release/qdrant-chaos-repair.py --cell local --documents 500` kills Qdrant during queued ingest, restarts it, deletes a bounded set of real Qdrant points, runs the reindex repair endpoint with `force=true`, proves Qdrant point counts recover, and SQL shows `0` active chunks in pending/failed/unindexed status.
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
[original Wave 007 repair response superseded by Wave 008/Wave 009 proof below]
0|0|0|0|4500|4500
Qdrant chaos repair complete.
```

Wave 008 tightened the repair proof after the original Gate 2 run. Current
`qdrant-chaos-repair.py` output must include a non-zero repair response and
Qdrant count recovery similar to:

```text
selected_qdrant_points=75 collections=["svs_biz_dev_openai_text_embedding_3_small_1536"]
qdrant_counts_before_delete={"svs_biz_dev_openai_text_embedding_3_small_1536": 160}
qdrant_counts_after_delete={"svs_biz_dev_openai_text_embedding_3_small_1536": 85}
repair_response processed=75
qdrant_counts_after_repair={"svs_biz_dev_openai_text_embedding_3_small_1536": 160}
0|0|0|0|160|160
```

Wave 009 added a cursor-based repair-all proof for drift larger than a single
maintenance batch:

```text
python scripts/release/qdrant-repair-all.py --cell local --proof --documents 24 --headings-per-doc 3 --batch-size 25 --delete-count 55 --timeout-seconds 600
repair_all_seed_sql_counts={"active_chunks": 96, "active_jobs": 0, "failed_jobs": 0, "indexed_chunks": 96}
repair_all_deleted_points=55
qdrant_total_after_delete=41
repair_all_iteration=1 processed=25 has_more=true
repair_all_iteration=2 processed=25 has_more=true
repair_all_iteration=3 processed=25 has_more=true
repair_all_iteration=4 processed=21 has_more=false
repair_all_total_processed=96
qdrant_total_after_repair_all=96
repair_all_search_results=5
repair_all_sql_counts_final={"active_chunks": 96, "active_jobs": 0, "failed_jobs": 0, "indexed_chunks": 96}
```
