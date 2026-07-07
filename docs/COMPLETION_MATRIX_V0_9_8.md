# Completion Matrix — v0.9.8

| Area | v0.9.7 state | v0.9.8 state |
|---|---|---|
| RLS/runtime roles | Live-verified by user under both topologies | Unchanged |
| JSONB portability | Live-verified by user | Unchanged |
| Worker outage retry | First attempt failed, retry could complete via ghost dedupe | Fixed with SAVEPOINT + retry-aware integration test |
| Failed-attempt partial DB rows | Could commit partial docs/chunks | Rolled back to SAVEPOINT |
| Dedupe safety | Content-hash match did not require indexed chunks | Requires indexed current version and all active chunks indexed |
| Qdrant outage proof | Test expected one-pass terminal failure | Drains to terminal max-attempt failure and checks no ghost rows |
| Build-container validation | 23 passed, 1 skipped | 25 passed, 1 skipped |
| Live validation | Required | Still required in target environment |

## Remaining v1.0 work

- Run v0.9.8 live integration suite in CI/topology A and topology B.
- Run provider integration tests for real OpenAI/RunPod/TEI/Infinity endpoints.
- Run backup/restore drills on the first micro-production cell.
- Run corpus-scale ingestion and retrieval load tests.
