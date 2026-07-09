# WAVE-057 Native Retrieval Answer Citation Integrity

## Goal

Implement the native `/api/v1/retrieval/answer` endpoint promised in the
planning spec and close the remaining citation gap called out in
`docs/TICKET_TRAIL.md`: generated answer payloads must be returned only when
their visible citation markers and OpenAI-core annotation indexes are valid.

## Scope

- Add native retrieval answer request/response schemas.
- Add a retrieval service answer builder that uses the existing context-pack
  retrieval path as its source of truth.
- Build an extractive cited answer from included context-pack chunks without
  adding provider-generation or model-router behavior.
- Verify every returned answer citation before the payload leaves the service:
  visible `【n†source】` marker, exact annotation offset, strict
  `{type, index, file_id, filename}` annotation, and no stray source markers.
- Apply existing output redaction to answer snippets before marker insertion.
- Add the FastAPI route under the existing `retrieval:read` scope and vector
  store activity refresh behavior.

## Non-Goals

- LLM/provider prose generation.
- OpenAI Responses route changes.
- Direct vector-store search shape changes.
- Tenant isolation, API-key lifecycle, migrations, provider routing, or admin UI
  changes beyond the required route import/wiring.

## Acceptance Criteria

- [x] `POST /api/v1/retrieval/answer` exists and returns a typed native answer
  payload.
- [x] The answer is assembled from context-pack chunks and includes visible
  `【n†source】` markers.
- [x] `citations[].annotation.index` points to the marker offset in the returned
  answer text.
- [x] The answer citation integrity guard rejects stray markers, malformed
  annotations, or annotation indexes that do not point at the marker.
- [x] Sensitive snippets are redacted before answer citation markers are added.
- [x] Context-pack expansion/trimming behavior remains the source of truth for
  which chunks may be cited.
- [x] Existing Responses and direct vector-store search citation behavior
  remains unchanged.

## Verification

- Focused retrieval answer/context-pack tests.
- Focused OpenAI compatibility citation tests.
- Full non-integration suite.
- `python -m compileall -f -q packages apps tests`.
- `git diff --check`.

## Proof

Focused answer/context/OpenAI citation verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_retrieval_profile_resolution.py tests/test_retrieval_answer_routes.py tests/test_openai_compat_search.py tests/test_openai_responses_routes.py
125 passed, 2 warnings
```

Compile proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass
```

Full non-integration proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
269 passed, 2 warnings
```

Whitespace proof:

```text
git diff --check
pass
```

Notes:

- The two warnings are existing FastAPI `on_event` deprecation warnings.
- This ticket does not add provider-generated prose; it returns extractive cited
  answers from the verified context-pack source set.
