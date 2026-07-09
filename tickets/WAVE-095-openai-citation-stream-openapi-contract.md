# WAVE-095 OpenAI Citation Stream OpenAPI Contract

## Objective

Lock OpenAI-style Responses citation streaming in generated `/openapi.json` so
clients see the same strict `file_citation` annotation contract on
`response.output_text.annotation.added` events that they already see on
completed `output_text.annotations`.

## Evidence Anchors

Official OpenAI references checked on 2026-07-09:

- Responses OpenAPI reference: file-search Responses emit a
  `file_search_call` item plus an assistant message whose `output_text`
  content carries `file_citation` annotations with `type`, `index`, `file_id`,
  and `filename`.
  https://api.openai.com/v1/responses
- Responses streaming examples in the same reference advertise typed
  `response.output_text.*`, `response.content_part.*`, and
  `response.completed` events for streamed response output.
  https://api.openai.com/v1/responses
- Assistants annotation guidance: file-search annotations identify uploaded
  files and visible marker substrings that clients replace or render.
  https://developers.openai.com/api/docs/assistants/deep-dive#message-annotations

## Scope

- Add named Pydantic models for the Responses SSE event types emitted by ExAIS.
- Ensure `response.output_text.annotation.added.annotation` references the
  existing strict `OpenAIFileCitationAnnotation` model.
- Add an OpenAPI generation hook that preserves the JSON `OpenAIResponseObject`
  response schema while typing `text/event-stream` for
  `POST /v1/responses` and `GET /v1/responses/{response_id}?stream=true`.
- Add focused OpenAPI regression coverage for citation-bearing stream events.
- Update docs, ticket trail, and proof.

## Non-Goals

- Changing runtime SSE ordering, event names, citation marker text, annotation
  fields, same-index citation support, replay `sequence_number` behavior,
  retrieval ranking, vector-store APIs, API-key behavior, provider routing,
  deployment, or admin UI.
- Adding ExAIS-native chunk/page/guard metadata to OpenAI-facing
  `output_text.annotations` or stream annotation objects.

## Acceptance

- [x] Generated `/openapi.json` advertises `OpenAIResponseStreamEvent` for both
  Responses streaming surfaces.
- [x] The normal JSON response schema for both routes remains
  `OpenAIResponseObject`.
- [x] `OpenAIResponseOutputTextAnnotationAddedEvent.annotation` reuses
  `OpenAIFileCitationAnnotation`.
- [x] Citation-bearing stream events include typed content-part-done and
  completed-response payloads.
- [x] Runtime citation/stream tests still pass.
- [x] Compile, broad non-integration, whitespace, and QC verification pass.

## Proof

Focused Responses/OpenAI citation stream contract verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_openai_responses_routes.py tests/test_openapi_contract.py
125 passed, 2 warnings in 4.41s
```

Compile proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass
```

Broad non-integration proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
401 passed, 2 warnings in 5.74s
```

Whitespace proof:

```text
git diff --check
pass
```

Notes:

- The two warnings are existing FastAPI `on_event` deprecation warnings.

## QC

Decision: PASS

Review notes:

- Scope stayed within citation stream OpenAPI schema, focused tests, and docs.
- Runtime SSE generation was not changed; existing citation/stream tests still
  pass.
- JSON Responses OpenAPI schema remains `OpenAIResponseObject` for both typed
  streaming routes.
