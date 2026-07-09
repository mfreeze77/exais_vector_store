# WAVE-062 OpenAI Responses Cancel Parity

## Goal

Close the OpenAI-compatible Responses lifecycle gap for
`POST /v1/responses/{response_id}/cancel`.

Official OpenAI reference checked on 2026-07-09:

- https://developers.openai.com/api/reference/resources/responses/methods/cancel/
- `POST /responses/{response_id}/cancel` cancels a response by ID.
- Only responses created with `background: true` are cancellable.

## Scope

- Add `POST /v1/responses/{response_id}/cancel`.
- Reuse existing tenant/business scoped stored-response lookup.
- Require `retrieval:read`, matching existing Responses retrieve/delete routes.
- Require the stored response payload to have `background: true`.
- Update the stored response JSON payload and row status to `cancelled`.
- Preserve citation integrity for stored payloads with annotations.
- Add `Idempotency-Key` support for retry-safe cancel calls.

## Non-Goals

- Background model execution.
- Worker-side cancellation.
- Streaming interruption for an active HTTP request.
- Database schema or migration changes.
- Changing existing create/retrieve/delete/input-items behavior.

## Acceptance Criteria

- [x] `POST /v1/responses/{response_id}/cancel` returns the stored response
  object with `status: cancelled`.
- [x] The route updates the `openai_responses.status` column and stored
  response JSON payload.
- [x] Non-background responses return a client error instead of being cancelled.
- [x] Missing or deleted responses continue to return the existing 404 shape.
- [x] Citation integrity remains enforced before storing/returning cancelled
  payloads.
- [x] Matching idempotency retries return the original cancel response without
  re-running the mutation.
- [x] Existing Responses route behavior remains unchanged.

## Verification

- Focused Responses route tests.
- Full non-integration suite.
- `python -m compileall -f -q packages apps tests`.
- `git diff --check`.

## Proof

- Focused Responses route tests:
  `python -m pytest -q -rs tests/test_openai_responses_routes.py`
  - Result: 29 passed, 2 warnings.
- Compile:
  `python -m compileall -f -q packages apps tests`
  - Result: passed.
- Full non-integration suite:
  `python -m pytest -q -rs tests --ignore=tests/integration`
  - Result: 292 passed, 2 warnings.
- Whitespace:
  `git diff --check`
  - Result: passed.
