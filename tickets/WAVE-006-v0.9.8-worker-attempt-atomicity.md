# WAVE-006 — v0.9.8 Worker Attempt Atomicity + Indexed-Only Dedupe

## Trigger

Live multi-pass Postgres verification of v0.9.7 found that a strict Qdrant outage could fail attempt 1, leave partial document/version/chunk rows committed, and then complete attempt 2 through content-hash dedupe even though no vectors existed. The root cause was that worker retry metadata and ingest side effects shared the same outer transaction.

## W6-001 — Failed job attempts must not persist partial ingest rows

**Owner:** Worker/runtime subagent
**Severity:** v1.0 blocker
**Status:** Implemented in v0.9.8

### Implementation

- Wrapped each worker job attempt in `with db.begin_nested():`.
- The outer transaction still owns the job claim, lock, attempt increment, status update, and retry accounting.
- The SAVEPOINT owns document ingestion, version creation, chunk creation, embedding rows, usage writes, and maintenance job side effects for the attempted job.
- On strict indexing failure, SQLAlchemy rolls back to the SAVEPOINT before the worker writes `queued` or `failed` status to the job row.

### Acceptance criteria

- A failed worker attempt preserves `attempts` and retry state.
- A failed worker attempt does not leave visible `documents`, `document_versions`, `chunks`, or `usage_events` for the failed ingest.
- Retrying while Qdrant remains down reaches terminal `failed`, not `completed`.

## W6-002 — Dedupe must only target fully indexed current versions

**Owner:** Ingestion correctness subagent
**Severity:** v1.0 blocker
**Status:** Implemented in v0.9.8

### Implementation

`_find_exact_duplicate()` now requires all of the following before returning a dedupe hit:

- `documents.status = 'active'`
- current `document_versions.status = 'indexed'`
- at least one active chunk for the current version with both dense and sparse statuses indexed
- no active current-version chunk with either dense or sparse status other than indexed

### Acceptance criteria

- Partial, pending, failed, or delete-queued chunks cannot satisfy exact-dedupe.
- A legitimate fully indexed duplicate still returns `deduplicated`.

## W6-003 — Retry-aware Qdrant outage integration proof

**Owner:** Test/integration subagent
**Severity:** v1.0 gate
**Status:** Implemented in v0.9.8

### Implementation

- Updated the live Postgres Qdrant-outage test to drain the worker until terminal state instead of assuming `max_attempts = 1`.
- The test now asserts `attempts == max_attempts` at terminal failure.
- The test now asserts zero document/version/chunk rows survive for the failed title.

### Acceptance criteria

Run against a migrated live Postgres instance with Qdrant unavailable:

```bash
SVS_RUN_INTEGRATION=1 pytest -q tests/integration
```

Expected result:

```text
all integration tests pass
Qdrant outage job status = failed
attempts == max_attempts
no ghost documents for failed title
```

## Release gate

v0.9.8 is fit to supersede v0.9.7 only after the live integration suite passes under both supported Postgres topologies:

1. compose-style owner/bootstrap topology
2. hardened or managed-style non-superuser owner topology
