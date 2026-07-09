# WAVE-051 Vector Store Search Visible Citation Markers

## Summary

Make direct OpenAI-compatible vector-store search result annotations point at
visible `【n†source】` markers in returned text content. ExAIS already exposes
strict OpenAI-shaped `file_citation` annotations on search results; this ticket
ensures those annotations are renderable with the same marker/index invariant
used by Responses file-search output.

## Background

Official OpenAI references checked during this ticket:

- File-search guide: Responses file-search output exposes file references as
  annotations, and raw file-search result rows are opt-in through `include`.
- Assistants annotation guidance: file-search annotations correspond to visible
  generated source-marker substrings such as `【13†source】`.

WAVE-050 added a generation-time guard for Responses payloads, but direct
`/v1/vector_stores/{vector_store_id}/search` result content still emitted
annotations with `index: 0` while the returned chunk text did not contain a
visible marker at index 0. Because ExAIS intentionally exposes OpenAI-shaped
annotations on direct search results as a compatibility extension, the direct
search surface should satisfy the same user-visible marker invariant whenever
content is included.

## Scope

- Append visible OpenAI-style source markers to direct vector-store search result
  text content when `include_content=true`.
- Set each direct search `file_citation.index` to the marker offset in that
  returned text.
- Preserve strict OpenAI-facing annotation fields:
  `type`, `index`, `file_id`, and `filename`.
- Preserve richer native citation metadata outside the strict annotation object.
- Preserve metadata-only source handles when `include_content=false`.
- Update focused tests, docs, ticket trail, and proof.

## Code Anchors

- `packages/svs_common/svs_common/openai_compat.py`
- `tests/test_openai_compat_search.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`

## Out Of Scope

- Changing Responses citation formatting or streaming events.
- Changing retrieval ranking, filters, ACL behavior, indexing, API keys, storage,
  provider routing, or deployment behavior.
- Claiming undocumented OpenAI internals for direct vector-store search results.
- Validating or migrating historical stored Responses payloads.

## Acceptance Criteria

- [x] Direct search result content includes a visible `【n†source】` marker when
  content is returned.
- [x] Direct search result `annotations[].index` points at that visible marker.
- [x] Direct search result annotations remain strict OpenAI-shaped
  `file_citation` objects without native metadata.
- [x] Native `citation.annotation` mirrors the result-level annotation.
- [x] Sensitive-output redaction still runs before marker insertion and preserves
  marker indexes.
- [x] `include_content=false` continues to return source handles without result
  text.
- [x] Focused and broad non-integration verification passes.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_openai_responses_routes.py tests/test_openai_vector_store_object.py
84 passed, 2 warnings

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
250 passed, 2 warnings

git diff --check
pass
```
