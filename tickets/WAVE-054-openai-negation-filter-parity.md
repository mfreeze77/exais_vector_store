# WAVE-054 OpenAI Negation Filter Parity

## Status

Complete.

## Context

The official OpenAI vector-store search reference lists comparison filter
operators `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, and `nin`. ExAIS already
supports safe file-attribute `eq`, `in`, and range filters, but still rejects
OpenAI negation operators.

This ticket adds `ne` and `nin` for safe file attributes without changing API
key behavior, tenant isolation, migrations, indexing semantics, provider
routing, deployment behavior, or the existing simple `or` filter subset.

## Scope

- Map OpenAI `ne` filters on safe file attributes into an internal negation
  filter contract.
- Map OpenAI `nin` filters on safe file attributes into an internal not-in
  filter contract.
- Preserve sensitive-key and primitive-value validation.
- Enforce negation authoritatively in Postgres-backed profile selection,
  sparse search, hydration, and context expansion SQL.
- Push compatible candidate pruning into Qdrant and OpenSearch where the
  existing adapters already translate file-attribute filters.
- Update docs and proof.

## Out of Scope

- Negation on ExAIS internal filter keys such as `document_id` or
  `classification`.
- Compound `or` support for negation or range filters.
- New migrations, API-key behavior, tenant isolation, indexing semantics,
  provider routing, deployment changes, and admin UI behavior.

## Acceptance Criteria

- [x] `openai_filter_to_internal` accepts `ne` on safe file attributes.
- [x] `openai_filter_to_internal` accepts `nin` on safe file attributes.
- [x] Sensitive keys and invalid values remain rejected.
- [x] Negation filters are included in the file-attribute filter detector.
- [x] Postgres SQL helpers require the attribute key to exist and exclude
  matching values for `ne`/`nin`.
- [x] Qdrant/OpenSearch candidate filters include negation clauses.
- [x] Existing positive filters, citations, query planning, API keys, and
  vector-store route behavior are not otherwise changed.
- [x] Focused tests and full non-integration verification pass.

## Proof

- Official reference checked:
  `https://developers.openai.com/api/reference/resources/vector_stores/methods/search`
  lists comparison operators `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, and
  `nin` for vector-store search filters.
- Focused OpenAI/retrieval/adapter tests:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_retrieval_profile_resolution.py tests/test_opensearch_adapter.py`
  - Result: `103 passed`.
- Compile:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests`
  - Result: pass.
- Full non-integration:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration`
  - Result: `263 passed, 2 warnings`.
- Whitespace and stale-doc checks:
  `git diff --check`
  - Result: pass.
  `rg -n "[ \t]+$" ...`
  - Result: no matches in touched files.
  `rg -n "unsupported negation" docs packages/svs_common/svs_common tests tickets -S`
  - Result: no matches.
