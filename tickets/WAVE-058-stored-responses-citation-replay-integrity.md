# WAVE-058 Stored Responses Citation Replay Integrity

## Goal

Ensure OpenAI-compatible stored Responses cannot later return or stream invalid
file-search citation annotations. Create-time Responses already run the strict
citation guard; replay must use the same guard before any stored payload leaves
`GET /v1/responses/{response_id}`.

## Scope

- Reuse the existing Responses citation integrity guard for stored response
  retrieval.
- Fail closed for both normal stored response reads and `stream=true` replay.
- Correct stored replay fixtures so annotation indexes point at the actual
  visible `【n†source】` marker offset.
- Add route regressions for bad persisted annotation indexes and missing native
  citation proof.
- Document that persisted Responses are rechecked before replay.

## Non-Goals

- Changing create-time Responses citation formatting.
- Adding Assistants/thread APIs.
- Changing direct vector-store search result shape.
- Adding provider-generated prose or LLM citation synthesis.
- Removing ExAIS-native top-level citation audit fields.

## Acceptance Criteria

- [x] `GET /v1/responses/{response_id}` validates stored citation annotations
  before returning the response.
- [x] `GET /v1/responses/{response_id}?stream=true` validates stored citation
  annotations before creating the replay stream.
- [x] Persisted annotations whose `index` does not point at a visible
  `【n†source】` marker return HTTP 500 instead of emitting invalid output.
- [x] Persisted OpenAI-facing annotations without matching native citation
  proof return HTTP 500.
- [x] Existing create, stream, include, and resume citation behavior remains
  unchanged.

## Verification

- Focused OpenAI Responses route and compatibility tests.
- Full non-integration suite.
- `python -m compileall -f -q packages apps tests`.
- `git diff --check`.

## Proof

Focused Responses citation replay verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_responses_routes.py tests/test_openai_compat_search.py
84 passed, 2 warnings
```

Compile proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass
```

Full non-integration proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
272 passed, 2 warnings
```

Whitespace proof:

```text
git diff --check
pass
```

Notes:

- The two warnings are existing FastAPI `on_event` deprecation warnings.
