# WAVE-041 Responses Multi-Store Duplicate Citation Dedupe

## Summary

Deduplicate exact duplicate Responses file-search results after multiple
requested vector stores are searched, so a shared file or chunk attached through
more than one vector store does not produce repeated deterministic excerpts,
markers, annotations, and included result rows.

## Background

Official OpenAI references checked on 2026-07-08:

- The file-search guide says a `file_search` tool can search a supplied list of
  `vector_store_ids`.
- The same guide says Responses output contains a `file_search_call` item and a
  `message` item with file citations.
- The Responses API schema supports `include=["file_search_call.results"]` for
  including search result bodies.

ExAIS already deduplicates repeated chunks inside a single vector-store search
when deterministic query planning runs multiple subqueries. The Responses layer
still flattens multiple vector-store pages by concatenation, so the same chunk
can appear twice if the same file is attached to more than one requested vector
store. That hurts retrieval quality and citation readability.

## Scope

- Deduplicate exact duplicate file-search items when flattening multiple
  vector-store search pages for a Responses file-search output.
- Prefer the highest-scored duplicate item for returned text, score, attributes,
  marker, annotation, and included result row.
- Preserve native audit proof by recording all contributing vector-store IDs on
  the top-level/native citation object.
- Keep included `file_search_call.results` and `search_results` entries
  OpenAI-shaped with only `file_id`, `filename`, `score`, `text`, and
  `attributes`.
- Add formatter and route-level regression tests.
- Update docs and proof.

## Code Anchors

- `packages/svs_common/svs_common/openai_compat.py`
- `tests/test_openai_compat_search.py`
- `tests/test_openai_responses_routes.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`

## Out Of Scope

- Changing `/v1/vector_stores/{id}/search` result semantics.
- Deduplicating different chunks from the same file.
- New database indexes, migrations, provider routing, API key behavior,
  tenant isolation behavior, deployment work, or admin UI work.
- Removing native top-level `citations`.
- Streaming Responses output.

## Acceptance Criteria

- [x] Responses file-search flattening emits one output item for duplicate
  chunks seen through multiple vector stores.
- [x] The highest-scored duplicate supplies the returned text, score,
  annotation, and included OpenAI-shaped result row.
- [x] Native citation proof records all contributing vector-store IDs outside
  the OpenAI-core annotation and included result objects.
- [x] Distinct chunks from the same file are not collapsed.
- [x] Route-level proof covers a `file_search` tool with multiple
  `vector_store_ids`.
- [x] Focused and broad non-integration verification passes.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_openai_responses_routes.py
44 passed, 2 warnings

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
214 passed, 2 warnings

git diff --check
pass
```
