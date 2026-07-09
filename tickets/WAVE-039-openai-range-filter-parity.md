# WAVE-039 OpenAI Range Filter Parity

## Summary

Add OpenAI-style range comparison filters for safe vector-store file attributes.
W38 added `in` and simple `or` parity; current OpenAI retrieval docs also call
out date-range attribute filtering. ExAIS should accept `gt`, `gte`, `lt`, and
`lte` over safe primitive file attributes and enforce those filters wherever
retrieval can produce cited chunks.

## Background

Official OpenAI reference checked on 2026-07-08:

- The retrieval guide says attribute filtering can restrict searches to a
  specific date range.
- The same guide describes comparison filters and compound filters.

ExAIS currently rejects range operators with HTTP 422. That blocks common
OpenAI-compatible retrieval requests such as "documents created after this
date" even when file attributes contain ISO date strings or numeric values.

## Scope

- Support safe file-attribute `gt`, `gte`, `lt`, and `lte` filters.
- Preserve existing `eq`, `in`, `and`, and simple safe-attribute `or` behavior.
- Allow range filters as standalone filters and inside `and` compounds.
- Enforce range filters in Postgres sparse fallback, embedding-profile
  selection, hydration, neighbor expansion, and parent-section expansion.
- Add numeric range filters to the Qdrant dense prefilter.
- Add string/date and numeric range filters to the OpenSearch sparse prefilter.
- Preserve sensitive attribute rejection and reject range filters over booleans,
  structured values, and internal ExAIS fields.
- Update docs and proof.

## Code Anchors

- `packages/svs_common/svs_common/openai_compat.py`
- `packages/svs_common/svs_common/security.py`
- `packages/svs_common/svs_common/retrieval.py`
- `packages/svs_common/svs_common/opensearch_adapter.py`
- `tests/test_openai_compat_search.py`
- `tests/test_retrieval_profile_resolution.py`
- `tests/test_opensearch_adapter.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`

## Out Of Scope

- OR filters that contain range comparisons.
- Negation operators.
- Range comparisons over internal ExAIS filters such as `document_id` or
  `classification`.
- New database indexes, migrations, provider routing changes, API key behavior,
  tenant isolation changes, deployment work, or admin UI work.

## Acceptance Criteria

- [x] `openai_filter_to_internal` accepts `gt`, `gte`, `lt`, and `lte` filters
  over safe string or numeric file attributes.
- [x] Range filters reject sensitive keys, booleans, lists, objects, and
  internal ExAIS fields.
- [x] `and` filters can combine exact/list file-attribute filters with range
  filters.
- [x] Qdrant dense filters include numeric range prefilters without attempting
  unsafe string/date range prefilters.
- [x] OpenSearch sparse filters include range clauses for safe range filters.
- [x] Postgres sparse, embedding-profile selection, hydration, neighbor
  expansion, and parent-section expansion SQL all enforce range filters.
- [x] Existing W38 `eq`, `in`, and simple `or` behavior remains intact.
- [x] Docs state the supported range subset and still-unsupported operators.
- [x] Focused and broad non-integration verification passes.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_retrieval_profile_resolution.py tests/test_opensearch_adapter.py
73 passed

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
211 passed, 2 warnings

git diff --check
pass
```

## Notes

String range comparisons are intended for lexicographically sortable values such
as ISO dates or timestamps. Postgres hydration remains the authoritative
enforcement point after dense/sparse candidate retrieval.
