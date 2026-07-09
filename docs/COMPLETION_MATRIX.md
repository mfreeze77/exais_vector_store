# Completion Matrix

| Area | Scaffolded | Production hardening next |
|---|---|---|
| API | FastAPI native + OpenAI-compatible routes | remaining OpenAI contract breadth, pagination tuning, rate-limit tuning |
| DB | schema + RLS | Alembic, rollback locks, PITR |
| Ingestion | markdown + PDF-MD stub | resumability, dedupe, parser plugins |
| Retrieval | dense+sparse+RRF+ACL+context | rerankers, expansion, latency tuning |
| Security | levels/scope/post-ACL/API-key hashing and lookup | secrets, output guards, OIDC |
| Model routing | mode/model registries | provider-specific adapters/pricing |
| RunPod | handler/Dockerfile | GPU image, warm pool, autoscaling |
| Micro production | manifests/agent/scripts | signed releases, canaries |
| Ops | Terraform/Ansible/runbooks | monitoring, real backup integrations |
| Evals | metrics/schema + golden bakeoff metrics | live retrieval/provider fan-out runner |


## Frontend

| Area | Status | Files |
|---|---|---|
| Mode selection UI | scaffolded | `apps/admin_ui/src/main.tsx` |
| Ingest/search UI | scaffolded | `apps/admin_ui/src/main.tsx` |
| Production sessions/OIDC | ticketed | `docs/FRONTEND_ADMIN_UI.md` |

## External audit response update

The external review correctly identified several defects as release blockers. This patch adds `docs/AUDIT_RESPONSE_WAVE_PLAN.md` and Wave tickets.

Implemented after audit:

- FORCE RLS hardening migration.
- API-key lookup compatible with FORCE RLS.
- Worker queue claim compatible with FORCE RLS.
- Endpoint scope enforcement.
- Strict Qdrant/OpenSearch adapter errors.
- Async ingestion threshold.
- Dedupe and basic document versioning.
- Chunk dense/sparse index-status columns.
- OpenAI-compatible vector-store file and file-batch surfaces.
- Postgres FTS fallback for micro-production cells.
- Real dependency-free code symbol chunker.
- Minimal metrics endpoint.
- Usage-event writes for retrieval and ingestion.

Still not complete:

- reindex repair worker
- Alembic
- full OpenAPI contract
- production observability dashboards
- live bakeoff fan-out, fine-tuning, and multimodal research features
