# WAVE-027 OpenAI File Batch Lifecycle Parity

## Summary

Tighten the OpenAI-compatible vector-store file-batch surface so SDK-style
`create_and_poll`, retrieve, cancel, and list-files workflows see consistent
OpenAI-shaped batch objects and fail-fast request validation.

Official OpenAI references checked on 2026-07-08:

- File search guide: adding files to vector stores is asynchronous; callers can
  retrieve the vector store and monitor `file_counts`, and file batches accept
  either `file_ids` or a per-file `files` array.
- File-batch create reference: `file_ids` and `files` are mutually exclusive,
  current generated reference caps the batch at 2000 files, and returned batch
  objects include `id`, `object`, `created_at`, `vector_store_id`, `status`, and
  `file_counts`.
- File-batch list-files reference: supports `limit`, `order`, `after`,
  `before`, and status `filter`.

## Tickets

| Ticket | Status | Type | Outcome |
|---|---|---|---|
| W27-001 | Complete | Implementation/Test | Validate OpenAI file-batch create inputs, return consistent batch objects, preserve global metadata/chunking for `file_ids`, and fix cancel/list proof. |

## Code Anchors

- `apps/api/svs_api/main.py`
- `apps/worker/svs_worker/main.py`
- `tests/test_openai_files.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`

## W27-001 Acceptance Criteria

- [x] File-batch create rejects requests that mix `file_ids` and `files`, reject
  non-list inputs, and reject batches over the current OpenAI reference cap.
- [x] `file_ids` batch creation applies request-level `attributes`/`metadata`
  and `chunking_strategy` to every linked vector-store file.
- [x] Create, retrieve, and cancel return one normalized
  `vector_store.file_batch` object shape with complete `file_counts` keys and
  `created_at`.
- [x] Cancel targets queued jobs for the batch, accumulates existing cancelled
  counts, sets `in_progress` to zero, and does not require an extra read scope
  through the retrieve route.
- [x] List-files keeps OpenAI pagination/status controls and returns
  vector-store file payloads for the requested batch.
- [x] Focused tests cover request validation, normalized payload shape,
  request-level metadata/chunking inheritance, cancel SQL/count behavior, and
  list-files helper behavior.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -q packages apps tests
exit 0

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_files.py tests/test_openai_vector_store_object.py tests/test_openai_compat_search.py tests/test_retrieval_profile_resolution.py
70 passed, 2 warnings in 3.41s

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
152 passed, 2 warnings in 4.35s

git diff --check
exit 0
```

## Notes

This ticket does not add database columns, alter API-key resolution, change RLS
policies, implement OpenAI managed vector-store fallback, change retrieval
ranking, or remove ExAIS inline-file batch extensions.
