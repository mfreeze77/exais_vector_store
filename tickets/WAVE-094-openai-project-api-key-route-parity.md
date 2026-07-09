# WAVE-094 OpenAI Project API Key Route Parity

## Objective

Expose OpenAI-compatible project API-key list, retrieve, and delete aliases over
the existing ExAIS scoped API-key store without leaking raw key material, key
hashes, scopes, or native security metadata.

## Evidence Anchors

Official OpenAI OpenAPI references checked on 2026-07-09:

- `GET /organization/projects/{project_id}/api_keys` lists project API keys
  with `limit` default 20, `after`, and `organization.project.api_key` objects
  containing `redacted_value`, `name`, timestamps, id, and owner.
  https://api.openai.com/v1/organization/projects/{project_id}/api_keys
- `GET /organization/projects/{project_id}/api_keys/{api_key_id}` retrieves one
  `organization.project.api_key`.
  https://api.openai.com/v1/organization/projects/{project_id}/api_keys/{api_key_id}
- `DELETE /organization/projects/{project_id}/api_keys/{api_key_id}` returns
  `organization.project.api_key.deleted` with `id` and `deleted: true`.
  https://api.openai.com/v1/organization/projects/{project_id}/api_keys/{api_key_id}

## Scope

- Add metadata-only OpenAI project API-key formatting.
- Add tenant/business-scoped API-key retrieve support.
- Add `/v1/organization/projects/{project_id}/api_keys` list/retrieve/delete
  aliases gated by the existing `api_keys:*` scopes.
- Require OpenAI `project_id` to match the current ExAIS business instance ID.
- List/retrieve active keys only for the OpenAI-shaped aliases.
- Add named OpenAPI response components for the new aliases.
- Add focused route and leakage regressions.
- Update docs, ticket trail, and proof.

## Non-Goals

- Creating raw OpenAI admin API keys or a separate admin-key credential system.
- Returning raw keys, key hashes, scopes, max security levels, status, or native
  revoke metadata from OpenAI-shaped project API-key responses.
- Changing bearer resolution, RLS policy, database schema, vector-store routes,
  retrieval, citations, indexing, provider routing, deployment, or admin UI.

## Acceptance

- [x] List alias returns OpenAI-shaped list objects and passes `limit`, `after`,
  and active-status filtering to the scoped key store.
- [x] Retrieve alias returns one OpenAI-shaped active key or 404.
- [x] Delete alias reuses the scoped revoke path and returns only
  `organization.project.api_key.deleted`, `id`, and `deleted`.
- [x] Project mismatch fails closed with 404 before key lookup.
- [x] Formatter and route tests prove raw key material and hashes are not
  exposed.
- [x] Generated `/openapi.json` advertises named project API-key response
  components without native secret/security fields.
- [x] Focused, compile, broad non-integration, and whitespace verification pass.

## Proof

Focused API-key route/OpenAPI verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_auth_scopes.py tests/test_openapi_contract.py
32 passed, 2 warnings in 4.74s
```

Compile proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass
```

Broad non-integration proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
400 passed, 2 warnings in 6.10s
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
- `tickets/WAVE-094-openai-project-api-key-route-parity.md`

Evidence reviewed:
- `packages/svs_common/svs_common/auth.py`
- `apps/api/svs_api/main.py`
- `tests/test_auth_scopes.py`
- `tests/test_openapi_contract.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`
- `tickets/README.md`
- Focused API-key route/OpenAPI proof: `32 passed, 2 warnings in 4.74s`
- Compile proof: passed
- Broad non-integration proof: `400 passed, 2 warnings in 6.10s`
- Whitespace proof: `git diff --check` passed

Acceptance criteria:
- [pass] List alias returns OpenAI-shaped list objects and passes `limit`,
  `after`, and active-status filtering to the scoped key store.
- [pass] Retrieve alias returns one OpenAI-shaped active key or 404.
- [pass] Delete alias reuses the scoped revoke path and returns only
  `organization.project.api_key.deleted`, `id`, and `deleted`.
- [pass] Project mismatch fails closed with 404 before key lookup.
- [pass] Formatter and route tests prove raw key material and hashes are not
  exposed.
- [pass] Generated `/openapi.json` advertises named project API-key response
  components without native secret/security fields.
- [pass] Focused, compile, broad non-integration, and whitespace verification
  passed.

Findings:
- None.

Required fixes before next ticket:
- None.
