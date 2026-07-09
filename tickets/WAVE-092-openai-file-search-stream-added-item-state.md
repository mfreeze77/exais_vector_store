# WAVE-092 OpenAI File Search Stream Added Item State

## Objective

Keep Responses file-search citation streams closer to OpenAI's lifecycle shape by
making the initial `response.output_item.added` payload represent an in-progress
file-search call instead of pre-emitting final query/result state.

## Evidence Anchors

- OpenAI file-search guide documents the final `file_search_call` and cited
  message output shape.
  https://developers.openai.com/api/docs/guides/tools-file-search
- OpenAI Responses reference documents `file_search_call.results` as the include
  path for search results.
  https://developers.openai.com/api/reference/resources/responses/methods/create
- `packages/svs_common/svs_common/openai_compat.py`
- `tests/test_openai_compat_search.py`
- `tests/test_openai_responses_routes.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`

## Scope

- Sanitize streamed `response.output_item.added` items for `file_search_call` to
  `status: in_progress`, empty `queries`, and null `results`/`search_results`.
- Keep final `response.output_item.done`, `response.completed`, stored response,
  and non-streaming response payloads unchanged.
- Preserve citation annotation ordering and final strict `file_citation` payloads.
- Document the stream lifecycle behavior.

## Non-Goals

- Changing retrieval ranking, query planning, vector-store search response
  fields, API-key behavior, OpenAPI component schemas, or database migrations.
- Removing the `search_results` compatibility alias.
- Changing the existing deterministic retrieval summary text.

## Acceptance

- [x] `response.output_item.added` for `file_search_call` no longer exposes final
  planned queries or included results.
- [x] `response.output_item.done` still carries the final file-search call,
  including planned queries and included results when requested.
- [x] Citation annotation stream order remains unchanged:
  `response.output_text.annotation.added` precedes `response.output_text.done`,
  which precedes `response.content_part.done`.
- [x] Route-level SSE tests cover the same behavior.
- [x] Docs and tracker call out the lifecycle contract.

## Proof

- Focused OpenAI/Responses stream proof:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_openai_responses_routes.py`
  passed with `113 passed, 2 warnings in 3.82s`.
- Compile:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests`
  passed.
- Broad non-integration:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration`
  passed with `390 passed, 2 warnings in 5.13s`.
- Whitespace:
  `git diff --check` passed.

## QC

Decision: PASS

Ticket reviewed:
- `tickets/WAVE-092-openai-file-search-stream-added-item-state.md`

Evidence reviewed:
- `packages/svs_common/svs_common/openai_compat.py`
- `tests/test_openai_compat_search.py`
- `tests/test_openai_responses_routes.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`
- `tickets/README.md`
- Focused OpenAI/Responses stream proof: `113 passed, 2 warnings in 3.82s`
- Compile proof: passed
- Broad non-integration proof: `390 passed, 2 warnings in 5.13s`
- Whitespace proof: `git diff --check` passed

Acceptance criteria:
- [pass] `response.output_item.added` for `file_search_call` emits an
  in-progress item with empty `queries` and null result fields.
- [pass] Final `response.output_item.done` and completed snapshots retain
  planned queries and included results.
- [pass] Citation annotation ordering remains locked by focused tests.
- [pass] Route-level SSE tests cover the lifecycle behavior.
- [pass] Docs and tracker note the stream contract.

Findings:
- None.

Required fixes before next ticket:
- None.
