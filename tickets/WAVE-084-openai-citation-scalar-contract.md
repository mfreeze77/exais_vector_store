# WAVE-084 OpenAI Citation Scalar Contract

## Objective

Tighten OpenAI citation mimicry by making the shared `file_citation`
annotation contract reject invalid scalar values before they can drift into
runtime responses, streams, native citation mirrors, or generated OpenAPI.

## Evidence Anchors

- OpenAI Responses `POST /v1/responses` file-search example uses strict
  `file_citation` annotations with `type`, `index`, `file_id`, and `filename`.
- OpenAI Assistants message annotation guidance describes `file_citation`
  annotations as references to uploaded files and shows visible
  `【n†source】` marker strings in message text.
- `packages/svs_common/svs_common/openai_compat.py`
- `packages/svs_common/svs_common/schemas.py`
- `tests/test_openai_compat_search.py`
- `tests/test_openapi_contract.py`

## Scope

- Keep OpenAI-facing citation objects strict: only `type`, `index`, `file_id`,
  and `filename`.
- Reject negative annotation indexes in the shared runtime validator and
  constructor.
- Reject blank `file_id` and `filename` values in runtime validation.
- Expose the same scalar constraints through the
  `OpenAIFileCitationAnnotation` schema used by Responses and vector-store
  search OpenAPI components.
- Add focused regression proof and docs.

## Non-Goals

- Adding ExAIS-native metadata to OpenAI-facing annotations.
- Changing citation marker text, marker placement, same-index citation support,
  streaming event shape, retrieval ranking, API keys, tenant isolation,
  indexing, provider routing, deployment, or admin UI behavior.

## Acceptance

- [x] `openai_file_citation_annotation` and
  `validate_openai_file_citation_annotation` reject negative indexes.
- [x] Runtime citation validation rejects blank `file_id` or `filename` values.
- [x] `OpenAIFileCitationAnnotation` OpenAPI schema exposes non-negative
  `index` and non-empty `file_id`/`filename` constraints.
- [x] Existing Responses and vector-store citation shapes remain strict and
  unchanged except for invalid scalar rejection.
- [x] Focused citation/OpenAPI tests pass.
- [x] Compile, broad non-integration tests, and `git diff --check` pass.

## Proof

- Focused citation/OpenAPI:
  `python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_openai_responses_routes.py tests/test_openapi_contract.py tests/test_retrieval_answer_routes.py`
  passed with `117 passed, 2 warnings in 3.93s`.
- Compile:
  `python -m compileall -f -q packages apps tests` passed.
- Broad non-integration:
  `python -m pytest -q -rs tests --ignore=tests/integration` passed with
  `380 passed, 2 warnings in 5.41s`.
- Whitespace:
  `git diff --check` passed.
