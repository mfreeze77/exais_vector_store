# WAVE-016 OpenAI Files Upload Parity

## Summary

Remove the WAVE-015 workaround that required callers to attach raw ExAIS
document IDs. OpenAI SDK-style clients should be able to upload a file through
`/v1/files`, attach the returned file ID to a vector store, search it, receive
file-ID citations, and delete the file from associated vector stores.

Official OpenAI references checked on 2026-07-08:

- `/files`
- `/files/{file_id}`
- `/files/{file_id}/content`

## Tickets

| Ticket | Status | Type | Outcome |
|---|---|---|---|
| W16-001 | Complete | Implementation/Test | Add OpenAI-compatible files upload/list/retrieve/content/delete and wire uploaded file IDs into vector-store attachment, search metadata, and citations. |

## W16-001 Acceptance Criteria

- [x] `POST /v1/files` accepts OpenAI-style multipart `file` plus `purpose` and
  returns an OpenAI file object with `id`, `object`, `bytes`, `created_at`,
  `filename`, and `purpose`.
- [x] `GET /v1/files` supports `purpose`, `limit`, `order`, and `after`.
- [x] `GET /v1/files/{file_id}` and `GET /v1/files/{file_id}/content` work for
  uploaded file IDs.
- [x] `POST /v1/vector_stores/{vector_store_id}/files` and file batches accept
  uploaded `file_*` IDs as `file_id`.
- [x] Vector-store file responses preserve ExAIS `vector_store_file_id` while
  returning the OpenAI file ID as `id`.
- [x] Search results and file citations use the uploaded OpenAI file ID when a
  file was attached from `/v1/files`.
- [x] `DELETE /v1/files/{file_id}` cancels associated vector-store file rows,
  deactivates original and attached-copy chunks, and queues stale-vector cleanup.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests scripts
<exit 0>

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_files.py tests/test_openai_vector_store_object.py tests/test_openai_compat_search.py
22 passed, 2 warnings in 3.20s

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
110 passed, 2 warnings in 3.70s

git diff --check
<exit 0>
```

Live mounted-code proof against `exais-vector-store-local_default`:

```text
{'file_id': 'file_700f993be91849c8884a9090', 'vector_store_id': 'vs_5fca32f549bc455d93eaf191', 'vector_store_file_id': 'vsf_0a3ebeebe8b8429c857cb89e', 'citation': {'type': 'file_citation', 'index': 0, 'file_id': 'file_700f993be91849c8884a9090', 'filename': 'openai-files-live-proof-86b82f79.md'}, 'context_citation': {'type': 'file_citation', 'index': 0, 'file_id': 'file_700f993be91849c8884a9090', 'filename': 'openai-files-live-proof-86b82f79.md'}, 'attributes': {'region': 'us'}, 'deleted': {'id': 'file_700f993be91849c8884a9090', 'object': 'file', 'deleted': True}}
```

## Notes

`/v1/files` is backed by existing ExAIS documents and document-version metadata,
not a new table. That keeps RLS, audit, ingestion, chunking, and index cleanup
on the existing source-of-truth path.

UTF-8, UTF-16, and ASCII text uploads are supported directly. PDF uploads use
the configured Marker conversion path when available. Other binary uploads fail
with `415` until a parser is configured instead of producing unreadable chunks.
