# WAVE-065 OpenAI File Search Citation Result Alias

## Goal

Tighten the OpenAI Responses file-search citation surface so clients following
either the current API-reference examples or the file-search guide examples can
read the result placeholder around citation-bearing output.

## References

Official OpenAI references checked on 2026-07-09:

- OpenAI file-search guide: file-search output includes a `file_search_call`
  item plus a message with `output_text.annotations`; the guide example shows
  `search_results: null` when result bodies are not included.
  https://developers.openai.com/api/docs/guides/tools-file-search
- OpenAI file-search guide include section: result bodies are opt-in through
  `include: ["file_search_call.results"]`.
  https://developers.openai.com/api/docs/guides/tools-file-search#include-search-results-in-the-response
- OpenAI Responses API reference: file-search examples use strict
  `file_citation` annotations with `type`, `index`, `file_id`, and `filename`.
  https://api.openai.com/v1/responses

## Scope

- Keep OpenAI-facing `file_citation` annotations strict and unchanged.
- Return `search_results: null` beside `results: null` on default
  `file_search_call` items.
- Keep included `results` and `search_results` arrays identical when
  `include` requests file-search results.
- Add focused regression proof for default and stripped response alias behavior.
- Update docs and ticket trail.

## Non-Goals

- Changing citation marker text or annotation indexes.
- Adding model-generated prose or Assistants API route support.
- Changing vector-store search ranking, tenant isolation, API-key lifecycle,
  database migrations, indexing, provider routing, deployment, or admin UI
  behavior.

## Acceptance Criteria

- [x] Default Responses file-search output exposes both `results: null` and
  `search_results: null`.
- [x] `response_with_file_search_include(..., include_search_results=False)`
  preserves the same null alias pair.
- [x] Included file-search result bodies still populate both `results` and
  `search_results` with identical OpenAI-shaped result rows.
- [x] Strict OpenAI `file_citation` annotation fields and marker indexes remain
  unchanged.
- [x] Focused and broad verification passes.

## Verification

- Focused Responses/OpenAI compatibility tests.
- `python -m compileall -f -q packages apps tests`.
- Full non-integration suite.
- `git diff --check`.

## Proof

Focused Responses/OpenAI compatibility verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_responses_routes.py tests/test_openai_compat_search.py
96 passed, 2 warnings
```

Compile proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass
```

Full non-integration proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
297 passed, 2 warnings
```

Whitespace proof:

```text
git diff --check
pass
```

Notes:

- The two warnings are existing FastAPI `on_event` deprecation warnings.
