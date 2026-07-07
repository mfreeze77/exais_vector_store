# WAVE-012 Vector Store Delete RLS Soft-Delete

## Summary

Fix the local-cell operation bug where `DELETE /v1/vector_stores/{id}` returns
HTTP 500 while trying to soft-delete chunks under FORCE RLS.

Observed proof:

```text
DELETE /v1/vector_stores/vs_243480b176e54c159f561dea HTTP/1.1" 500 Internal Server Error
psycopg.errors.InsufficientPrivilege: new row violates row-level security policy for table "chunks"
```

The chunk RLS policy already allows tenant-scoped system maintenance mutations
when `svs.system_worker=true`. Vector-store delete is such a mutation because it
marks chunks inactive and queues physical index cleanup. The API delete path did
not set that transaction-local flag before updating chunks.

## Tickets

| Ticket | Status | Specialist | Scope |
| --- | --- | --- | --- |
| W12-001 | Complete | Implementation | Set transaction-local `svs.system_worker=true` inside vector-store delete before chunk soft-delete. |
| W12-002 | Complete | Test/Proof | Prove API delete returns success and chunks become inactive without weakening tenant/business RLS. |

## Out Of Scope

- Changing tenant IDs, business instance IDs, API-key auth, or retrieval ACLs.
- Making inactive chunks readable to normal retrieval callers.
- Reworking physical Qdrant/OpenSearch cleanup.

## Acceptance Criteria

- [x] `DELETE /v1/vector_stores/{id}` no longer fails with chunk RLS when the
  caller has `vector_stores:delete` or `vector_stores:write`.
- [x] The system-worker flag is transaction-local and only used for the
  tenant/business-scoped delete mutation.
- [x] Deleted vector store chunks are marked inactive and queued for index
  deletion.
- [x] Active real-profile/hash mismatch audit remains zero after the delete
  proof.
- [x] Tests cover the transaction-local system-worker setting before chunk
  soft-delete.

## Verification

```bash
PYTHONPATH=packages/svs_common:apps/api:apps/worker:apps/model_gateway:apps/instance_agent python -m pytest -q -rs tests/test_vector_store_delete.py
python scripts/release/build-images.py --registry-prefix localhost:5000/expertaiservices --service api
python scripts/release/publish-images.py --registry-prefix localhost:5000/expertaiservices --service api
python scripts/release/cell-up.py --cell local --worker-scale 4 --timeout-seconds 300
```

## Proof Notes

Focused test proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_embedding_providers.py tests/test_vectorization_plan.py tests/test_generate_cell_env.py tests/test_vector_store_delete.py
.................                                                        [100%]
17 passed in 1.95s
```

Live API delete proof after rebuilding and pulling the fixed API image:

```text
POST /v1/vector_stores status=200
{"id":"vs_b90f0655ef314ac8afec7ef9","object":"vector_store","name":"Delete RLS Proof","status":"completed","usage_bytes":0,"attributes":{},"created_at":null,"expires_after":null,"expires_at":null,"last_active_at":null}
POST /v1/vector_stores/vs_b90f0655ef314ac8afec7ef9/files status=200
{"id":"vsf_33ec12e4e14a43ffa833f8d7","object":"vector_store.file","status":"completed","vector_store_id":"vs_b90f0655ef314ac8afec7ef9"}
DELETE /v1/vector_stores/vs_b90f0655ef314ac8afec7ef9 status=200
{"id":"vs_b90f0655ef314ac8afec7ef9","object":"vector_store.deleted","deleted":true}
```

SQL proof:

```text
id                           | status
-----------------------------+---------
vs_b90f0655ef314ac8afec7ef9 | deleted

active | dense_index_status | sparse_index_status | count
--------+--------------------+---------------------+-------
f      | deleted            | deleted             |     1

status    | job_type            | count
-----------+---------------------+-------
completed | purge_stale_vectors |     1

active_real_profile_hash_rows
-------------------------------
                             0
```
