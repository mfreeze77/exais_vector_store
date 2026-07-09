# WAVE-064 OpenAI Citation Span Contract

## Goal

Make OpenAI-style citation parity a shared code contract instead of route-local
convention. Any OpenAI-facing `file_citation` annotation must use the strict
Responses/API core fields and its `index` must point at the visible
`【n†source】` marker in returned text.

## References

Official OpenAI references checked on 2026-07-09:

- OpenAI file-search guide: annotations are visible in output text, while
  `file_search_call.results` are included only when callers pass
  `include: ["file_search_call.results"]`.
  https://developers.openai.com/api/docs/guides/tools-file-search#include-search-results-in-the-response
- OpenAI Assistants annotation guidance: file-search annotations reference
  uploaded files and visible marker substrings such as `【13†source】`.
  https://developers.openai.com/api/docs/assistants/deep-dive#message-annotations

## Scope

- Add a reusable OpenAI `file_citation` annotation validator.
- Add a reusable helper that confirms an annotation `index` lands exactly on an
  OpenAI-style visible source marker.
- Reuse the shared helpers in Responses citation replay/generation integrity and
  native retrieval answer integrity.
- Add focused regression proof for strict fields, non-empty file metadata, and
  marker-span failure.
- Update docs and trail.

## Non-Goals

- Changing the OpenAI-facing annotation shape.
- Adding model-generated prose.
- Changing direct vector-store search result payload fields.
- Changing tenant isolation, API-key lifecycle, indexing, provider routing,
  database migrations, deployment, or admin UI behavior.

## Acceptance Criteria

- [x] A shared helper validates strict OpenAI `file_citation` annotation fields:
  `type`, `index`, `file_id`, and `filename`.
- [x] A shared helper rejects annotation indexes that do not point at a visible
  `【n†source】` marker.
- [x] Responses citation integrity uses the shared contract.
- [x] Native retrieval answer citation integrity uses the shared contract.
- [x] Focused tests prove extra fields, empty file metadata, and bad marker
  indexes fail closed.
- [x] Focused and broad verification passes.

## Verification

- Focused OpenAI compatibility tests.
- Focused native retrieval answer/context citation tests.
- `python -m compileall -f -q packages apps tests`.
- Full non-integration suite.
- `git diff --check`.

## Proof

Focused OpenAI/native citation verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_retrieval_profile_resolution.py tests/test_retrieval_answer_routes.py
109 passed, 2 warnings
```

Focused Responses route verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_responses_routes.py tests/test_openai_compat_search.py
96 passed, 2 warnings
```

Compile proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass
```

Full non-integration proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
297 passed, 2 warnings
```

Whitespace proof:

```text
git diff --check
pass
```

Notes:

- The two warnings are existing FastAPI `on_event` deprecation warnings.
