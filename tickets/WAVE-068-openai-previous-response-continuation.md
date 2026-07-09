# WAVE-068 OpenAI Previous Response Continuation

## Summary

Add OpenAI-compatible `previous_response_id` continuation for stored Responses
file-search requests so follow-up turns can use prior response context instead
of treating every request as stateless.

## Background

Official OpenAI references checked on 2026-07-09:

- Conversation-state guide: `previous_response_id` chains responses and creates
  threaded conversations.
  https://developers.openai.com/api/docs/guides/conversation-state#passing-context-from-the-previous-response
- Migration guide: `previous_response_id` is one of the common Responses state
  strategies; callers must resend stable `instructions` because prior
  top-level instructions are not carried over.
  https://developers.openai.com/api/docs/guides/migrate-to-responses#3-update-multi-turn-conversations
- Responses create reference: `previous_response_id` is the ID of the previous
  response and cannot be used with `conversation`.
  https://developers.openai.com/api/reference/resources/responses/methods/create

Before this ticket, ExAIS echoed `previous_response_id` into the response object
but did not resolve the prior response or use it as retrieval context. That made
follow-up file-search turns behave like unrelated stateless searches.

## Scope

- Resolve `previous_response_id` through the existing tenant/business-scoped
  stored Responses lookup.
- Compose a bounded continuation retrieval query from the new input plus prior
  stored input and assistant output text.
- Strip visible citation markers from prior assistant output before using it as
  search context.
- Store chained input items for the new response.
- Reject invalid `previous_response_id` values and reject requests that combine
  `previous_response_id` with `conversation`.
- Add focused helper and route regressions.
- Update docs, ticket trail, and proof.

## Code Anchors

- `packages/svs_common/svs_common/openai_compat.py`
- `apps/api/svs_api/main.py`
- `tests/test_openai_compat_search.py`
- `tests/test_openai_responses_routes.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`

## Out Of Scope

- Implementing the OpenAI Conversations API.
- Carrying over previous top-level `instructions`.
- Adding model-generated prose.
- Changing database schema, RLS policies, API-key behavior, indexing semantics,
  provider routing, deployment, or admin UI behavior.

## Acceptance Criteria

- [x] `POST /v1/responses` with `previous_response_id` loads the stored prior
  response under the same tenant/business scope before retrieval.
- [x] The new retrieval query includes current input plus bounded prior
  input/output context and does not include prior visible citation markers.
- [x] Missing, deleted, or cross-scope previous responses fail before retrieval.
- [x] Requests that combine `previous_response_id` with `conversation` fail
  with 422.
- [x] The returned and stored response preserve `previous_response_id`.
- [x] Stored input items include the chained previous input items plus the new
  turn input items.
- [x] Focused and broad non-integration verification passes.

## Verification

Focused Responses/OpenAI compatibility verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_responses_routes.py tests/test_openai_compat_search.py
106 passed, 2 warnings
```

Compile verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass
```

Broad non-integration verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
307 passed, 2 warnings
```

Whitespace verification:

```text
git diff --check
pass
```
