# WAVE-125 Caller Jurisdiction Metadata And Per-User API Keys

Status: Proposed  
Priority: P1  
Base: `main @ 3c2aa02` (Plan jurisdiction knowledge package lifecycle)  
Consumer: StateCivics `state-civics-ai` tickets KS-569 (jurisdiction-aware tool
scoping) and KS-570 (assistant bridge to exais experts)

## Summary

Give a caller product two things it needs to route its users to the right
expert and to account for what each human does: expert profiles that declare
the jurisdiction and corpus they answer for, and API keys that can be bound to
a caller-provisioned user so ExAIS sessions, usage events, audit events, and
rate limits are attributed to that person natively. StateCivics is the first
consumer; the contract must stay generic.

## Background

StateCivics keeps a data-only registry (`config/jurisdictions.json`) that maps
each civic jurisdiction key (`ks:state:kansas`, `ks:city:topeka`, ...) to the
ExAIS experts a granted workspace may ask. A jurisdiction may list several
experts (statutes, court decisions, municipal code, meetings) and the caller's
model chooses among them by slug; the caller's grant fence decides which
jurisdictions are reachable. Today the operator fills that registry by hand
because `ExpertProfile` (`packages/svs_common/svs_common/schemas.py:893`)
carries `label`, `description`, and vector-store bindings but no jurisdiction
or corpus field, so the caller cannot verify its assignment against
`GET /v1/experts`.

For accounting, the caller currently plans to use one cell key and pass
`external_user_id` and `conversation_id` on every expert message. Expert
sessions are already scoped by `api_key_id` plus `external_user_id`
(`packages/svs_common/svs_common/expert_sessions.py:105-201`), and
`usage_events.user_id` is filled from the principal
(`db/migrations/001_initial.sql:266`). The `api_keys` table has a `user_id`
column (`001_initial.sql:56`) and `resolve_api_key_principal` loads it into
the principal (`auth.py:211-250`), but:

- `POST /api/v1/admin/api-keys` (`apps/api/svs_api/main.py:2079`) accepts only
  `label`, `scopes`, `max_security_level`, `expires_at`; `create_api_key`
  binds `user_id` from the creating principal, so a caller cannot mint a key
  for one of its people.
- There is no route to provision or deactivate a user; `users` is keyed by
  `(tenant_id, email)` with no external identifier for a caller's own ids.
- `GET /api/v1/admin/usage` has no per-user or per-key filter or summary.

WAVE-124 packages are the natural source of jurisdiction and corpus metadata
because a package already describes one jurisdiction corpus end to end.

## Scope

### A. Expert jurisdiction and corpus metadata

- Add optional `jurisdiction_key` (string, caller-defined key such as
  `ks:city:topeka`) and `corpus` (enum: `statutes`, `court_decisions`,
  `municipal_code`, `administrative_regulations`, `legislative_materials`,
  `meeting_records`, `other`) to the expert profile registry, populated from
  the WAVE-124 `package.yaml` for compiled experts and settable for existing
  hand-registered experts.
- Surface both fields on `ExpertProfile` and accept
  `GET /v1/experts?jurisdiction_key=...&corpus=...` filters. Filtering never
  widens visibility; tenant, instance, principal, and binding checks apply
  first.
- Document in `docs/CALLER_AGENT_INTEGRATION.md` that callers should verify
  their local expert assignments against these fields and refuse to expose an
  expert whose declared jurisdiction does not match.

### B. Caller-provisioned users

- Add `users.external_id` (nullable text) with a unique index on
  `(tenant_id, external_id)`; keep the existing email uniqueness.
- Add admin routes, all requiring `api_keys:write` (or a new `users:write`
  scope granted to the cell admin key), instance rate-limited, idempotent on
  `(tenant_id, external_id)`:
  - `POST /api/v1/admin/users` with `external_id`, optional `email`,
    `display_name`; returns the ExAIS `user_id`.
  - `GET /api/v1/admin/users?external_id=...` and paged listing.
  - `POST /api/v1/admin/users/{user_id}/deactivate`, which also revokes that
    user's active API keys and blocks new sessions while preserving audit
    history.

### C. User-bound API keys

- Extend `POST /api/v1/admin/api-keys` with optional `user_id`. Rules: the
  user must belong to the principal's tenant and business instance; requested
  scopes must be a subset of the creating principal's scopes and default to
  `retrieval:read`; `max_security_level` may not exceed the creator's; the raw
  key is returned exactly once.
- `GET /api/v1/admin/api-keys?user_id=...` filter; existing delete route
  revokes.
- A user-bound key cannot call admin routes unless explicitly scoped, cannot
  see sessions or memory created under a different `user_id`, and cannot
  widen its own scopes.

### D. Attribution and reporting

- Confirm and test that expert messages, retrieval runs, usage events, audit
  events, and rate-limit buckets record `api_key_id` and `user_id` from the
  principal for user-bound keys; add whichever of those columns is missing
  (`usage_events` has no `api_key_id` today).
- Add `GET /api/v1/admin/usage?user_id=...&api_key_id=...` filters and
  `GET /api/v1/admin/usage/summary?group_by=user|api_key&from=&to=` returning
  quantity and `cost_estimate_usd` per group.
- Keep `external_user_id` on expert messages as the caller-side correlation
  id; document that a user-bound key whose ExAIS user has
  `external_id == external_user_id` is the expected pattern, and reject a
  message whose `external_user_id` disagrees with the bound user's
  `external_id` when both are present.

## Out Of Scope

- JWT or JWKS verification of caller-issued tokens.
- Per-key or per-user vector-store grants (the WAVE-116 boundary stands: store
  visibility is a tool-configuration boundary, not a hard auth boundary).
- A standalone MCP server package.
- Changing expert retrieval, citation, memory, or model-policy behavior.
- Cross-tenant user identity or organization tenancy.

## Deliverables

- Migration adding `users.external_id`, expert metadata storage, and
  `usage_events.api_key_id` (if absent), with RLS policies reviewed.
- Schema updates: `ExpertProfile`, admin user request and response models,
  extended API key create request, usage summary response.
- Routes and handlers in `apps/api/svs_api/main.py` with scope and rate-limit
  enforcement.
- `docs/API.md`, `docs/CALLER_AGENT_INTEGRATION.md`, and a regenerated
  `contracts/openapi.json` (currently stale against `docs/API.md`).
- Tests: contract suites for the new routes, an isolation test proving a
  user-bound key cannot read another user's sessions or memory, an
  attribution test proving usage and audit rows carry the bound user and key,
  and a filter test proving `jurisdiction_key` never widens visibility.
- `scripts/release/cell-access-proof.py` extended to mint a user-bound key,
  send one expert message, and show the usage row attributed to that user.

## Acceptance Criteria

- `GET /v1/experts?jurisdiction_key=ks:city:topeka` returns only experts
  declared for that key that the principal could already see, each with
  `jurisdiction_key` and `corpus` populated.
- A cell admin key can create a user by `external_id`, mint a
  `retrieval:read` key bound to it, and the key's first expert message
  produces a session, a usage event, and an audit event all carrying that
  user's `user_id` and the key's `api_key_id`.
- The same user-bound key receives 403 on every admin route and cannot list,
  fork, or read memory for a session created under another user.
- Deactivating the user revokes the key (subsequent calls 401) and preserves
  the session and usage history.
- `GET /api/v1/admin/usage/summary?group_by=user` returns one row per user
  with quantity and estimated cost for the window.
- `contracts/openapi.json` matches the live route list.

## Dependencies

- WAVE-123 (expert routes and sessions).
- WAVE-124 (packages declare jurisdiction and corpus; source of metadata).
- WAVE-028 (API key lifecycle and scope parity).

## Verification

- Contract and non-integration suites inside the released image, plus the new
  tests named above.
- `python scripts/release/cell-access-proof.py` against a local cell showing
  the per-user attribution path.
- Regenerate and diff `contracts/openapi.json`.

## Notes

- Code anchors: `auth.py` `resolve_api_key_principal` and `create_api_key`
  (INSERT at line ~114); `main.py:2079-2096` admin key routes;
  `main.py:2047` usage route; `schemas.py:893` `ExpertProfile`;
  `expert_sessions.py:54-201` session scope by `api_key_id` and
  `external_user_id`; `db/migrations/001_initial.sql` `users`, `api_keys`,
  `usage_events`.
- The caller's registry shape this serves (StateCivics
  `config/jurisdictions.json`, schema `jurisdictions.v1`): per jurisdiction
  key, a list of `{slug, label, corpus, expert_id, status}` plus
  `default_expert`. The caller exposes an expert only when `expert_id` is
  set and `status` is `active`; with Scope A it can also verify that the
  profile's `jurisdiction_key` matches.
- Per-user keys are optional for callers. A caller may keep one cell key and
  rely on `external_user_id`; Scope D must not make that path worse.
