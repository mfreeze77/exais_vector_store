# WAVE-038 OpenAI Metadata Filter Parity

## Summary

Tighten OpenAI-compatible file-search metadata filtering. Current ExAIS
compatibility accepts `eq` and `and` filters, but current OpenAI file-search
docs show `type: "in"` filters and the retrieval guide describes compound
`and`/`or` filters. ExAIS should accept the practical OpenAI file-attribute
subset and apply it consistently across dense, sparse, hydration, and context
expansion paths.

## Background

Official OpenAI reference checked on 2026-07-08:

- Responses file-search metadata filtering examples use
  `{"type": "in", "key": "category", "value": ["blog", "announcement"]}`.
- The retrieval guide says attribute filtering uses comparison filters and
  compound filters combined with `and` and `or`.

ExAIS currently rejects list values and explicitly rejects `or` filters. That
means OpenAI SDK-shaped file-search requests can fail before retrieval even
when the backing vector-store files have safe attributes indexed.

## Scope

- Support OpenAI-style file-attribute `in` filters.
- Support simple compound `or` filters over safe file-attribute comparisons.
- Preserve existing `eq` and `and` behavior.
- Apply the normalized filters in Qdrant dense filters, OpenSearch sparse
  filters, Postgres sparse fallback, hydration, and context expansion SQL.
- Preserve sensitive file-attribute rejection.
- Preserve tenant/business/security filters and post-ACL checks.
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

- Range operators such as `gt`, `gte`, `lt`, or `lte`.
- Negation operators.
- OR over ExAIS internal filters such as `document_id` or `classification`.
- Database migrations, new indexes, provider routing changes, API key behavior,
  tenant isolation changes, or admin UI work.

## Acceptance Criteria

- [x] `openai_filter_to_internal` accepts file-attribute `in` filters and
  rejects invalid or sensitive `in` filters.
- [x] `openai_filter_to_internal` accepts simple `or` filters over safe
  file-attribute `eq`/`in` comparisons.
- [x] Dense Qdrant filters include a safe OR group for normalized file-attribute
  alternatives.
- [x] OpenSearch sparse filters include equivalent `should` clauses.
- [x] Postgres sparse, embedding-profile selection, hydration, neighbor
  expansion, and parent-section expansion SQL all enforce the normalized
  file-attribute alternatives.
- [x] Existing exact `eq` and `and` filter behavior remains intact.
- [x] Docs state the supported and still-unsupported OpenAI filter subset.
- [x] Focused and broad non-integration verification passes.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_retrieval_profile_resolution.py tests/test_opensearch_adapter.py
65 passed

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
203 passed, 2 warnings

git diff --check
pass
```

## Notes

This ticket intentionally handles the OpenAI-compatible file-attribute subset
that ExAIS can safely enforce today. Range filters require typed/date-aware
attribute comparisons and should remain a separate ticket.
