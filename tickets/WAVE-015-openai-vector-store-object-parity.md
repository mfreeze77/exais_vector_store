# WAVE-015 OpenAI Vector Store Object Parity

## Summary

Close the next OpenAI compatibility gap after WAVE-014 search parity: the vector
store object and surrounding create/update/list/file-attach routes should be
usable by OpenAI-shaped SDK clients without silent request drift.

## Tickets

| Ticket | Status | Type | Outcome |
|---|---|---|---|
| W15-001 | Complete | Implementation/Test | Make vector-store create/update/list/object responses align with current OpenAI vector-store object semantics while preserving ExAIS native fields. |
| W15-002 | Complete | Implementation/Test | Add OpenAI-shaped file citation annotations to vector-store search and native context-pack citation output. |

## W15-001 Acceptance Criteria

- [x] `POST /v1/vector_stores` accepts an empty OpenAI-style body and current
  OpenAI fields: `name`, `description`, `file_ids`, `metadata`,
  `expires_after`, and `chunking_strategy`.
- [x] Unknown vector-store create/update fields are rejected instead of
  silently ignored.
- [x] `POST /v1/vector_stores/{vector_store_id}` is supported as the OpenAI
  update method while the existing `PATCH` alias remains available.
- [x] Vector-store list accepts OpenAI pagination order controls: `order`,
  `after`, and `before`.
- [x] Vector-store responses include OpenAI object fields `bytes`,
  `file_counts`, `metadata`, and `description`, while preserving existing
  `usage_bytes` and `attributes` for ExAIS clients.
- [x] `POST /v1/vector_stores/{vector_store_id}/files` accepts OpenAI-shaped
  `file_id` attachment for existing ExAIS documents.

## W15-001 Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_vector_store_object.py tests/test_openai_compat_search.py
..................                                                       [100%]
18 passed in 0.74s
```

## W15-002 Acceptance Criteria

- [x] `POST /v1/vector_stores/{vector_store_id}/search` emits OpenAI-shaped
  file citation annotations with `type: file_citation`, `index`, `file_id`, and
  `filename`.
- [x] Search results expose citation handles even when `include_content=false`.
- [x] Search responses keep ExAIS retrieval proof fields beside the OpenAI core:
  `chunk_id`, `document_id`, page range, heading path, score, title, and public
  URL when available.
- [x] Native `/api/v1/retrieval/context-pack` citations carry the same
  OpenAI-shaped annotation object beside existing ExAIS chunk/page metadata.

## W15-002 Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_openai_vector_store_object.py
..................                                                       [100%]
18 passed in 0.74s
```

Live mounted-code proof against `exais-vector-store-local_default`:

```text
{'document_id': 'doc_86450d5fde9747d9acb018b9', 'vector_store_file_id': 'vsf_dab8e6f9e3914c15bc8945f3', 'filename': 'openai-citation-live-proof-220a9afd.md', 'annotation': {'type': 'file_citation', 'index': 0, 'file_id': 'vsf_dab8e6f9e3914c15bc8945f3', 'filename': 'openai-citation-live-proof-220a9afd.md'}}
```

Final regression proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests scripts
<exit 0>

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
106 passed, 2 warnings in 3.81s

git diff --check
<exit 0>
```

## Notes

OpenAI `file_id` attachment maps to existing ExAIS document IDs until a full
OpenAI-compatible `/v1/files` object model is added. This is intentionally
documented as compatibility behavior, not a claim that ExAIS clones OpenAI's
hosted file storage internals.

OpenAI-style citations are modeled on the Responses API annotation shape. ExAIS
sets `index` to `0` for retrieved chunks because vector-store search returns
chunk text directly rather than generated answer text with character offsets.
