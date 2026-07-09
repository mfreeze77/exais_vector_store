# WAVE-031 OpenAI Tenant Leakage Proof

## Summary

Expand `SVS-014` cross-tenant leakage proof across the OpenAI-compatible
surfaces that resolve public IDs. Existing live integration proves FORCE RLS on
protected tables and plain-SQL tenant isolation. This ticket adds focused,
non-integration regression proof that OpenAI Responses, files, vector stores,
and vector-store file helpers always resolve by principal tenant/business scope.

## Background

OpenAI-compatible IDs such as `resp_*`, `file_*`, `vs_*`, vector-store file IDs,
and file-batch IDs can be guessed or reused across tenants. Every lookup,
cursor resolution, and mutation must fail closed under the caller principal's
tenant and business instance.

## Scope

- Pin `/v1/responses` stored-response lookup/delete scoping.
- Pin `/v1/files` OpenAI file lookup scoping.
- Pin vector-store repository list/get/delete scoping.
- Pin vector-store file row/list cursor scoping, including file-batch filters.
- Update `SVS-014` tracker status with focused proof.

## Out Of Scope

- New RLS policy migrations.
- Live API smoke tests that require a running Postgres/Qdrant cell.
- Changes to API-key resolution behavior.
- Provider, retrieval ranking, ingestion, or admin UI behavior changes.

## Acceptance Criteria

- [x] Stored Responses rows are selected and deleted only with
  tenant/business predicates from the caller principal.
- [x] OpenAI file lookup and vector-store file lookup/list helpers include
  tenant/business predicates even when resolving public `file_*` IDs or cursors.
- [x] Vector-store repository list/get/delete paths include tenant/business
  predicates on reads and mutations.
- [x] Cross-scope stored-response misses raise 404 rather than returning a row.
- [x] Focused tenant-leakage tests and broad non-integration verification pass.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_tenant_leakage_guards.py tests/test_vector_store_delete.py tests/test_auth_scopes.py tests/test_openai_responses_routes.py
19 passed, 2 warnings in 3.12s

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
<exit 0>

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
172 passed, 2 warnings in 3.72s

git diff --check
<exit 0>
```

## Notes

This ticket is proof-only. It does not alter database schema, RLS policy text,
or API-key behavior.
