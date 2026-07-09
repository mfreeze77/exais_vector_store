# WAVE-047 Responses Stream Resume Cursor

## Summary

Add OpenAI-style `starting_after` resume support for stored Responses streams so
clients can recover citation events after a stream interruption.

## Background

Official OpenAI references checked on 2026-07-08:

- The Responses retrieve reference documents `stream=true` for server-sent event
  streaming and a `starting_after` query parameter that resumes after an event
  sequence number.
- The same reference describes `include_obfuscation`; that remains out of scope
  for this ticket.

WAVE-046 added typed SSE events and citation annotation events. Those events
already carry monotonically increasing `sequence_number` values, but
`GET /v1/responses/{response_id}?stream=true` always starts at the beginning.
OpenAI-compatible citation consumers should be able to reconnect after the last
seen sequence number and still receive later `file_citation` annotation events.

## Scope

- Support `starting_after` on `GET /v1/responses/{response_id}` when
  `stream=true`.
- Filter SSE events to sequence numbers greater than `starting_after`.
- Preserve the existing OpenAI `file_citation` annotation shape and event
  payloads.
- Keep non-streaming retrieval behavior unchanged.
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

- Stream obfuscation fields or `include_obfuscation` behavior.
- Token-by-token model generation.
- WebSocket Responses mode.
- Non-`file_search` Responses tools.
- Changing JSON Responses output or citation object shape.

## Acceptance Criteria

- [x] Stored response streaming accepts `starting_after=N`.
- [x] SSE output omits events with `sequence_number <= N`.
- [x] Resumed streams still emit later
  `response.output_text.annotation.added` citation events.
- [x] Completed resumed streams still include final response citation
  annotations.
- [x] Non-streaming `GET /v1/responses/{response_id}` remains unchanged.
- [x] Focused and broad non-integration verification passes.

## Verification

Focused verification passed:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_openai_responses_routes.py
49 passed, 2 warnings
```

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
226 passed, 2 warnings

git diff --check
pass
```
