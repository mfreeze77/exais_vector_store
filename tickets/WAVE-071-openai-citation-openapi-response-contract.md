# WAVE-071 OpenAI Citation OpenAPI Response Contract

## Summary

Expose the strict OpenAI Responses file-search citation shape in generated
`/openapi.json` response components so SDK/client generation sees the same
`output_text.annotations` contract that runtime already enforces.

## Background

Official OpenAI references checked on 2026-07-09:

- File search guide: Responses file search exposes annotations in output text,
  while raw file-search result rows are opt-in through `include`.
  https://developers.openai.com/api/docs/guides/tools-file-search#include-search-results-in-the-response
- Assistants annotation guidance: file-search annotations identify files used
  by retrieval and appear as replaceable inline source substrings.
  https://developers.openai.com/api/docs/assistants/deep-dive#message-annotations
- Responses OpenAPI reference for `POST /v1/responses`: JSON Responses use a
  `Response` component, SSE uses `ResponseStreamEvent`, and file-search
  examples use strict `file_citation` annotations with `type`, `index`,
  `file_id`, and `filename`.
  https://api.openai.com/v1/responses

Prior citation waves locked runtime behavior: visible `【n†source】` markers,
strict annotation fields, streaming annotation events, stored replay guards, and
native citation mirrors. WAVE-070 then added named request components but left
Responses JSON response bodies too free-form for OpenAPI clients to discover the
citation contract.

## Scope

- Add typed Pydantic components for:
  - strict `OpenAIFileCitationAnnotation`
  - Responses `output_text` content with citation annotations
  - Responses message and file-search-call output items
  - Responses JSON response, input-token, compact, delete, and input-items page
    responses
- Wire Responses JSON routes to these response models while preserving payload
  shape with `response_model_exclude_unset=True`.
- Keep existing runtime citation guards and helper validation as the source of
  behavior.
- Add OpenAPI contract tests proving `output_text.annotations` references the
  strict file-citation component.
- Update docs, completion matrix, ticket trail, and proof.

## Code Anchors

- `packages/svs_common/svs_common/schemas.py`
- `apps/api/svs_api/main.py`
- `tests/test_openapi_contract.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/COMPLETION_MATRIX.md`
- `docs/TICKET_TRAIL.md`

## Out Of Scope

- Changing citation marker text or annotation indexes.
- Changing retrieval, ranking, tenant isolation, API keys, database schema,
  indexing semantics, provider routing, deployment, or admin UI behavior.
- Adding unsupported OpenAI tools or provider-generated prose.
- Removing native top-level `citations` or native proof metadata.

## Acceptance Criteria

- [x] `/openapi.json` includes a strict `OpenAIFileCitationAnnotation`
  component with required `type`, `index`, `file_id`, and `filename` fields.
- [x] `OpenAIResponseOutputTextContent.annotations` references
  `OpenAIFileCitationAnnotation`.
- [x] Responses JSON routes reference named response components instead of
  anonymous object responses.
- [x] `POST /v1/responses` and `GET /v1/responses/{response_id}` continue to
  advertise both `application/json` and `text/event-stream` 200 response media
  types.
- [x] Existing Responses citation behavior and compatibility helper tests still
  pass.
- [x] Compile, broad non-integration, and whitespace verification passes.

## Verification

Focused OpenAPI/Responses citation contract verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openapi_contract.py tests/test_openai_responses_routes.py tests/test_openai_compat_search.py
112 passed, 2 warnings
```

Compile verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass
```

Broad non-integration verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
318 passed, 2 warnings
```

Whitespace verification:

```text
git diff --check
pass
```
