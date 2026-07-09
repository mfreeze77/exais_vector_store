# WAVE-096 OpenAI Admin API Key Route Parity

## Objective

Expose OpenAI-compatible organization admin API-key list, retrieve, and delete
aliases over the existing ExAIS scoped API-key store without leaking raw key
material, key hashes, scopes, or native security metadata.

## Evidence Anchors

Official OpenAI references checked on 2026-07-09:

- `GET /organization/admin_api_keys` lists organization admin API keys with
  `after`, `order`, `limit`, and `organization.admin_api_key` rows containing
  `id`, `name`, `redacted_value`, timestamps, and owner metadata.
  https://api.openai.com/v1/organization/admin_api_keys
- `GET /organization/admin_api_keys/{key_id}` retrieves one
  `organization.admin_api_key`.
  https://api.openai.com/v1/organization/admin_api_keys/{key_id}
- `DELETE /organization/admin_api_keys/{key_id}` returns
  `organization.admin_api_key.deleted` with `id` and `deleted: true`.
  https://api.openai.com/v1/organization/admin_api_keys/{key_id}

## Scope

- Add metadata-only OpenAI organization admin API-key formatting.
- Add `/v1/organization/admin_api_keys` list/retrieve/delete aliases gated by
  existing `api_keys:*` scopes.
- List/retrieve active keys only for the OpenAI-shaped aliases.
- Support OpenAI admin list controls: `limit`, `after`, and
  `order=asc|desc`.
- Add named OpenAPI response components for the new aliases.
- Add focused formatter, route, ordering, and leakage regressions.
- Update docs, ticket trail, and proof.

## Non-Goals

- Exposing OpenAI's admin-key create route. It mints a raw admin secret and
  needs an explicit ExAIS scope policy before it is safe to advertise.
- Returning raw keys, key hashes, scopes, max security levels, status, or native
  revoke metadata from OpenAI-shaped admin API-key responses.
- Changing bearer resolution, RLS policy, database schema, vector-store routes,
  retrieval, citations, indexing, provider routing, deployment, or admin UI.

## Acceptance

- [x] List alias returns OpenAI-shaped admin key list objects and passes
  `limit`, `after`, `order`, and active-status filtering to the scoped key
  store.
- [x] Retrieve alias returns one OpenAI-shaped active admin key or 404.
- [x] Delete alias reuses the scoped revoke path and returns only
  `organization.admin_api_key.deleted`, `id`, and `deleted`.
- [x] Formatter and route tests prove raw key material, hashes, scopes, and
  native security metadata are not exposed.
- [x] Generated `/openapi.json` advertises named admin API-key response
  components without native secret/security fields.
- [x] Focused, compile, broad non-integration, whitespace, and QC verification
  pass.

## Proof

Focused API-key route/OpenAPI verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_auth_scopes.py tests/test_openapi_contract.py
40 passed, 2 warnings in 5.01s
```

Compile proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass
```

Broad non-integration proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
408 passed, 2 warnings in 6.23s
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

Review notes:

- Scope stayed within OpenAI organization admin API-key metadata list,
  retrieve, delete, shared list ordering, focused tests, and docs.
- No raw key value, key hash, scopes, max security level, or native revoke
  metadata is exposed through the OpenAI-shaped admin payloads.
- OpenAI admin-key create was intentionally left out of scope because it would
  mint a raw admin secret and needs a separate ExAIS scope policy.
