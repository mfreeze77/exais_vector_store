# WAVE-060 Expiration Sweeper Proof

## Goal

Close the stale tracker gap for OpenAI vector-store expiration policies by
proving the existing expiration sweeper behavior and updating status from
scaffolded to implemented.

## Scope

- Add focused maintenance tests for `MaintenanceService.sweep_expired_vector_stores`.
- Prove the API route delegates to the sweeper under `maintenance:write` scope
  and commits.
- Update tracker/docs to state that the sweeper is implemented and covered.

## Non-Goals

- Changing expiration policy semantics.
- Changing retrieval fail-closed behavior for expired stores.
- Changing worker queue claiming or physical index cleanup behavior.
- Running live Qdrant/OpenSearch cleanup proof.

## Acceptance Criteria

- [x] Sweeper marks expired active/completed vector stores as `expired`.
- [x] Sweeper deactivates chunks for expired stores and marks dense/sparse index
  status `delete_queued`.
- [x] Sweeper queues one `purge_stale_vectors` job per expired store.
- [x] Sweeper writes a maintenance audit event containing expired store ids and
  purge job ids.
- [x] The `/api/v1/maintenance/expire-vector-stores` route requires
  `maintenance:write`, delegates to the sweeper, and commits.
- [x] Tracker no longer says expiration sweeper is only scaffolded.

## Verification

- Focused maintenance proof tests.
- Full non-integration suite.
- `python -m compileall -f -q packages apps tests`.
- `git diff --check`.

## Proof

Focused expiration sweeper verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_index_cleanup.py
4 passed, 2 warnings
```

Compile proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass
```

Full non-integration proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
280 passed, 2 warnings
```

Whitespace proof:

```text
git diff --check
pass
```

Notes:

- The two warnings are existing FastAPI `on_event` deprecation warnings.
- This proof does not run live Qdrant/OpenSearch cleanup; it verifies stale
  cleanup enqueue and the existing `purge_stale_vectors` unit path.
