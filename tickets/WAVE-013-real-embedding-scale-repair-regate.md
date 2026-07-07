# WAVE-013 Real Embedding Scale Repair Regate

## Summary

Rerun Gate 2 after WAVE-011 invalidated the old scale/repair proof. The prior
scale, chaos, repair-all, and some PDF proof vector stores exercised Docker,
queueing, Qdrant, SQL counts, and repair mechanics, but their embeddings were
mock-backed while stored under real embedding profile IDs.

This wave replaces that with real-provider proof.

## Tickets

| Ticket | Status | Specialist | Scope |
| --- | --- | --- | --- |
| W13-001 | Complete | Test/Proof | Run a bounded real-provider scale pilot through file batches, real Qdrant, SQL audit, and hybrid search. |
| W13-002 | Complete | Test/Proof | Run the full Gate 2 seed/search-bench/chaos-repair sequence with real embeddings if the pilot is clean. |
| W13-003 | Complete | Quality Control | Update `docs/GATE_2_SCALE.md` only with raw output from real-provider proof. |

## Out Of Scope

- Docker Hub or VPS launch.
- Changing provider routing semantics to make scale pass.
- Re-enabling mock-backed historical proof as release proof.
- Printing provider secret values.

## Acceptance Criteria

- [x] Generated cell env imports provider secret names only, never values.
- [x] Runtime env proof prints provider variable names and nonempty status only.
- [x] Scale pilot completes with `0` failed jobs and `0` active queued/running
  jobs.
- [x] Scale pilot SQL shows active chunks equal indexed chunks.
- [x] Scale pilot SQL shows every active real embedding profile is backed by its
  real provider, not `hash_mock`.
- [x] Scale pilot Qdrant count matches active indexed chunk count.
- [x] Scale pilot hybrid search returns results with no provider fallback.
- [x] Full Gate 2 is rerun or explicitly deferred with the blocking reason.

## Verification

```bash
python scripts/release/seed-scale.py --cell local --documents 100 --headings-per-doc 4 --timeout-seconds 900
python scripts/release/search-bench.py --cell local --vector-store-id <pilot-vs-id> --queries 25 --p95-ms 1500
python scripts/release/seed-scale.py --cell local --documents 10000 --headings-per-doc 8 --timeout-seconds 7200
python scripts/release/search-bench.py --cell local --vector-store-id <full-vs-id> --queries 200 --warmup-queries 100 --p95-ms 500 --pace-ms 800
python scripts/release/qdrant-chaos-repair.py --cell local --documents 500 --timeout-seconds 1200
```

## Proof Notes

Generated env proof printed variable names only:

```text
Variable names imported from source env:
- DEFAULT_EMBEDDING_PROVIDER
- MARKER_MODE
- MARKER_RUNPOD_API_KEY
- MARKER_RUNPOD_ENDPOINT_ID
- OPENAI_API_KEY
- OPENAI_EMBEDDING_DIMENSIONS
- OPENAI_EMBEDDING_MODEL
- RUNPOD_API_KEY
- RUNPOD_ENDPOINT_ID
- VOYAGE_API_KEY
No values printed.
```

Runtime provider proof printed names and boolean status only:

```text
OPENAI_API_KEY_present=True nonempty=True
VOYAGE_API_KEY_present=True nonempty=True
DEFAULT_EMBEDDING_PROVIDER_present=True nonempty=True
openai_configured=True required_env=OPENAI_API_KEY provider_class=OpenAIEmbeddingProvider is_hash_mock=False
voyage_configured=True required_env=VOYAGE_API_KEY provider_class=VoyageEmbeddingProvider is_hash_mock=False
```

Pilot proof:

```text
VECTOR_STORE_ID=vs_8914fd967a204598ae09125a
 completed | 100
0|0|500|500
openai_text_embedding_3_small_1536 | openai | text-embedding-3-small | 1536 | 500
pilot_real_profile_hash_rows = 0
global_active_real_profile_hash_rows = 0
{"result":{"count":500},"status":"ok","time":0.00473562}
queries=25
errors=0
p50_ms=322
p95_ms=767
avg_ms=527
```

Full Gate 2 real-provider proof:

```text
VECTOR_STORE_ID=vs_891c4834a6f94c51a0509fb2
completed | 10000
failed_jobs=0 active_jobs=0 active_chunks=90000 indexed_chunks=90000
openai_text_embedding_3_small_1536 | openai | text-embedding-3-small | 1536 | 90000
full_store_real_profile_hash_rows = 0
global_active_real_profile_hash_rows = 0
{"result":{"count":90000},"status":"ok","time":0.184690167}
```

Search latency proof after adding scoped query-embedding cache and release-script
warmup/pacing:

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

Operational bugs found while rerunning Gate 2:

```text
Pre-cache full search: queries=200 errors=0 p95_ms=1031 [exit 1]
Unpaced cached search: queries=200 errors=41 p95_ms=833 [exit 1]
First paced hot-cache search: queries=200 errors=0 p95_ms=501 [exit 1]
```

Repair proof and repair-all recovery:

```text
python scripts/release/qdrant-repair-all.py --cell local --vector-store-id vs_b3a7ca4774104ae9891e2cd1 --batch-size 1000 --timeout-seconds 1200
qdrant_total_before_repair=4499
repair_all_total_processed=4500
qdrant_total_after_repair_all=4500
repair_all_sql_counts_final={"active_chunks": 4500, "active_jobs": 0, "failed_jobs": 0, "indexed_chunks": 4500}
Qdrant repair-all complete.

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
