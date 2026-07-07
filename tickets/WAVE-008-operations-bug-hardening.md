# WAVE-008 Operations Bug Hardening

## Summary

Fix operational bugs found after the Docker-first local cell proof, excluding
Docker Hub push and VPS deployment. Keep changes scoped to local/cell runtime
truthfulness and reusable operations scripts.

## Tickets

| Ticket | Status | Specialist | Scope |
| --- | --- | --- | --- |
| W8-001 | Complete | Implementation | Remove hardcoded `local` cell network fallbacks from release proof scripts. |
| W8-002 | Complete | Implementation | Make `/readyz` fail when required runtime dependencies are unavailable. |
| W8-003 | Complete | Test/Proof | Prove repair endpoint can perform actual reindex work, not only report a clean state after Qdrant restart. |

## Acceptance Criteria

- [x] Release scripts that fall back to an external Docker container derive the compose network from `--cell`.
- [x] `cell-smoke.py`, `scale_common.py`, and `search-bench.py` no longer hardcode `exais-vector-store-local_default`.
- [x] `/readyz` returns HTTP `503` when DB is unavailable.
- [x] `/readyz` returns HTTP `503` when strict Qdrant dense indexing is configured and Qdrant is unavailable.
- [x] `/healthz` remains a lightweight process/build endpoint and does not become a dependency gate.
- [x] Unit tests cover dependency readiness behavior without requiring live Docker services.
- [x] Container/cell proof confirms `/readyz` still returns HTTP `200` in the healthy pulled cell.
- [x] Qdrant repair proof deletes real points for a vector store and shows the Qdrant count drops.
- [x] `/api/v1/maintenance/reindex` returns non-zero `processed` for the deleted points.
- [x] Qdrant repair proof shows the vector-store point count returns to its pre-delete count.
- [x] Final SQL after repair shows zero failed jobs and zero active pending/failed/unindexed chunks.

## Verification

```bash
PYTHONPATH=packages/svs_common;apps/api;apps/worker;apps/model_gateway;apps/instance_agent python -m compileall -f -q packages apps tests scripts
docker run --rm -v "${PWD}:/work" -w /work --network exais-vector-store-local_default -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_readyz.py tests/test_release_cell_network.py
docker run --rm -v "${PWD}:/work" -w /work --network exais-vector-store-local_default -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_qdrant_repair_proof_script.py
python scripts/release/cell-smoke.py --cell local --worker-scale 4
python scripts/release/qdrant-chaos-repair.py --cell local --documents 40 --headings-per-doc 3 --kill-delay-seconds 0.5 --outage-seconds 2 --repair-batch-size 75 --timeout-seconds 600
```

## Proof Notes

- `python -m compileall -f -q packages apps tests scripts` exited `0`.
- Focused containerized tests:

```text
.....                                                                    [100%]
5 passed, 2 warnings in 3.37s
```

- Rebuilt and published versioned app images to the local registry after the
  fix. API image proof:

```text
Successfully tagged localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate
localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate	sha256:766e3ca75cc3da7e3d0d9cf3fac641115ea1882800aadc09fb4f5e839b7c30ab	142212424
0.9.8-production-candidate: digest: sha256:766e3ca75cc3da7e3d0d9cf3fac641115ea1882800aadc09fb4f5e839b7c30ab size: 2942
```

- Removed local app tags before recreating the cell:

```text
Error response from daemon: No such image: localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate
Error response from daemon: No such image: localhost:5000/expertaiservices/exai-vector-store-worker:0.9.8-production-candidate
Error response from daemon: No such image: localhost:5000/expertaiservices/exai-vector-store-model-gateway:0.9.8-production-candidate
Error response from daemon: No such image: localhost:5000/expertaiservices/exai-vector-store-admin-ui:0.9.8-production-candidate
Error response from daemon: No such image: localhost:5000/expertaiservices/exai-vector-store-instance-agent:0.9.8-production-candidate
```

- `python scripts/release/cell-smoke.py --cell local --worker-scale 4` passed:

```text
{"ready":true,"db":true,"qdrant":true}
200
Host loopback curl failed; checking through an external curl container on the cell network.
{"ready":true,"db":true,"qdrant":true}
200
Unsafe SVS startup configuration occurrences: 0
29 passed, 1 skipped, 2 warnings in 1.93s
5 passed, 8 warnings in 1.83s
```

- `python -m pytest -q -rs tests/test_qdrant_repair_proof_script.py` inside
  the API image with the repo mounted:

```text
...                                                                      [100%]
3 passed in 0.27s
```

- Combined focused Wave 008 test set:

```text
........                                                                 [100%]
8 passed, 2 warnings in 4.18s
```

- `python scripts/release/qdrant-chaos-repair.py --cell local --documents 40
  --headings-per-doc 3 --kill-delay-seconds 0.5 --outage-seconds 2
  --repair-batch-size 75 --timeout-seconds 600` proved actual reindex work:

```text
VECTOR_STORE_ID=vs_3c7695972fe44f3f86581595
completed |    40
0|0|0
selected_qdrant_points=75 collections=["svs_biz_dev_openai_text_embedding_3_small_1536"]
qdrant_counts_before_delete={"svs_biz_dev_openai_text_embedding_3_small_1536": 160}
qdrant_counts_after_delete={"svs_biz_dev_openai_text_embedding_3_small_1536": 85}
{"ok":true,"action":"reindex_chunks","processed":75,"details":{}}
200
repair_response={"action": "reindex_chunks", "details": {}, "ok": true, "processed": 75}
qdrant_counts_after_repair={"svs_biz_dev_openai_text_embedding_3_small_1536": 160}
0|0|0|0|160|160
Qdrant chaos repair complete.
```

- Qdrant interruption proof:

```text
$ docker kill exais-vector-store-local-qdrant-1
exais-vector-store-local-qdrant-1
$ curl /readyz inside api
{"ready":false,"db":true,"qdrant":false}
503
$ curl /healthz inside api
{"ok":true,"service":"svs-api","version":"0.9.8-production-candidate","sparse_backend":"postgres_fts","dense_backend":"qdrant"}
200
```

- Postgres interruption proof:

```text
$ docker kill exais-vector-store-local-postgres-1
exais-vector-store-local-postgres-1
$ curl /readyz inside api
{"ready":false,"db":false,"qdrant":true}
503
```

- Final recovery proof:

```text
{"ready":true,"db":true,"qdrant":true}
200
exais-vector-store-local-admin-ui-1        localhost:5000/expertaiservices/exai-vector-store-admin-ui:0.9.8-production-candidate        Up 2 minutes (healthy)
exais-vector-store-local-api-1             localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate             Up 2 minutes (healthy)
exais-vector-store-local-postgres-1        postgres:17                                                                                  Up 16 seconds (healthy)
exais-vector-store-local-qdrant-1          qdrant/qdrant:v1.14.1                                                                        Up 51 seconds (healthy)
exais-vector-store-local-worker-1          localhost:5000/expertaiservices/exai-vector-store-worker:0.9.8-production-candidate          Up 13 seconds (healthy)
exais-vector-store-local-worker-2          localhost:5000/expertaiservices/exai-vector-store-worker:0.9.8-production-candidate          Up 13 seconds (healthy)
exais-vector-store-local-worker-3          localhost:5000/expertaiservices/exai-vector-store-worker:0.9.8-production-candidate          Up 13 seconds (healthy)
exais-vector-store-local-worker-4          localhost:5000/expertaiservices/exai-vector-store-worker:0.9.8-production-candidate          Up 13 seconds (healthy)
```

- Wave 008 is complete. Docker Hub push and VPS deployment remain outside this
  wave by design.
