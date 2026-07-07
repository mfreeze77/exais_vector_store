# Completion Matrix — v0.9.6 Production Gate

| Area | v0.9.5 status | v0.9.6 status | Notes |
|---|---:|---:|---|
| App runtime role protected by RLS | blocked | implemented | Runtime `svs_app` is non-superuser / non-bypassrls. |
| Compose defaults preserve tenant isolation | blocked | implemented | `POSTGRES_USER` is owner-only; app DSN uses `svs_app`. |
| Production dev-mode guard | blocked | implemented | Fail-closed outside local/dev/test/ci. |
| Default API-key pepper guard | blocked | implemented | Weak/default pepper rejected in production-like envs. |
| TLS verification guard | partial | implemented | HTTPS OpenSearch cannot disable cert verification outside local. |
| Stale Qdrant vector cleanup | blocked | implemented | Cleanup jobs delete Qdrant points by point ID grouped by collection. |
| Stale OpenSearch sparse cleanup | partial | implemented | Delete-by-query scoped to document/vector-store/version. |
| Superseded-version cleanup | blocked | implemented | Old chunks marked `delete_queued`, then worker purges. |
| Expiration cleanup | partial | implemented | Expiration/deletion paths queue external index purge. |
| Live RLS proof | absent | CI-wired | Requires `SVS_RUN_INTEGRATION=1` and Compose Postgres. |
| Unit/local validation | 16 tests | 21 tests | 21 passed, 1 skipped offline integration gate. |

## Remaining v1.0 deployment gates

- Run full Compose stack smoke test with Postgres/Qdrant/OpenSearch/MinIO.
- Run live integration suite in CI or a VPS builder with Docker.
- Run live Qdrant cleanup/expiration proof on an actual collection.
- Run provider integration tests for whichever embedding/rerank providers are enabled.
- Run backup/restore drill for one micro-production cell.
- Run p95/p99 retrieval and ingestion load validation on target cell sizes.
