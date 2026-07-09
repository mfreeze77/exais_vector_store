# WAVE-099 OpenAI Citation Replacement Span Contract

## Goal

Tighten OpenAI citation mimicry for renderer clients by making ExAIS-native
citation proof carry exact replacement spans for the visible source marker while
preserving the strict OpenAI `file_citation` annotation object.

## OpenAI references

- Responses create reference: `output_text.annotations` includes strict
  `file_citation` objects with `file_id`, `filename`, `index`, and `type`.
  https://api.openai.com/v1/responses
- File search guide: annotations are visible in output text, while
  `file_search_call.results` remains opt-in through `include`.
  https://developers.openai.com/api/docs/guides/tools-file-search#include-search-results-in-the-response
- Assistants annotation guidance: client renderers replace model-generated
  source substrings with citation UI.
  https://developers.openai.com/api/docs/assistants/deep-dive#message-annotations

## Scope

- Add exact `start_index`/`end_index` replacement spans to native citation proof
  for Responses and direct vector-store search citations.
- Extend `openai_response_citation_references` so internal renderer mappings
  include the same exact span.
- Advertise the native span fields in typed OpenAPI/Pydantic schemas.
- Document that spans remain native proof and never enter
  `output_text.annotations[]`.

## Out of scope

- Changing OpenAI-facing `file_citation` annotation fields.
- Changing visible marker text, marker numbering, or stream event ordering.
- Adding hosted OpenAI tool behavior, LLM-generated citation prose, retrieval
  ranking, filters, tenant isolation, API keys, indexing, provider routing,
  deployment, or admin UI behavior.

## Acceptance criteria

- [x] Direct vector-store search native `citation` objects expose
  `start_index`/`end_index` for visible marker text.
- [x] Responses native `citations[]` entries expose `start_index`/`end_index`
  matching their strict `file_citation.index` and visible marker length.
- [x] `openai_response_citation_references` returns replacement spans along
  with output/content/annotation indexes, marker text, and the strict
  annotation object.
- [x] OpenAI-facing annotations remain limited to `type`, `index`, `file_id`,
  and `filename`.
- [x] Focused, compile, broad non-integration, and whitespace verification pass.

## Changed files

- `packages/svs_common/svs_common/openai_compat.py`
- `packages/svs_common/svs_common/schemas.py`
- `tests/test_openai_compat_search.py`
- `tests/test_openapi_contract.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`
- `tickets/README.md`
- `tickets/WAVE-099-openai-citation-replacement-span-contract.md`

## Verification

Focused OpenAI citation/Responses/OpenAPI verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_openai_responses_routes.py tests/test_openapi_contract.py
128 passed, 2 warnings in 5.15s
```

Compile proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass
```

Broad non-integration proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
411 passed, 2 warnings in 6.05s
```

Whitespace proof:

```text
git diff --check
pass
```

Notes:

- The two warnings are existing FastAPI `on_event` deprecation warnings.

## QC

Decision: PASS

Ticket reviewed:
- `tickets/WAVE-099-openai-citation-replacement-span-contract.md`

Evidence reviewed:
- `packages/svs_common/svs_common/openai_compat.py`
- `packages/svs_common/svs_common/schemas.py`
- `tests/test_openai_compat_search.py`
- `tests/test_openapi_contract.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`
- `tickets/README.md`
- Focused citation/Responses/OpenAPI proof: `128 passed, 2 warnings in 5.15s`
- Compile proof: passed
- Broad non-integration proof: `411 passed, 2 warnings in 6.05s`
- Whitespace proof: `git diff --check` passed

Acceptance criteria:
- [pass] Direct vector-store search native `citation` objects expose
  `start_index`/`end_index` for visible marker text.
- [pass] Responses native `citations[]` entries expose `start_index`/`end_index`
  matching strict `file_citation.index` and visible marker length.
- [pass] `openai_response_citation_references` returns replacement spans along
  with output/content/annotation indexes, marker text, and the strict
  annotation object.
- [pass] OpenAI-facing annotations remain limited to `type`, `index`, `file_id`,
  and `filename`.
- [pass] Focused, compile, broad non-integration, and whitespace verification
  passed.

Findings:
- None.

Required fixes before next ticket:
- None.
