# Completion Matrix — v0.9.8

| Area | v0.9.7 state | v0.9.8 state |
|---|---|---|
| RLS/runtime roles | Live-verified by user under both topologies | Unchanged |
| JSONB portability | Live-verified by user | Unchanged |
| Worker outage retry | First attempt failed, retry could complete via ghost dedupe | Fixed with SAVEPOINT + retry-aware integration test |
| Failed-attempt partial DB rows | Could commit partial docs/chunks | Rolled back to SAVEPOINT |
| Dedupe safety | Content-hash match did not require indexed chunks | Requires indexed current version and all active chunks indexed |
| Qdrant outage proof | Test expected one-pass terminal failure | Drains to terminal max-attempt failure and checks no ghost rows |
| Build-container validation | 23 passed, 1 skipped | Historical v0.9.8 report: 25 passed, 1 skipped |
| Local Docker validation | Not part of v0.9.8 patch gate | Wave 009: registry-pulled cell healthy, 46 non-integration tests passed inside pulled API image, restore and repair-all proofs passed |
| Live validation | Required | Target VPS/Docker Hub validation still required; local Docker proof does not claim external deployment |

## Remaining v1.0 work

- Run v0.9.8 live integration suite in CI/topology A and topology B.
- Run provider integration tests for real OpenAI/RunPod/TEI/Infinity endpoints.
- Run backup/restore drills on the first external micro-production cell. Local
  restore drill now passes under Wave 009.
- Run corpus-scale ingestion and retrieval load tests.
- Push the versioned image set to Docker Hub or another external registry after
  operator credentials are available.
