# WAVE-093 OpenAI Citation Client Marker Contract

## Objective

Lock OpenAI-style file-search citations as a client-renderable contract: each
Responses `output_text.annotations[]` entry must resolve by `index` to the exact
visible `【n†source】` marker that clients replace or render, while the annotation
object itself remains strict OpenAI shape.

## Evidence Anchors

Official OpenAI references checked on 2026-07-09:

- File search guide: annotations are visible in output text, while
  `file_search_call.results` are included only when callers pass
  `include: ["file_search_call.results"]`.
  https://developers.openai.com/api/docs/guides/tools-file-search#include-search-results-in-the-response
- Assistants annotation guidance: file-search annotations reference uploaded
  files and visible marker substrings such as `【13†source】`.
  https://developers.openai.com/api/docs/assistants/deep-dive#message-annotations

## Scope

- Add a shared citation-reference helper that validates and returns the
  output/content/annotation position, visible marker text, and strict OpenAI
  `file_citation` annotation.
- Route the Responses citation integrity guard through the shared helper.
- Add focused proof that generated Responses output, native citation proof, and
  stream annotation events all point to the same client-replaceable marker.
- Update docs, ticket trail, and proof.

## Non-Goals

- Adding `text`, `quote`, chunk IDs, page data, or other native proof fields to
  OpenAI-facing `output_text.annotations[]`.
- Changing citation marker text, marker placement, annotation scalar fields,
  ranking, API keys, tenant isolation, indexing, provider routing, deployment,
  or admin UI behavior.

## Acceptance

- [x] A shared helper returns client-renderable citation references from a
  Responses payload.
- [x] The citation integrity guard uses the helper and still rejects orphan
  visible markers.
- [x] A focused regression proves annotation `index`, native `citations[].marker`,
  and streaming `response.output_text.annotation.added.annotation` describe the
  same citation.
- [x] OpenAI-facing annotations remain limited to `type`, `index`, `file_id`,
  and `filename`.
- [x] Focused, compile, broad non-integration, and whitespace verification pass.

## Proof

Focused Responses/OpenAI citation verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_openai_responses_routes.py
114 passed, 2 warnings in 3.55s
```

Compile proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass
```

Broad non-integration proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
391 passed, 2 warnings in 5.23s
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
- `tickets/WAVE-093-openai-citation-client-marker-contract.md`

Evidence reviewed:
- `packages/svs_common/svs_common/openai_compat.py`
- `tests/test_openai_compat_search.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`
- `tickets/README.md`
- Focused Responses/OpenAI citation proof: `114 passed, 2 warnings in 3.55s`
- Compile proof: passed
- Broad non-integration proof: `391 passed, 2 warnings in 5.23s`
- Whitespace proof: `git diff --check` passed

Acceptance criteria:
- [pass] `openai_response_citation_references` returns client-renderable
  citation references from Responses payloads.
- [pass] `ensure_openai_response_citation_integrity` routes through the helper
  while preserving orphan-marker rejection.
- [pass] Focused regression proves output annotation indexes, native markers,
  and streaming annotation events describe the same citation.
- [pass] OpenAI-facing annotations stay limited to `type`, `index`, `file_id`,
  and `filename`.
- [pass] Focused, compile, broad non-integration, and whitespace verification
  passed.

Findings:
- None.

Required fixes before next ticket:
- None.
