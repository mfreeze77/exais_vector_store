# WAVE-043 OpenAI Citation Annotation Mirror

## Summary

Make OpenAI-style citations easier to consume from native ExAIS proof without
changing the OpenAI-facing Responses shape. Native citation objects now carry an
`annotation` field that exactly mirrors the strict OpenAI `file_citation` object
returned under `output_text.annotations`.

## Background

Official OpenAI references checked on 2026-07-08:

- File search guide: Responses file search returns a `file_search_call` output
  item plus an assistant `message` with file citations.
- Responses API reference: `output_text.annotations` file citations use
  `type`, `index`, `file_id`, and `filename`.
- Assistants annotation guidance: file-search annotations map visible generated
  source markers such as `【13†source】` back to uploaded files.

Prior tickets already added OpenAI-style markers, strict
`output_text.annotations`, OpenAI-shaped included `file_search_call.results`,
and multi-store duplicate citation dedupe. This ticket preserves those contracts
and gives native audit consumers one exact OpenAI citation object to read.

## Scope

- Keep `output_text.annotations` limited to OpenAI-core `file_citation` fields.
- Keep included `file_search_call.results` entries limited to `file_id`,
  `filename`, `score`, `text`, and `attributes`.
- Add `citation.annotation` on native vector-store search citation proof.
- Add `citations[].annotation` on native Responses file-search proof.
- Preserve existing flattened native citation fields for backward compatibility.
- Update formatter, route tests, docs, and proof.

## Code Anchors

- `packages/svs_common/svs_common/openai_compat.py`
- `tests/test_openai_compat_search.py`
- `tests/test_openai_responses_routes.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`

## Out Of Scope

- Model prose generation.
- Streaming Responses output.
- Removing native top-level `citations`.
- Changing OpenAI `output_text.annotations` shape.
- Adding ExAIS-only fields to `file_search_call.results`.

## Acceptance Criteria

- [x] Native vector-store search citation objects include `annotation` matching
  the result-level OpenAI annotation.
- [x] Native Responses `citations[]` objects include `annotation` matching the
  corresponding `output_text.annotations[]` object.
- [x] OpenAI-facing annotation objects remain limited to `type`, `index`,
  `file_id`, and `filename`.
- [x] Included `file_search_call.results` remain strict OpenAI result objects.
- [x] Existing native citation fields such as marker, chunk, page, and
  vector-store proof remain available outside the OpenAI annotation object.
- [x] Focused and broad non-integration verification passes.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_openai_responses_routes.py
44 passed, 2 warnings

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
217 passed, 2 warnings

git diff --check
pass
```
