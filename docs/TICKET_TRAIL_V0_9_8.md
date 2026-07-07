# Ticket Trail — v0.9.8 Worker Attempt Atomicity Gate

## Summary

v0.9.8 is a focused production-blocker patch opened by live multi-pass verification of v0.9.7. It fixes a retry/dedupe composition defect that could mark a job completed after a strict Qdrant outage even though the document had no vectors.

## Tickets

| Ticket | Title | Status | Gate |
|---|---|---:|---|
| W6-001 | Worker failed attempts roll back partial ingest rows via SAVEPOINT | Done | Integration |
| W6-002 | Exact dedupe requires fully indexed current version | Done | Unit + integration |
| W6-003 | Qdrant outage test drains retries and checks zero ghost rows | Done | Live Postgres |

## Subagent assignments

- **Worker/runtime subagent:** savepoint boundary and retry semantics.
- **Ingestion correctness subagent:** indexed-only dedupe query.
- **Integration-test subagent:** live retry-to-terminal proof and no-ghost-row assertion.
- **Release/documentation subagent:** patch report, validation notes, and packaging.

## Definition of done

- Local unit suite passes.
- Live Postgres integration suite passes.
- Qdrant-outage case reaches terminal failed state when Qdrant remains down.
- No failed-ingest title leaves document/version/chunk rows behind.
- Dedupe cannot match pending or partially indexed chunks.
