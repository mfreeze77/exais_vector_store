# Gate 2: Scale And Repair

This gate runs only after Gate 1 proves the cell boots from pulled registry
images. All commands must use `infra/docker/compose.cell.yml`; source-build
compose files do not count.

- [x] `python scripts/release/seed-scale.py --cell local --documents 10000 --headings-per-doc 8` submits 10,000 documents through the queued file-batch path and uses real Qdrant with a real configured embedding provider.
- [x] SQL output shows `0` `ingestion_jobs` in terminal `failed` status.
- [x] SQL output shows active chunks `>= 80000`.
- [x] SQL output shows active chunks with `dense_index_status='indexed'` and `sparse_index_status='indexed'` `>= 80000`.
- [x] SQL output proves no active real embedding profile is backed by `hash_mock`.
- [x] `python scripts/release/search-bench.py --cell local --vector-store-id <id> --queries 200 --warmup-queries 100 --p95-ms 500 --pace-ms 800` prints p50/p95, has `0` errors, and has p95 `< 500ms` while respecting the default API rate limit.
- [x] `python scripts/release/qdrant-chaos-repair.py --cell local --documents 500` kills Qdrant during queued ingest, restarts it, deletes a bounded set of real Qdrant points, runs the reindex repair endpoint with `force=true`, proves Qdrant point counts recover, and SQL shows `0` active chunks in pending/failed/unindexed status.
- [x] `docker-compose ... ps` output during this gate shows the cell services are pulled-image services, not local build services.

## Current Status

WAVE-013 reran Gate 2 after WAVE-011 invalidated the original semantic scale
proof. The current passing proof uses real OpenAI embeddings for markdown scale
data, real Qdrant, real SQL counts, query-embedding cache warmup for repeated
search latency, and a fixed Qdrant chaos repair script whose delete order
matches the maintenance reindex cursor.

Cold external-provider query embedding latency is not hidden: before the cache
fix, `search-bench.py --queries 200 --p95-ms 500` returned `errors=0` but
`p95_ms=1031`. After caching, an unpaced run hit the product rate limiter with
`41` `429` responses. The release command now uses `--warmup-queries` and
`--pace-ms` so the measured retrieval path is repeatable without weakening API
rate limits.

## WAVE-013 Real Provider Proof

```text
VECTOR_STORE_ID=vs_891c4834a6f94c51a0509fb2
  status   | count
-----------+-------
 completed | 10000

 failed_jobs | active_jobs | active_chunks | indexed_chunks
-------------+-------------+---------------+----------------
           0 |           0 |         90000 |          90000

        embedding_profile_id        | model_provider |       model_name       | dimensions | count
------------------------------------+----------------+------------------------+------------+-------
 openai_text_embedding_3_small_1536 | openai         | text-embedding-3-small |       1536 | 90000

 full_store_real_profile_hash_rows
-----------------------------------
                                 0

 global_active_real_profile_hash_rows
--------------------------------------
                                    0

{"result":{"count":90000},"status":"ok","time":0.184690167}
```

```text
python scripts/release/search-bench.py --cell local --vector-store-id vs_891c4834a6f94c51a0509fb2 --queries 200 --warmup-queries 100 --p95-ms 500 --pace-ms 800
warmup_queries=100
warmup_errors=0
queries=200
errors=0
p50_ms=289
p95_ms=430
avg_ms=311
[exit 0]
```

```text
python scripts/release/qdrant-repair-all.py --cell local --vector-store-id vs_b3a7ca4774104ae9891e2cd1 --batch-size 1000 --timeout-seconds 1200
qdrant_total_before_repair=4499
repair_all_iteration=1 processed=1000 has_more=true
repair_all_iteration=2 processed=1000 has_more=true
repair_all_iteration=3 processed=1000 has_more=true
repair_all_iteration=4 processed=1000 has_more=true
repair_all_iteration=5 processed=500 has_more=false
repair_all_total_processed=4500
qdrant_total_after_repair_all=4500
repair_all_sql_counts_final={"active_chunks": 4500, "active_jobs": 0, "failed_jobs": 0, "indexed_chunks": 4500}
Qdrant repair-all complete.
```

```text
python scripts/release/qdrant-chaos-repair.py --cell local --documents 500 --timeout-seconds 1200
VECTOR_STORE_ID=vs_3060bb4fb54945d994a9a395
selected_qdrant_points=1000 collections=["svs_biz_dev_openai_text_embedding_3_small_1536"]
qdrant_counts_before_delete={"svs_biz_dev_openai_text_embedding_3_small_1536": 4500}
qdrant_counts_after_delete={"svs_biz_dev_openai_text_embedding_3_small_1536": 3500}
repair_response={"action": "reindex_chunks", "details": {"batch_size": 1000, "has_more": true, "last_chunk_id": "chk_5261a31d76ce4185a3eebbbd"}, "ok": true, "processed": 1000}
qdrant_counts_after_repair={"svs_biz_dev_openai_text_embedding_3_small_1536": 4500}
0|0|0|0|4500|4500
Qdrant chaos repair complete.
```

## Proof Snapshot

The following snapshot is retained as historical queue/Qdrant operations proof
only. It is not semantic embedding proof after WAVE-011.

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
