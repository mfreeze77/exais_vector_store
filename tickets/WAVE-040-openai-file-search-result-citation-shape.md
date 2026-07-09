# WAVE-040 OpenAI File Search Result Citation Shape

## Summary

Tighten the Responses `file_search` citation surface so included
`file_search_call.results` entries are OpenAI-shaped result objects, while rich
ExAIS citation proof remains outside the OpenAI result object.

## Background

Official OpenAI reference checked on 2026-07-08:

- The file-search guide says a response contains a `file_search_call` output
  item plus an assistant `message` with file citations.
- The Responses API reference defines `output_text.annotations` file citations
  with `type`, `index`, `file_id`, and `filename`.
- The same reference defines `file_search_call.results` entries with
  `file_id`, `filename`, `score`, `text`, and `attributes`.

ExAIS already emits OpenAI-core citation annotations and visible source
markers. The remaining shape mismatch is that included file-search results
currently carry ExAIS-only fields such as `citation`, `vector_store_id`, and
`output_guard`. Strict OpenAI-compatible clients should be able to consume the
included result array without seeing native proof fields in that object.

## Scope

- Keep `output_text.annotations` limited to OpenAI-core `file_citation` fields.
- Keep top-level/native `citations` for chunk, document, page, marker,
  vector-store, and output-guard proof.
- Keep top-level `output_guard` metadata when redaction occurs.
- Change included `file_search_call.results` and `search_results` entries to
  the OpenAI result shape: `file_id`, `filename`, `score`, `text`, and
  `attributes`.
- Preserve guarded/redacted text in included result `text`.
- Update route and formatter regression tests.
- Update docs and proof.

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
- New citation marker formats.
- Removing native top-level `citations`.
- Changing vector-store search result objects outside Responses
  `file_search_call.results`.

## Acceptance Criteria

- [x] Included `file_search_call.results` entries contain only `file_id`,
  `filename`, `score`, `text`, and `attributes`.
- [x] Included `search_results` alias entries match the same OpenAI-shaped
  result objects.
- [x] Redacted result text remains redacted without exposing `output_guard`
  inside individual result objects.
- [x] Rich native citation/output-guard proof remains available outside
  `file_search_call.results`.
- [x] Route-level citation annotations remain OpenAI-core-shaped and indexed at
  the visible citation marker.
- [x] Focused and broad non-integration verification passes.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_openai_responses_routes.py
41 passed, 2 warnings

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
211 passed, 2 warnings

git diff --check
pass
```
