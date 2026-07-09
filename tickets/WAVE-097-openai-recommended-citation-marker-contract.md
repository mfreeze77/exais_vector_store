# WAVE-097 OpenAI Recommended Citation Marker Contract

## Goal

Mimic OpenAI citation behavior beyond the Responses API `file_citation`
annotation object by adding a shared contract for OpenAI's recommended
model-facing citation marker syntax.

## OpenAI references

- Citation Formatting guide: recommends `\ue200` / `\ue202` / `\ue201`
  marker delimiters, `cite` as the citation family, source IDs such as
  `turn0file0`, optional line locators, and parsing/stripping of generated
  citations:
  https://developers.openai.com/api/docs/guides/citation-formatting
- Assistants annotation guidance: client renderers replace visible generated
  source substrings with citation UI:
  https://developers.openai.com/api/docs/assistants/deep-dive#message-annotations

## Scope

- Add shared helpers for OpenAI recommended model citation source IDs, markers,
  extraction, and stripping.
- Add native citation proof fields for `model_source_id` and `model_marker`
  while preserving strict OpenAI-facing `file_citation` annotations.
- Strip recommended `\ue200cite...\ue201` markers from prior Responses output
  before reusing it as retrieval context.
- Document the difference between OpenAI API annotations and model-facing
  citation markers.

## Out of scope

- Changing `output_text.annotations` fields.
- Replacing existing visible `【n†source】` markers in Responses output.
- Adding LLM-generated prose or hosted OpenAI tool behavior.
- Changing retrieval ranking, filters, tenant isolation, API keys, indexing, or
  provider routing.

## Acceptance criteria

- [x] Shared helpers format `\ue200cite\ue202turn0file0\ue201` and line-locator
  variants, parse single-source and multi-source markers, and strip them by
  offset.
- [x] Direct vector-store search native citations include `model_source_id` and
  `model_marker`.
- [x] Responses native citations include `model_source_id` and `model_marker`.
- [x] Prior response continuation strips both visible `【n†source】` markers and
  recommended model-facing markers before search.
- [x] Strict OpenAI-facing `file_citation` annotations remain limited to
  `type`, `index`, `file_id`, and `filename`.

## Changed files

- `packages/svs_common/svs_common/openai_compat.py`
- `tests/test_openai_compat_search.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`
- `tickets/README.md`
- `tickets/WAVE-097-openai-recommended-citation-marker-contract.md`

## Verification

- Focused OpenAI/citation/OpenAPI:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_openai_responses_routes.py tests/test_openapi_contract.py`
  - Result: `128 passed, 2 warnings in 4.77s`
- Compile:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests`
  - Result: pass
- Broad non-integration:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration`
  - Result: `409 passed, 2 warnings in 6.28s`
- Whitespace:
  `git diff --check`
  - Result: pass
