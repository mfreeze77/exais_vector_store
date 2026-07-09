# WAVE-070 OpenAI Responses OpenAPI Contract

## Summary

Improve the generated FastAPI OpenAPI contract for OpenAI-compatible Responses
routes by replacing anonymous request `dict` bodies with documented request
models for the supported file-search subset.

## Background

Official OpenAI references checked on 2026-07-09:

- Responses create reference:
  https://developers.openai.com/api/reference/resources/responses/methods/create
- OpenAPI spec for `POST https://api.openai.com/v1/responses` reports a
  concrete `CreateResponse` request body and JSON/SSE response media types.

ExAIS already implements the supported file-search subset of Responses create,
input-token preflight, and compact handoff behavior. The remaining contract gap
is generated schema quality: `/openapi.json` exposes generic object bodies for
these routes, which weakens SDK/client generation and obscures the supported
OpenAI-compatible fields.

## Scope

- Add typed Pydantic request models for:
  - `POST /v1/responses`
  - `POST /v1/responses/input_tokens`
  - `POST /v1/responses/compact`
- Preserve existing route behavior by converting request models back to dicts
  before running the existing OpenAI compatibility helpers.
- Keep models permissive enough to avoid moving validation away from current
  fail-closed helper logic.
- Add OpenAPI contract tests proving the generated schema exposes the expected
  request components and fields.
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

- Implementing unsupported OpenAI tools.
- Changing Responses runtime behavior, citation behavior, retrieval ranking,
  API-key behavior, rate-limit values, database schema, RLS policies, indexing,
  provider routing, deployment, or admin UI behavior.
- Exporting a standalone static `openapi.yaml`.

## Acceptance Criteria

- [x] `/openapi.json` for `POST /v1/responses` references a named request
  component with OpenAI-compatible fields such as `model`, `input`, `tools`,
  `tool_choice`, `include`, `previous_response_id`, `conversation`,
  `instructions`, `store`, `stream`, `stream_options`, and `background`.
- [x] `/openapi.json` for Responses input-token and compact routes references
  named request components instead of anonymous free-form objects.
- [x] Direct route behavior for dict callers and existing compatibility helper
  validation remains unchanged.
- [x] Focused and broad non-integration verification passes.

## Verification

Focused OpenAPI/Responses contract verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openapi_contract.py tests/test_openai_responses_routes.py tests/test_openai_compat_search.py
109 passed, 2 warnings
```

Compile verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass
```

Broad non-integration verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
315 passed, 2 warnings
```

Whitespace verification:

```text
git diff --check
pass
```
