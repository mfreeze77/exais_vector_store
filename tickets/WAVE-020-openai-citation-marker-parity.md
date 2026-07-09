# WAVE-020 OpenAI Citation Marker Parity

## Summary

Tighten the Responses `file_search` citation surface so ExAIS output text uses
OpenAI-style inline citation markers and annotation indexes point at the visible
marker substring clients render or replace.

Official OpenAI references checked on 2026-07-08:

- Responses create reference: supported `include` value
  `file_search_call.results`
- File search guide: `file_search_call` output plus assistant `message` with
  `output_text.annotations`
- Assistants message annotation guidance: `file_citation` references uploaded
  files used by file search and visible generated source markers

## Tickets

| Ticket | Status | Type | Outcome |
|---|---|---|---|
| W20-001 | Complete | Implementation/Test | Emit OpenAI-style visible file-citation markers and accept current/cookbook file-search results include paths. |

## W20-001 Acceptance Criteria

- [x] Responses `file_search` output text contains visible OpenAI-style citation
  markers such as `【1†source】` instead of local `[1]` prefixes.
- [x] Each `file_citation.index` points to the start of that visible marker in
  the returned `output_text.text`.
- [x] Annotation objects remain OpenAI-core-shaped with only `type`, `index`,
  `file_id`, and `filename`.
- [x] Rich ExAIS citation proof remains available outside the OpenAI annotation
  object and includes the marker plus chunk/vector-store metadata.
- [x] `include` accepts both `file_search_call.results` and the cookbook-style
  `output[*].file_search_call.search_results` path.
- [x] Focused tests and live/API proof cover marker text, annotation index, and
  include alias behavior.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py
21 passed in 0.44s

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests scripts
<exit 0>

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_files.py tests/test_openai_vector_store_object.py tests/test_openai_compat_search.py
30 passed, 2 warnings in 3.45s

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
118 passed, 2 warnings in 3.84s

git diff --check
<exit 0>
```

Live API proof against `exais-vector-store-local_default` used a temporary
dev-header-created Bearer key, then exercised `/v1/files`, `/v1/vector_stores`,
`/v1/responses`, stored response retrieval, and file cleanup without printing
the key:

```text
{'api_key_prefix': 'svs_live_', 'vector_store_id': 'vs_449c938c6cd047bfabbbe561', 'file_id': 'file_91ff2e9454574a5eacf05550', 'response_id': 'resp_d704c00fa3724935b3679a1f', 'marker': '【1†source】', 'annotation': {'type': 'file_citation', 'index': 183, 'file_id': 'file_91ff2e9454574a5eacf05550', 'filename': 'w20-citations-proof-88d724f6.md'}, 'include_alias_results': True, 'include_alias_search_results': True, 'retrieved_marker_ok': True, 'file_cleanup': {'id': 'file_91ff2e9454574a5eacf05550', 'object': 'file', 'deleted': True}}
```

## Notes

This ticket does not add model prose generation, streaming Responses output,
new retrieval providers, or new database schema.
