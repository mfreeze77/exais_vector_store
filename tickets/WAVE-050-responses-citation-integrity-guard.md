# WAVE-050 Responses Citation Integrity Guard

## Summary

Add a generation-time integrity guard for OpenAI-compatible Responses
file-search citations. Before ExAIS stores, returns, or streams a newly created
Responses file-search payload, it should prove that every strict
`file_citation` annotation points at the visible `【n†source】` marker in the
output text and that native citation proof mirrors those OpenAI annotations.

## Background

Official OpenAI references checked on 2026-07-08:

- File-search guide: Responses file search returns a `file_search_call` output
  item plus a message output item with file citations in the `output_text`
  content annotations.
- Assistants annotation guidance: file-search annotations correspond to visible
  generated source-marker substrings such as `【13†source】`.
- File-search guide examples show `file_citation` annotations with
  `type`, `index`, `file_id`, and `filename`.

Prior citation waves implemented the visible markers, strict annotation shape,
included result gating, native annotation mirrors, stream citation events,
stream resume, stream obfuscation, and `tool_choice` guards. This ticket adds a
runtime invariant check at the route boundary so future formatter changes cannot
silently return broken citation indexes or native/OpenAI annotation mismatches.

## Scope

- Add a reusable citation-integrity helper for completed Responses file-search
  payloads.
- Verify OpenAI-facing `output_text.annotations[]` entries are strict
  `file_citation` objects with only `type`, `index`, `file_id`, and `filename`.
- Verify each annotation index is within the output text and points at a visible
  `【n†source】` marker.
- Verify native top-level `citations[]` mirrors the OpenAI-facing annotations
  and marker text when citations are present.
- Call the guard after deterministic response generation and before storing,
  returning, or streaming a created response.
- Update focused helper/route tests, docs, trail, and proof.

## Code Anchors

- `packages/svs_common/svs_common/openai_compat.py`
- `apps/api/svs_api/main.py`
- `tests/test_openai_compat_search.py`
- `tests/test_openai_responses_routes.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`

## Out Of Scope

- Changing the OpenAI annotation shape.
- Validating arbitrary historical stored responses on retrieval.
- Adding model-generated answer verification.
- Changing stream event payloads.
- Changing API key, tenant, indexing, provider, or deployment behavior.

## Acceptance Criteria

- [x] Valid generated file-search Responses pass the integrity guard.
- [x] Extra fields or malformed OpenAI annotation objects fail the guard.
- [x] Annotation indexes that do not point at a visible `【n†source】` marker fail
  the guard.
- [x] Native `citations[].annotation` mismatches fail the guard.
- [x] `POST /v1/responses` does not store/return/stream a newly generated
  payload that fails citation integrity.
- [x] Existing JSON and streaming citation shapes remain unchanged for valid
  responses.
- [x] Focused and broad non-integration verification passes.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_openai_responses_routes.py
73 passed, 2 warnings

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
250 passed, 2 warnings

git diff --check
pass
```
