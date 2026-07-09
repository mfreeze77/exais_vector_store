# WAVE-077 OpenAI Same-Index Citation Parity

## Summary

Lock OpenAI-style file-search citation behavior where multiple strict
`file_citation` annotations may point at the same visible citation marker in
one `output_text` part.

## Background

Official OpenAI references checked on 2026-07-09:

- File search guide: Responses file search returns a `file_search_call` item
  plus an assistant `message` whose `output_text.annotations` contain
  `file_citation` objects.
  https://developers.openai.com/api/docs/guides/tools-file-search
- The guide's example includes repeated `file_citation` annotations sharing the
  same `index`, proving clients must tolerate multiple source references at one
  visible answer location.
  https://developers.openai.com/api/docs/guides/tools-file-search

Prior ExAIS waves locked the strict citation object, visible marker offsets,
included result bodies, streaming annotation events, replay integrity, OpenAPI
schemas, and native citation mirrors. This ticket makes same-index
multi-citation output an explicit regression target.

## Scope

- Add a focused regression proving two `file_citation` annotations can share one
  marker offset while preserving strict OpenAI fields.
- Prove the citation integrity guard accepts this shape only when native
  citation proof mirrors each annotation and marker.
- Prove streaming emits both `response.output_text.annotation.added` events in
  order.
- Document same-marker multi-citation support.

## Code Anchors

- `packages/svs_common/svs_common/openai_compat.py`
- `tests/test_openai_compat_search.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`

## Out Of Scope

- Changing citation marker text.
- Adding native metadata to OpenAI-facing annotation objects.
- Changing retrieval ranking, dedupe, file-search result includes, API keys,
  rate limits, tenant isolation, indexing, or provider routing.

## Acceptance Criteria

- [x] A regression covers multiple `output_text.annotations[]` entries with the
  same `index`.
- [x] The regression proves every OpenAI-facing annotation remains strict:
  `type`, `index`, `file_id`, and `filename` only.
- [x] The regression proves streaming emits one annotation-added event per
  annotation while preserving order.
- [x] Docs describe same-marker multi-citation support as part of OpenAI
  citation mimicry.
- [x] Focused and broad non-integration verification passes.

## Verification

Focused Responses/OpenAI citation verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_openai_responses_routes.py
108 passed, 2 warnings
```

Compile verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass
```

Broad non-integration verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
368 passed, 2 warnings
```

Whitespace verification:

```text
git diff --check
pass
```
