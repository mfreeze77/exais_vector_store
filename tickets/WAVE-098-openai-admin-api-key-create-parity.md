# WAVE-098 OpenAI Admin API Key Create Parity

## Objective

Expose `POST /v1/organization/admin_api_keys` so OpenAI-compatible clients can
create organization admin API keys while ExAIS preserves its scoped API-key
security model.

## OpenAI reference

Official OpenAI reference checked on 2026-07-09:

- `POST /organization/admin_api_keys` creates an organization admin API key
  from required `name` and optional `expires_in_seconds` (`1..31536000`) and
  returns an `organization.admin_api_key` object with a one-time raw `value`.
  https://api.openai.com/v1/organization/admin_api_keys

## Scope

- Add typed `OpenAIAdminApiKeyCreateRequest` and
  `OpenAIAdminApiKeyCreateResponse` schemas.
- Add `POST /v1/organization/admin_api_keys` gated by `api_keys:write`.
- Map `expires_in_seconds` to the existing ExAIS `expires_at` storage.
- Return the raw key only as OpenAI create-time `value`.
- Prevent privilege escalation by inheriting the caller's current ExAIS scopes
  and max security level; do not accept scope or security-level fields on the
  OpenAI-shaped request.
- Update OpenAPI contract coverage and docs.

## Non-goals

- Adding project API-key create aliases.
- Changing bearer resolution, native API-key hashing, database schema,
  tenant/RLS policy, vector-store routes, retrieval, citations, indexing,
  provider routing, deployment, or admin UI.
- Returning raw key material from list/retrieve/delete routes.
- Adding OpenAI role/service-account management.

## Acceptance criteria

- [x] `POST /v1/organization/admin_api_keys` accepts `name` and optional
  bounded `expires_in_seconds`.
- [x] Created keys inherit the caller's current ExAIS scopes and max security
  level.
- [x] Create responses include OpenAI's `value` exactly on create and do not
  expose `api_key`, key hash, scopes, or max security level.
- [x] List/retrieve schemas remain metadata-only and do not include `value`.
- [x] Generated `/openapi.json` advertises named create request/response
  components.
- [x] Focused, compile, broad non-integration, whitespace, and QC verification
  pass.

## Changed files

- `apps/api/svs_api/main.py`
- `packages/svs_common/svs_common/auth.py`
- `packages/svs_common/svs_common/schemas.py`
- `tests/test_auth_scopes.py`
- `tests/test_openapi_contract.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`
- `tickets/README.md`
- `tickets/WAVE-098-openai-admin-api-key-create-parity.md`

## Verification

- Focused API-key route/OpenAPI verification:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_auth_scopes.py tests/test_openapi_contract.py`
  - Result: `42 passed, 2 warnings in 4.61s`
- Compile:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests`
  - Result: pass
- Broad non-integration:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration`
  - Result: `411 passed, 2 warnings in 6.52s`
- Whitespace:
  `git diff --check`
  - Result: pass
