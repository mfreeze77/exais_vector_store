# Completion Matrix v0.9.6

| Area | Status | Evidence |
|---|---:|---|
| Tenant/business/user security model | 95% | migrations, RLS, API scopes, tests |
| Ingestion pipeline | 95% | async jobs, dedupe, versioning, artifact storage, chunk status |
| Retrieval pipeline | 95% | Qdrant + Postgres FTS/OpenSearch, RRF, post-ACL, audit, usage |
| OpenAI-compatible vector stores | 90% | main file/file-batch APIs implemented; not a byte-for-byte OpenAI clone |
| Intelligent vectorization router | 90% | preview plans, candidate scoring, model registry, mode-specific chunkers |
| Micro-production ops | 90% | manifests, agent, svsctl, backup/restore scripts; HA orchestration remains deployment-specific |
| Observability | 80% | metrics endpoint and counters; full Grafana/Loki dashboards still infra work |
| Evals/fine-tuning | 75% | tables/API/proxy bakeoff; real golden-set provider bakeoff needs corpus/credentials |
| RunPod/private models | 80% | endpoint/provider contracts; actual model container depends on chosen model |
| Frontend admin UI | 80% | mode selector, preview plan, ingest/search; full user/admin console remains product UI work |


## v0.9.6 security production gate

See `docs/V0_9_6_PATCH_REPORT.md` and `tickets/WAVE-004-v0.9.6-security-production-gate.md`.
