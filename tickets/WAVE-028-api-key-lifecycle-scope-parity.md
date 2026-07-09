# WAVE-028 API Key Lifecycle Scope Parity

## Summary

Harden the native API-key lifecycle so scoped keys can be created, listed as
metadata, and revoked without exposing hashes or raw secret material after the
one-time create response. This closes the `SVS-011` scaffold gap called out by
the tracker while preserving existing bearer-key resolution semantics.

Repo references checked on 2026-07-08:

- `docs/TICKET_TRAIL.md`: SVS-011 API key hashing/scopes/resolution is
  scaffolded.
- `docs/planning-specs/FULL_REPO_SPEC.md`: API keys are scoped and hashed at
  rest; API-key routes should support create, list metadata, and revoke.
- `packages/svs_common/svs_common/auth.py`: bearer-key lookup already hashes
  presented keys, sets RLS lookup context, checks active/unexpired status, and
  updates `last_used_at`.

## Tickets

| Ticket | Status | Type | Outcome |
|---|---|---|---|
| W28-001 | Complete | Implementation/Test | Add metadata list/revoke helpers and routes, fix default scope reporting, and prove no key hash/raw secret leakage in metadata responses. |

## Code Anchors

- `packages/svs_common/svs_common/auth.py`
- `apps/api/svs_api/main.py`
- `tests/test_auth_scopes.py`
- `docs/API.md`
- `docs/TICKET_TRAIL.md`

## W28-001 Acceptance Criteria

- [x] `create_api_key` stores and returns the same effective scope list,
  including the default scope path.
- [x] API-key metadata payloads include id, label, scopes, max security level,
  status, and timestamps, but never include `api_key` or `key_hash`.
- [x] Admin list route returns tenant/business-scoped API-key metadata under a
  read/write API-key scope check.
- [x] Admin revoke route marks a key revoked, fails closed on missing keys, and
  makes future bearer resolution fail through the existing `status='active'`
  lookup.
- [x] Focused tests cover default scope reporting, metadata redaction,
  list/revoke SQL scoping, route scope checks, and existing scope behavior.

## Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -q packages apps tests
exit 0

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_auth_scopes.py tests/test_config_guardrails.py tests/test_openai_files.py tests/test_openai_vector_store_object.py tests/test_openai_compat_search.py
61 passed, 2 warnings in 3.47s

docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
159 passed, 2 warnings in 3.62s

git diff --check
exit 0
```

## Notes

This ticket does not change API-key hashing, pepper requirements, RLS policies,
bearer token parsing, provider API keys, model-provider credentials, or
OpenAI-compatible vector-store routes.
