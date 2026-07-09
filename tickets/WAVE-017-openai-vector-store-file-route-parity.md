# WAVE-017 OpenAI Vector Store File Route Parity

## Summary

Close the next OpenAI SDK compatibility gaps around vector-store files and file
batches. OpenAI clients should be able to use the current route/method shapes
for file updates, file lists, and file-batch attachment while preserving ExAIS
RLS, scope checks, and internal attachment bookkeeping.

Official OpenAI references checked on 2026-07-08:

- `/vector_stores/{vector_store_id}/files`
- `/vector_stores/{vector_store_id}/files/{file_id}`
- `/vector_stores/{vector_store_id}/file_batches`
- `/vector_stores/{vector_store_id}/file_batches/{batch_id}/files`

## Tickets

| Ticket | Status | Type | Outcome |
|---|---|---|---|
| W17-001 | Complete | Implementation/Test | Add OpenAI-compatible vector-store file update/list and file-batch attach route-shape parity. |

## W17-001 Acceptance Criteria

- [x] `POST /v1/vector_stores/{vector_store_id}/files/{file_id}` updates file
  attributes as the OpenAI-compatible method while the existing `PATCH` alias
  remains available.
- [x] `GET /v1/vector_stores/{vector_store_id}/files` supports `limit`,
  `order`, `after`, `before`, and `filter` with public OpenAI file IDs as
  cursors.
- [x] `GET /v1/vector_stores/{vector_store_id}/file_batches/{batch_id}/files`
  supports the same OpenAI list controls.
- [x] `POST /v1/vector_stores/{vector_store_id}/file_batches` accepts OpenAI
  `files` entries containing `file_id`, optional `attributes`, and optional
  `chunking_strategy`, and preserves public `file_*` IDs in file responses and
  citations.
- [x] Public file response/search attributes do not expose internal attachment
  bookkeeping such as `attached_from_file_id`, `_file_batch_id`, or stored
  chunking-strategy sentinels.
- [x] Live proof covers Bearer API-key auth for upload, batch attach, POST file
  update, list filtering/pagination, search citation, and context-pack
  citation.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests scripts
<exit 0>

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_files.py tests/test_openai_vector_store_object.py tests/test_openai_compat_search.py
23 passed, 2 warnings in 3.20s

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
111 passed, 2 warnings in 4.07s
```

Live mounted-code proof against `exais-vector-store-local_default`:

```text
{'api_key_prefix': 'svs_live_', 'vector_store_id': 'vs_c14e03c74ea24ddd88cccf6b', 'batch_id': 'vsfb_eb9c3f7b6f0f425db18c5a3a', 'file_ids': ['file_6222a462644b4e67808dc8dd', 'file_99941fb300d24631ad3fa8e4'], 'first_page': {'first_id': 'file_6222a462644b4e67808dc8dd', 'has_more': True}, 'post_update_attributes': {'topic': 'proof', 'region': 'us'}, 'citation': {'type': 'file_citation', 'index': 0, 'file_id': 'file_6222a462644b4e67808dc8dd', 'filename': 'w17-route-proof-e692352e-1.md'}, 'context_citation': {'type': 'file_citation', 'index': 0, 'file_id': 'file_6222a462644b4e67808dc8dd', 'filename': 'w17-route-proof-e692352e-1.md'}}
```

## Notes

This ticket does not change API-key creation or resolution semantics. It must
prove that OpenAI-compatible vector-store file and file-batch surfaces work
through the existing `Authorization: Bearer svs_live_...` API-key path.
