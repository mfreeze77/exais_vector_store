# WAVE-048 Responses Stream Obfuscation Parity

## Summary

Add OpenAI-style stream obfuscation support for Responses SSE output so delta
events include an `obfuscation` field by default and clients can opt out.

## Background

Official OpenAI references checked on 2026-07-08:

- The Responses retrieve reference documents `include_obfuscation`, enabled by
  default, which adds random characters to streaming delta events.
- The Responses create reference documents `stream=true` and `stream_options`
  for streaming response options.

WAVE-046 added typed SSE events and WAVE-047 added stored stream resume cursors.
The remaining stream-parity gap on this path is obfuscation. This matters for
OpenAI-compatible SDKs and clients that expect delta events to carry the field
unless explicitly disabled.

## Scope

- Add obfuscation strings to Responses streaming delta events by default.
- Support `stream_options.include_obfuscation=false` on
  `POST /v1/responses` streaming requests.
- Support `include_obfuscation=false` on
  `GET /v1/responses/{response_id}?stream=true`.
- Preserve citation annotation event payloads and final completed response
  citation annotations.
- Keep non-streaming JSON response behavior unchanged.
- Update formatter tests, route tests, docs, trail, and proof.

## Code Anchors

- `packages/svs_common/svs_common/openai_compat.py`
- `apps/api/svs_api/main.py`
- `tests/test_openai_compat_search.py`
- `tests/test_openai_responses_routes.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`

## Out Of Scope

- Exact OpenAI side-channel padding strategy or payload-size normalization.
- Token-by-token model generation.
- WebSocket Responses mode.
- Non-`file_search` Responses tools.
- Changing JSON Responses output or citation object shape.

## Acceptance Criteria

- [x] Streaming delta events include a non-empty `obfuscation` string by
  default.
- [x] Create streaming requests with
  `stream_options: {"include_obfuscation": false}` omit obfuscation.
- [x] Stored response streaming with `include_obfuscation=false` omits
  obfuscation.
- [x] Citation annotation events remain unchanged and do not receive
  obfuscation fields.
- [x] Invalid obfuscation option shapes fail with 422.
- [x] Focused and broad non-integration verification passes.

## Verification

Focused verification passed:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_openai_responses_routes.py
52 passed, 2 warnings
```

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
229 passed, 2 warnings

git diff --check
pass
```
