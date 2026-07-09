# WAVE-078 API Key Expiration Create

## Summary

Allow operators to create time-bound API keys through the existing admin
lifecycle route by accepting a future `expires_at` Unix timestamp and storing it
in the existing `api_keys.expires_at` column.

## Background

The auth resolver already fails closed unless an API key is active and
unexpired, and API-key list/revoke metadata already exposes `expires_at` when
present. The creation path did not let an operator set that field, leaving
time-bound keys available in storage but unreachable through the API.

## Scope

- Extend `create_api_key(...)` to accept an optional future `expires_at` epoch
  second.
- Store accepted values in `api_keys.expires_at`.
- Return `expires_at` in the one-time create response when supplied.
- Reject past/current expiration values before inserting a key.
- Pass `expires_at` through `POST /api/v1/admin/api-keys`.
- Document the lifecycle behavior and update proof.

## Code Anchors

- `packages/svs_common/svs_common/auth.py`
- `apps/api/svs_api/main.py`
- `tests/test_auth_scopes.py`
- `docs/API.md`
- `docs/OPENAI_COMPAT.md`
- `docs/TICKET_TRAIL.md`

## Out Of Scope

- Changing bearer key format or hashing.
- Changing scope semantics, tenant/business resolution, RLS policies, route
  rate limits, OpenAI vector-store behavior, retrieval, citations, or indexing.
- Adding key rotation, PATCH/update, or pagination changes.

## Acceptance Criteria

- [x] API-key create accepts a future `expires_at` Unix timestamp.
- [x] Accepted expirations are stored in `api_keys.expires_at` and returned in
  the create response.
- [x] Past/current expirations fail with `422` before insert.
- [x] Route tests prove the admin endpoint passes the value through and commits
  successful creation.
- [x] Existing inactive/revoked/expired-key resolution behavior remains covered.
- [x] Focused and broad non-integration verification passes.

## Verification

Focused auth/rate-limit verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_auth_scopes.py tests/test_openai_rate_limits.py
21 passed, 2 warnings
```

Compile verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
pass
```

Broad non-integration verification:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
371 passed, 2 warnings
```

Whitespace verification:

```text
git diff --check
pass
```
