# WAVE-063 OpenAI Responses Input Tokens Parity

## Goal

Close the OpenAI-compatible Responses utility gap for
`POST /v1/responses/input_tokens` so SDK clients can preflight request size
before creating a file-search response.

Official OpenAI reference checked on 2026-07-09:

- https://developers.openai.com/api/reference/python/resources/responses/subresources/input_tokens/methods/count/
- `POST /responses/input_tokens` returns an object with
  `object: response.input_tokens` and an `input_tokens` count.

## Scope

- Add `POST /v1/responses/input_tokens`.
- Reuse existing `retrieval:read` authorization for Responses-compatible
  surfaces.
- Count common Responses request inputs deterministically without running
  retrieval or requiring a file-search tool.
- Include text-bearing request fields such as `input`, `instructions`, tools,
  tool choice, text config, reasoning config, and previous response IDs.
- Document that this is a deterministic compatibility estimate, not
  provider-tokenizer billing truth.

## Non-Goals

- Provider-specific tokenizer integration.
- Image/audio/file byte token accounting.
- Retrieval execution, storage, idempotency, or usage-event writes.
- Changes to `POST /v1/responses` behavior.

## Acceptance Criteria

- [x] `POST /v1/responses/input_tokens` returns
  `{object: "response.input_tokens", input_tokens: N}`.
- [x] The route requires `retrieval:read`.
- [x] Text input and structured message input both produce positive counts.
- [x] Tool definitions contribute to the count.
- [x] The route does not execute retrieval or store a response.
- [x] Existing Responses create/retrieve behavior remains unchanged.

## Verification

- Focused Responses route tests.
- Focused OpenAI compatibility helper tests.
- Full non-integration suite.
- `python -m compileall -f -q packages apps tests`.
- `git diff --check`.

## Proof

- Focused Responses route and compatibility helper tests:
  `python -m pytest -q -rs tests/test_openai_responses_routes.py tests/test_openai_compat_search.py`
  - Result: 95 passed, 2 warnings.
- Compile:
  `python -m compileall -f -q packages apps tests`
  - Result: passed.
- Full non-integration suite:
  `python -m pytest -q -rs tests --ignore=tests/integration`
  - Result: 296 passed, 2 warnings.
- Whitespace:
  `git diff --check`
  - Result: passed.
