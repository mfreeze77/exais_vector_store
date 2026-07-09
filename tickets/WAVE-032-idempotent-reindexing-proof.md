# WAVE-032 Idempotent Reindexing Proof

## Summary

Close `SVS-034` by pinning the existing repair/reindex behavior with focused
unit proof. The repo already has cursor-aware repair-all scripts and a
`MaintenanceService.reindex_chunks` implementation; this ticket verifies that
the implementation is idempotent at the external index boundary and only
processes intended chunks unless forced.

## Background

Reindex repair is part of end-to-end production durability. If dense or sparse
indexes drift, repair must safely replay source-of-truth chunks without
duplicating vector points or leaking across tenant/business scope. It also needs
stable cursor behavior for multi-batch repair operations.

## Scope

- Prove non-forced reindex selects only chunks with non-`indexed` dense/sparse
  status.
- Prove forced reindex omits the status filter for repair-all sweeps.
- Prove reindex upserts stable dense point IDs and sparse document IDs, so
  reruns replace/repair rather than duplicate.
- Prove cursor-missing behavior returns a clean zero-processed result without
  calling embedding or index providers.
- Update `SVS-034` tracker status with proof.

## Out Of Scope

- Live Qdrant/OpenSearch chaos drills.
- New provider adapters or credentials.
- Database migrations or schema changes.
- Worker scheduling changes.

## Acceptance Criteria

- [x] Focused tests cover default status-filtered reindex selection.
- [x] Focused tests cover forced reindex selection for repair-all.
- [x] Focused tests cover stable dense point IDs and sparse chunk IDs on replay.
- [x] Focused tests cover cursor-missing zero result without provider calls.
- [x] Broad non-integration verification passes.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_reindex_idempotency.py tests/test_qdrant_repair_all_script.py tests/test_qdrant_repair_proof_script.py
10 passed in 0.90s

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
<exit 0>

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
177 passed, 2 warnings in 3.88s

git diff --check
<exit 0>
```

## Notes

This ticket is proof-focused and does not change external index semantics.
