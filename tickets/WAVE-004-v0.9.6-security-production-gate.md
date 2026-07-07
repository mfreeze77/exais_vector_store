# WAVE-004 — v0.9.6 RLS Runtime + v1.0 Proof Gates

## Context
Independent review of v0.9.5 found the core wave implementation was real, but four production blockers remained. v0.9.6 patches the two immediate release blockers and wires code/test coverage for the v1.0 gate.

## Tickets

### W4-001 — Runtime role must not bypass RLS
- **Severity:** release blocker
- **Finding:** Docker Compose used `POSTGRES_USER` as the runtime `DATABASE_URL`; the official Postgres image creates that user as superuser, which bypasses RLS even when `FORCE ROW LEVEL SECURITY` is enabled.
- **Implementation:** `POSTGRES_USER=svs_owner` is migration/admin only. Runtime API/worker connections use `svs_app`, created as `NOSUPERUSER NOBYPASSRLS`. Migration scripts grant table/function privileges to the runtime role.
- **Acceptance:** live integration test checks `rolsuper=false`, `rolbypassrls=false`, and every protected table has `relforcerowsecurity=true`.

### W4-002 — Dev mode / default pepper startup guard
- **Severity:** release blocker
- **Finding:** dev mode allowed unauthenticated header-selected principals with wildcard scopes and default API-key pepper outside local mode.
- **Implementation:** `Settings.validate_for_startup()` fails startup when `SVS_ENV` is non-local and dev mode is enabled, the pepper is default/weak, CORS includes `*`, or HTTPS OpenSearch cert verification is disabled.
- **Acceptance:** unit tests cover production rejection and local allowance.

### W4-003 — Stale external vectors must be physically removed
- **Severity:** v1.0 blocker
- **Finding:** superseded/deleted/expired chunks were inactive in Postgres but stale Qdrant/OpenSearch entries remained in external indexes, burning top-k candidates and growing storage.
- **Implementation:** Mutating paths first mark chunks inactive and set dense/sparse status to `delete_queued`, then enqueue a `purge_stale_vectors` worker job. The worker uses `IndexCleanup` to delete Qdrant points grouped by collection and OpenSearch docs by query, scoped by old `document_version_id`, `document_id`, or `vector_store_id`. This avoids deleting the new live version if an ingest transaction rolls back.
- **Acceptance:** unit tests verify dense point grouping/sparse delete scope; worker path performs physical purge after commit; integration test plan covers expiration/supersede on live stores.

### W4-004 — Integration proof for security guarantees
- **Severity:** v1.0 blocker
- **Finding:** v0.9.5 security behavior was implemented but not proven with live Postgres/runtime-role CI.
- **Implementation:** CI now has a `postgres-rls-integration` job that brings up Postgres, runs migrations, and executes integration tests for runtime role, FORCE RLS, cross-tenant SQL isolation, and strict worker failure behavior.
- **Acceptance:** GitHub Actions must pass the unit suite and the live Postgres integration job before v1.0.

## Exit Criteria
- `pytest -q` passes locally.
- `tests/integration` passes under `SVS_RUN_INTEGRATION=1` with live Postgres.
- Docker cell starts with `DATABASE_URL` pointing to `svs_app`, never `svs_owner`.
- Production-like startup fails if `SVS_DEV_MODE=true` or `SVS_API_KEY_PEPPER=change-me-in-prod`.
