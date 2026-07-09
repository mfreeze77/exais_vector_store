# WAVE-026 OpenAI Vector Store Expiration Activity

## Summary

Implement OpenAI-style vector-store expiration activity for citation-producing
retrieval paths. A vector store using `expires_after.anchor=last_active_at`
must slide `expires_at` when the store is used, and expired stores must fail
closed before search can return stale cited content.

Official OpenAI reference checked on 2026-07-08:

- File search guide: vector stores support expiration policies such as
  `{"anchor": "last_active_at", "days": 7}`, and runs fail after the vector
  store expires.

## Tickets

| Ticket | Status | Type | Outcome |
|---|---|---|---|
| W26-001 | Complete | Implementation/Test | Refresh vector-store activity on attach, ingestion, search, context-pack, and Responses file-search; fail closed for expired stores before retrieval. |

## Code Anchors

- `packages/svs_common/svs_common/vector_store_repo.py`
- `packages/svs_common/svs_common/ingestion.py`
- `apps/api/svs_api/main.py`
- `tests/test_openai_vector_store_object.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`

## W26-001 Acceptance Criteria

- [x] `expires_after.anchor=last_active_at` recalculates `expires_at` whenever
  vector-store activity is recorded.
- [x] Direct OpenAI vector-store search and Responses file-search refresh
  `last_active_at` before retrieval.
- [x] Native retrieval search and context-pack refresh `last_active_at` when a
  `vector_store_id` is supplied.
- [x] File attach, direct ingestion, and queued ingestion use the same active
  vector-store guard and activity refresh path.
- [x] Expired vector stores fail closed before retrieval runs, even if the
  maintenance sweeper has not yet marked rows `expired` or deactivated chunks.
- [x] Existing maintenance sweep behavior remains the cleanup path for marking
  expired rows and queuing stale-vector purge work.
- [x] Focused tests cover expiration policy math, refresh SQL, expired-store
  preflight, existing-file attach refresh, and OpenAI search not invoking
  retrieval after an expired preflight.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -q packages apps tests
exit 0

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_vector_store_object.py tests/test_openai_compat_search.py tests/test_retrieval_profile_resolution.py
58 passed, 2 warnings in 3.10s

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
145 passed, 2 warnings in 4.34s

git diff --check
exit 0
```

## Notes

This ticket does not add new database columns, change OpenAI citation annotation
shape, add thread-vector-store default expiration, alter the maintenance worker
schedule, or implement file-batch lifecycle semantics beyond active-store
preflight and activity refresh.
