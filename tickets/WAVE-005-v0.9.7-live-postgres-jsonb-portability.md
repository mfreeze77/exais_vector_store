# WAVE-005 — v0.9.7 Live-Postgres JSONB + Portability Patch

## Trigger

The first real execution of the v0.9.6 integration suite verified RLS topology but uncovered a blocking SQLAlchemy 2 + psycopg3 JSONB adaptation failure: untyped `text()` statements could not bind raw Python dict/list values into JSONB columns.

## Owner lanes

| Lane | Owner | Status |
|---|---|---|
| JSONB data-plane sweep | backend-data | done |
| Runtime-role portability | infra-db | done |
| Integration-fixture honesty | qa-db | done |
| Worker live-Postgres proof | qa-platform | done |

## Tickets

### W5-001 JSONB parameter sweep

**Problem:** JSONB writes fail against live Postgres with `ProgrammingError: cannot adapt type 'dict'`.

**Implementation:**

- Introduce standardized JSON text serialization via `jsonb_param()`.
- Require `CAST(:param AS jsonb)` at JSONB SQL call sites.
- Sweep ingestion, retrieval, audit, usage, vector store, router, bakeoff, idempotency, model endpoint, file batch, and maintenance job writes.
- Ensure external-index payloads and API responses remain JSON objects where they are not DB binds.

**Acceptance:**

- Unit JSONB contract tests pass.
- Live integration clean-ingest test passes.
- Search/audit path no longer fails on metadata writes.

### W5-002 Managed-Postgres role portability

**Problem:** `ALTER ROLE ... NOSUPERUSER` can fail on managed Postgres/hardened owner roles even when setting the attribute to false.

**Implementation:**

- Remove unconditional SUPERUSER/BYPASSRLS attributes from create/alter paths.
- Verify `rolsuper=false` and `rolbypassrls=false` after setup.
- Fail clearly when an unsafe preexisting runtime role is supplied.

**Acceptance:**

- Compose topology still produces `svs_app` as NOSUPERUSER/NOBYPASSRLS.
- Managed-Postgres users can precreate the runtime role without the script attempting forbidden SUPERUSER mutations.

### W5-003 GUC-aware integration fixtures

**Problem:** Owner-DSN fixtures inserted rows without tenant/business GUCs, so the tests were only honest when the owner was a superuser/table-owner bypassing RLS.

**Implementation:**

- Add `_set_scope()` fixture helper.
- Scope cross-tenant test writes to `ten_other` / `biz_other`.
- Scope job cleanup with `svs.system_worker=true`.

**Acceptance:**

- Fixtures remain valid under FORCE RLS and non-superuser owners.

### W5-004 Worker live-Postgres proof

**Problem:** Green unit tests did not prove that enqueue → worker → document/chunk/audit/usage JSONB writes executed against live Postgres.

**Implementation:**

- Add `test_worker_completes_real_document_against_live_postgres`.
- Enqueue via `IngestionService.enqueue()` and SQLAlchemy runtime role.
- Run `svs_worker.process_once()`.
- Assert completed job, document row, chunk metadata, and usage event.

**Acceptance:**

- Compose-backed CI integration suite proves one successful real ingest and one strict-indexing Qdrant failure.
