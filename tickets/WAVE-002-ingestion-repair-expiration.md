# WAVE-002 Ingestion Repair, Expiration, and Migration Tooling

## Goal
Make indexing recoverable and lifecycle-safe.

## Subagent assignments

- Worker agent: implement `reindex_chunks`, `expire_vector_stores`, and orphan cleanup jobs.
- Database agent: convert raw migrations to Alembic, add idempotency table.
- API agent: add idempotency-key handling to ingest and vector-store file APIs.
- QA agent: failure-injection tests for Qdrant/OpenSearch downtime.

## Acceptance criteria

- A failed dense/sparse write records status and can be repaired.
- Expired vector stores are marked expired and no longer searchable.
- Re-running an idempotent ingestion request does not duplicate work.
- Migration history is tracked and safely repeatable.
