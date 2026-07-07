# WAVE-003 Router, Bakeoff, and Fleet Control Plane

## Goal
Move from static YAML profile selection to the intelligent vectorization router and micro-production fleet-management target.

## Subagent assignments

- Router agent: preview endpoint, model endpoint registry, ingestion plan persistence.
- Eval agent: bakeoff runner and golden-query metrics.
- Control-plane agent: `svsctl`, instance-agent backup/rollback, blue/green upgrade records.
- UI agent: frontend mode preview and per-instance model/security settings.

## Acceptance criteria

- `POST /api/v1/ingestion/preview` returns the full parser/chunker/model/retrieval/security plan.
- Model endpoint registration APIs populate persistent tables.
- Bakeoff runner compares configured embedding/reranker candidates.
- Fleet upgrade supports canary, rollback, and signed image/version metadata.
