# WAVE-036 OpenAI File Search Call Default Parity

## Summary

Tighten the OpenAI-compatible Responses `file_search_call` output so default
responses more closely match OpenAI's current file-search shape. OpenAI returns
file citations in assistant `output_text.annotations`, and the `file_search_call`
item carries `queries` plus `results: null` unless `include` asks for
`file_search_call.results`.

## Background

Official OpenAI references checked on 2026-07-08:

- Responses create OpenAPI example: file-search output includes a
  `file_search_call` with `queries` and `results: null`, followed by a message
  with `output_text.annotations` containing `file_citation` objects.
- File search guide: search results are not returned by default; clients use
  `include: ["file_search_call.results"]` to include them.

Existing ExAIS citation behavior already emits OpenAI-core `file_citation`
annotations and visible `【n†source】` markers. The remaining default-shape gap is
that `response_with_file_search_include(..., include_search_results=False)`
removes the `results` field entirely instead of returning `results: null`.

## Scope

- Return `results: null` on default OpenAI-compatible `file_search_call` output.
- Preserve `search_results` as an ExAIS/cookbook compatibility alias only when
  search results are explicitly included.
- Preserve stored full responses with full results so retrieval with `include`
  can still expose result bodies.
- Keep OpenAI-core annotation objects limited to `type`, `index`, `file_id`, and
  `filename`.
- Update docs and proof.

## Code Anchors

- `packages/svs_common/svs_common/openai_compat.py`
- `tests/test_openai_compat_search.py`
- `tests/test_openai_responses_routes.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`

## Out Of Scope

- Model prose generation.
- Streaming Responses output.
- New retrieval providers.
- Changes to citation marker numbering or annotation index calculation.
- API key, vector-store lifecycle, ingestion, or retrieval ranking changes.

## Acceptance Criteria

- [x] Default returned `file_search_call` output includes `queries` and
  `results: null`.
- [x] Default returned `file_search_call` output does not expose
  `search_results`.
- [x] Stored full responses still retain full `results` and `search_results` so
  later retrieval with `include` can expose them.
- [x] `include=["file_search_call.results"]` still returns result bodies and the
  compatibility `search_results` alias.
- [x] File citation annotations remain OpenAI-core shaped and marker indexes
  still point at visible `【n†source】` markers.
- [x] Focused and broad non-integration verification passes.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_openai_responses_routes.py
30 passed, 2 warnings in 3.04s

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
191 passed, 2 warnings in 4.00s

git diff --check
pass
```

## Notes

This ticket is about the OpenAI Responses output envelope. It does not change
the retrieval engine or the richer ExAIS citation proof fields.
