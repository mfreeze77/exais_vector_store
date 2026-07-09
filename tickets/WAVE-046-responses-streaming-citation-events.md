# WAVE-046 Responses Streaming Citation Events

## Summary

Support `stream=true` for OpenAI-compatible `/v1/responses` file-search
requests and stored response retrieval. ExAIS now returns typed SSE events that
preserve the same strict OpenAI `file_citation` annotations already emitted in
JSON responses.

## Background

Official OpenAI references checked on 2026-07-08:

- Streaming Responses guide: `stream=true` uses server-sent events with typed
  semantic events.
- Migration guide: text streaming consumers should branch on event `type`, with
  common events such as `response.created`, `response.output_text.delta`, and
  `response.completed`.
- Streaming event reference search results list file-search lifecycle events
  such as `response.file_search_call.in_progress`,
  `response.file_search_call.searching`, and
  `response.file_search_call.completed`, plus
  `response.output_text.annotation.added`.

Before this ticket, ExAIS returned correct citation annotations in JSON
Responses payloads but rejected `stream=true`. That left OpenAI-style streaming
clients unable to consume file-search citations through the SSE path.

## Scope

- Add a reusable Responses SSE event formatter.
- Emit OpenAI-style lifecycle events for completed deterministic retrieval
  responses.
- Emit file-search lifecycle events for `file_search_call` output items.
- Emit `response.output_text.annotation.added` for citation annotations.
- Preserve annotations on `response.content_part.done` and
  `response.completed`.
- Support streaming on both `POST /v1/responses` and
  `GET /v1/responses/{response_id}`.
- Update route tests, formatter tests, docs, trail, and proof.

## Code Anchors

- `packages/svs_common/svs_common/openai_compat.py`
- `apps/api/svs_api/main.py`
- `tests/test_openai_compat_search.py`
- `tests/test_openai_responses_routes.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`

## Out Of Scope

- Token-by-token model generation.
- Streaming before retrieval completes.
- WebSocket Responses mode.
- Stream obfuscation options.
- Non-`file_search` Responses tools.
- Changing the existing JSON response or citation shape.

## Acceptance Criteria

- [x] `POST /v1/responses` with `stream=true` no longer returns 422 for
  supported file-search requests.
- [x] Non-boolean JSON `stream` values return 422 instead of silently falling
  back to non-streaming output.
- [x] Stream output uses `text/event-stream` SSE framing.
- [x] Stream output includes typed lifecycle and file-search events.
- [x] Citation annotations appear in `response.output_text.annotation.added`,
  `response.content_part.done`, and `response.completed` events.
- [x] `GET /v1/responses/{response_id}?stream=true` streams stored response
  payloads with citation annotations.
- [x] Focused and broad non-integration verification passes.

## Verification

Focused verification passed:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_openai_responses_routes.py
48 passed, 2 warnings
```

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
225 passed, 2 warnings

git diff --check
pass
```
