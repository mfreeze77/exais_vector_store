# WAVE-089 OpenAI Citation Stream Done Event Contract

## Objective

Lock the OpenAI Responses streaming citation contract so clients that render
file citations can rely on `response.output_text.done` arriving after
`response.output_text.annotation.added` and before `response.content_part.done`.

## Evidence Anchors

- OpenAI Responses API streaming examples include `response.output_text.done`
  before `response.content_part.done`.
  https://developers.openai.com/api/docs/api-reference/responses/create
- OpenAI file-search guide shows file-search Responses output with
  `file_citation` annotations under `output_text.annotations`, including
  repeated annotations at the same `index`.
  https://developers.openai.com/api/docs/guides/tools-file-search
- `packages/svs_common/svs_common/openai_compat.py`
- `tests/test_openai_compat_search.py`
- `tests/test_openai_responses_routes.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`

## Scope

- Add regression assertions that Responses SSE includes
  `response.output_text.done` for cited output text.
- Assert citation annotation-added events precede output-text done, and
  output-text done precedes content-part done.
- Assert `response.output_text.done` carries the final text only, while
  annotations remain on annotation-added, content-part-done, and completed
  events.
- Document the stream ordering as part of the OpenAI citation parity contract.

## Non-Goals

- Changing citation marker text, annotation schema, or native citation metadata.
- Changing retrieval, ranking, file-search result inclusion, storage,
  idempotency, API keys, tenant isolation, or rate limits.
- Adding model-generated prose.

## Acceptance

- [x] Citation streaming tests require `response.output_text.done`.
- [x] Tests prove annotation-added events arrive before output-text done.
- [x] Tests prove content-part-done still carries annotations after
  output-text done.
- [x] Route-level SSE proof covers the same event ordering.
- [x] Docs describe `response.output_text.done` in the citation streaming
  sequence.

## Proof

- Focused OpenAI citation/Responses route tests:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_openai_responses_routes.py`
  passed with `112 passed, 2 warnings in 3.45s`.
- Broad non-integration:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration`
  passed with `389 passed, 2 warnings in 5.02s`.
- Compile:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests`
  passed.
- Whitespace:
  `git diff --check` passed.
