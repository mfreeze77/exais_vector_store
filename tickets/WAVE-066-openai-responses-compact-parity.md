# WAVE-066 OpenAI Responses Compact Parity

## Goal

Add the OpenAI-compatible `POST /v1/responses/compact` utility route so long
Responses conversations can hand off compacted state through the same object
shape current OpenAI SDK clients expect.

## References

Official OpenAI references checked on 2026-07-09:

- OpenAI endpoint list includes `/responses/compact`.
  https://api.openai.com/v1/responses/compact
- OpenAI OpenAPI reference describes `POST /responses/compact` as compacting a
  conversation and returning a compacted response object.
  https://api.openai.com/v1/responses/compact
- OpenAI prompt guidance says Responses compaction returns an
  `encrypted_content` item that can be passed into future requests, and callers
  should treat compacted items as opaque state.
  https://developers.openai.com/api/docs/guides/prompt-guidance#preserve-behavior-in-long-sessions

## Scope

- Add a shared Responses compact helper that returns `object:
  "response.compaction"`.
- Add `POST /v1/responses/compact` under the existing Responses
  `retrieval:read` scope.
- Preserve user input messages in the compaction output.
- Add a `type: "compaction"` output item with opaque `encrypted_content`.
- Return deterministic usage estimates and fail closed on malformed requests.
- Update docs and ticket trail.

## Non-Goals

- Implementing OpenAI-hosted ZDR encryption.
- Running a model-generated summarizer.
- Storing compacted responses in `openai_responses`.
- Changing `/v1/responses` citation generation, streaming, lifecycle storage,
  tenant isolation, API-key lifecycle, database migrations, indexing, provider
  routing, deployment, or admin UI behavior.

## Acceptance Criteria

- [x] `POST /v1/responses/compact` exists before dynamic
  `/v1/responses/{response_id}` routing can capture it.
- [x] The response object is `response.compaction` with `id`, `created_at`,
  `output`, and OpenAI-shaped `usage`.
- [x] User input messages are preserved as completed message items with
  `input_text` content.
- [x] Non-user prior output is represented by an opaque compaction item instead
  of being copied into visible output.
- [x] Missing model, non-object payloads, and streaming compact requests fail
  closed.
- [x] Focused and broad verification passes.

## Verification

- Focused Responses/OpenAI compatibility tests.
- `python -m compileall -f -q packages apps tests`.
- Full non-integration suite.
- `git diff --check`.

## Proof

Focused Responses/OpenAI compatibility verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_responses_routes.py tests/test_openai_compat_search.py
101 passed, 2 warnings
```

Compile proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass
```

Full non-integration proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
302 passed, 2 warnings
```

Whitespace proof:

```text
git diff --check
pass
```

Notes:

- The two warnings are existing FastAPI `on_event` deprecation warnings.
