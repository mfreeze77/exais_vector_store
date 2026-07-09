# WAVE-018 OpenAI Responses File Search Citation Parity

## Summary

Add the OpenAI Responses API citation path for ExAIS vector stores. OpenAI-style
file citations must be available where current OpenAI clients expect them:
`output[].content[].annotations` on an `output_text` message returned by
`POST /v1/responses` with a `file_search` tool.

Official OpenAI references checked on 2026-07-08:

- `/responses`
- Responses API `file_search` tool examples
- Assistants message annotation guidance for `file_citation`

## Tickets

| Ticket | Status | Type | Outcome |
|---|---|---|---|
| W18-001 | Complete | Implementation/Test | Add a minimal non-streaming `/v1/responses` file-search facade that returns OpenAI-shaped `output_text.annotations` citations. |

## W18-001 Acceptance Criteria

- [x] `POST /v1/responses` accepts non-streaming requests with a `file_search`
  tool containing `vector_store_ids`.
- [x] The route extracts query text from common Responses `input` shapes,
  searches the requested vector stores using the existing retrieval/search
  stack, and preserves RLS/scope behavior through `retrieval:read`.
- [x] The response uses the OpenAI Responses object shape with a completed
  assistant message and an `output_text` content part.
- [x] File citations are present on `output_text.annotations` using the OpenAI
  core fields `type: file_citation`, `index`, `file_id`, and `filename`.
- [x] Citation `index` values point into the returned output text, and richer
  ExAIS citation proof remains available outside the OpenAI core annotation.
- [x] Unsupported tools and streaming requests return 422 instead of pretending
  to support them.
- [x] Focused tests and live proof cover OpenAI-style uploaded `file_*` IDs in
  Responses API citations.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py
18 passed in 0.41s

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests scripts
<exit 0>

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_files.py tests/test_openai_vector_store_object.py tests/test_openai_compat_search.py
27 passed, 2 warnings in 3.19s

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
115 passed, 2 warnings in 4.09s

git diff --check
<exit 0>
```

Live mounted-code proof against `exais-vector-store-local_default`:

```text
{'api_key_prefix': 'svs_live_', 'vector_store_id': 'vs_ff0b031787544b6d9e1b6522', 'file_id': 'file_532f10d01afc4deeb125c12c', 'attached_id': 'file_532f10d01afc4deeb125c12c', 'response_object': 'response', 'output_types': ['file_search_call', 'message'], 'annotation': {'type': 'file_citation', 'index': 32, 'file_id': 'file_532f10d01afc4deeb125c12c', 'filename': 'w18-responses-proof-326e79682d.md'}, 'citation_index_text': '[1]', 'search_results_included': True, 'deleted': {'id': 'file_532f10d01afc4deeb125c12c', 'object': 'file', 'deleted': True}}

{'stream_status': 422, 'unsupported_tool_status': 422}
```

## Notes

This ticket does not add model generation. The Responses facade deterministically
returns a source-backed retrieval summary from vector-store search results so
OpenAI-compatible clients can consume citations through the Responses API shape.
