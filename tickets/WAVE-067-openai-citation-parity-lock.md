# WAVE-067 OpenAI Citation Parity Lock

## Summary

Lock the OpenAI Responses file-search citation contract with an explicit
regression that mirrors the official guide shape across JSON response content,
included result bodies, and streaming annotation events.

## Background

Official OpenAI references checked on 2026-07-09:

- File search guide: Responses file search returns a `file_search_call` output
  item plus an assistant `message` with `output_text.annotations` file
  citations.
  https://developers.openai.com/api/docs/guides/tools-file-search
- File search guide include section: result bodies are opt-in through
  `include: ["file_search_call.results"]`.
  https://developers.openai.com/api/docs/guides/tools-file-search#include-search-results-in-the-response
- Responses OpenAPI reference for `POST /v1/responses`: file-search examples
  use strict `file_citation` annotations with `type`, `index`, `file_id`, and
  `filename`.
  https://api.openai.com/v1/responses

Prior waves built the formatter, include gating, result alias, streaming events,
stored replay guard, and native citation mirrors. This ticket makes the
OpenAI-facing citation shape an explicit regression target so future ExAIS proof
fields cannot drift into SDK-facing citation objects.

## Scope

- Add a focused formatter regression that asserts the OpenAI-facing
  `file_search_call`, `message`, `output_text`, included result row, and
  `response.output_text.annotation.added` shapes.
- Keep native ExAIS citation proof available under top-level `citations`.
- Document the citation shape as a compatibility contract.
- Update ticket trail and proof.

## Code Anchors

- `packages/svs_common/svs_common/openai_compat.py`
- `tests/test_openai_compat_search.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`

## Out Of Scope

- Changing citation marker text or annotation indexes.
- Changing OpenAI-facing annotation fields.
- Adding model-generated prose.
- Changing retrieval, tenant isolation, API keys, indexing, provider routing,
  deployment, or admin UI behavior.

## Acceptance Criteria

- [x] The regression asserts `output_text.annotations[]` contains only
  `type`, `index`, `file_id`, and `filename`.
- [x] The regression asserts the annotation `index` points at the visible
  `【n†source】` marker in returned output text.
- [x] The regression asserts included `file_search_call.results` rows contain
  only OpenAI result fields.
- [x] The regression asserts streaming
  `response.output_text.annotation.added` events carry the same strict
  annotation object.
- [x] Docs describe the citation shape as a locked compatibility contract.
- [x] Focused and broad non-integration verification passes.

## Verification

Focused Responses/OpenAI compatibility verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_responses_routes.py tests/test_openai_compat_search.py
102 passed, 2 warnings
```

Compile verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass
```

Broad non-integration verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
303 passed, 2 warnings
```

Whitespace verification:

```text
git diff --check
pass
```
