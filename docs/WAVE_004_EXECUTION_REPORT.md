# WAVE-004 Execution Report — v0.9.6 Production Blockers

## Goal

Patch the four v1.0-blocking findings from the independent v0.9.5 audit without expanding scope into provider bakeoffs, multimodal research, or HA infrastructure.

## Findings closed

### W4-001 — Runtime DB role bypassed RLS

The shipped Docker Compose configuration no longer uses the Postgres image-created superuser as the runtime application user. `svs_owner` remains the init/migration role; `svs_app` is created by migration as `NOSUPERUSER NOBYPASSRLS` and receives only runtime grants.

### W4-002 — Dev mode and weak secrets lacked production guardrails

`Settings.validate_for_startup()` fails startup outside local/dev/test/CI when dev mode is enabled, API-key pepper is weak/default, CORS includes `*`, or HTTPS OpenSearch certificate verification is disabled.

### W4-003 — Stale Qdrant/OpenSearch vectors accumulated

Mutation paths now mark affected chunks `delete_queued` and enqueue `purge_stale_vectors`. The worker physically deletes Qdrant points/OpenSearch docs, then marks chunks `deleted`. This preserves transaction safety during version supersede while preventing unbounded stale vector growth.

### W4-004 — Security guarantees lacked live integration proof

A live Postgres integration test suite and GitHub Actions job were added. The suite checks runtime role properties, forced RLS on protected tables, direct cross-tenant SQL isolation through the app role, and strict failure behavior when Qdrant is unavailable.

## Validation

```text
compileall -f: passed
pytest -q -rs: 21 passed, 1 skipped
FastAPI routes: 45
svsctl help: ok
```

The skipped suite requires `SVS_RUN_INTEGRATION=1` and live Postgres. It is configured in CI.
