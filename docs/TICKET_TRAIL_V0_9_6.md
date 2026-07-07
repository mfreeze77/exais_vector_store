# Ticket Trail — v0.9.6 Security Production Gate

v0.9.6 executes WAVE-004, the blocker patch opened from the independent v0.9.5 audit.

## W4-001 — Runtime DB role must not bypass RLS

**Status:** implemented; live CI proof wired.

- Compose bootstrap role is now `svs_owner`.
- Runtime app/worker role is now `svs_app`.
- `svs_app` is created as `NOSUPERUSER NOBYPASSRLS`.
- Runtime `DATABASE_URL` points to `svs_app`.
- Migration/admin DSNs remain owner-only.
- Integration test checks `rolsuper=false`, `rolbypassrls=false`, and `relforcerowsecurity=true`.

## W4-002 — Production startup guard

**Status:** implemented; unit tested.

- Non-local `SVS_DEV_MODE=true` fails startup.
- Default/weak `SVS_API_KEY_PEPPER` fails startup outside local/dev/test/ci.
- Wildcard CORS fails startup outside local/dev/test/ci.
- Disabled HTTPS OpenSearch cert verification fails startup outside local/dev/test/ci.
- API and worker call guardrails on startup/import path.

## W4-003 — Stale vector cleanup

**Status:** implemented; unit tested; live-store proof remains deployment gate.

- Superseded document versions mark old chunks `delete_queued`.
- Vector-store file delete queues cleanup by document.
- Vector-store delete / expiration queues cleanup by vector store.
- Worker handles `purge_stale_vectors` jobs.
- Cleanup groups Qdrant point deletes by collection and deletes OpenSearch sparse docs by scoped query.

## W4-004 — Security integration proof

**Status:** CI job wired; skipped offline unless `SVS_RUN_INTEGRATION=1`.

- GitHub Actions starts Compose Postgres.
- Runs migrations against owner role.
- Executes integration tests against `svs_app` runtime role.
- Verifies runtime role, forced RLS, cross-tenant SQL isolation, and strict worker failure semantics.

## Exit status

Local/offline validation:

```text
compileall: passed
pytest -q -rs: 21 passed, 1 skipped
FastAPI routes: 45
OpenAPI paths: 34
```

The skipped test is the live Postgres integration suite, which is configured in CI and requires Docker/Postgres.
