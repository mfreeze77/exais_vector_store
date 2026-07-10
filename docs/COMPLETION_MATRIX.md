# Completion Matrix

| Area | Scaffolded | Production hardening next |
|---|---|---|
| API | FastAPI native + OpenAI-compatible routes; complete named-component request/2xx response contract proof | pagination tuning, rate-limit tuning |
| DB | schema + RLS + Alembic baseline | rollback locks, PITR, forward-fix revisions for future changes |
| Ingestion | markdown + PDF-MD stub | resumability, dedupe, parser plugins |
| Retrieval | dense+sparse+RRF+ACL+context | rerankers, expansion, latency tuning |
| Security | levels/scope/post-ACL/API-key hashing and lookup | secrets, output guards, OIDC |
| Model routing | mode/model registries | provider-specific adapters/pricing |
| RunPod | handler/Dockerfile | GPU image, warm pool, autoscaling |
| Micro production | manifests/agent/scripts | signed releases, canaries |
| Ops | Terraform/Ansible/runbooks; backup artifact manifests and restore preflight; local observability stack | external production SLO/load proof, external/offsite restore proof |
| Evals | metrics/schema + golden bakeoff metrics + deterministic live fan-out runner | live provider credential proof, fine-tuning, multimodal research |


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
- Local-cell observability overlay, dashboard, alert rules, and smoke proof for API, ingestion/worker, index, storage, security, cost, and backup metric visibility.

Reindex repair is complete and reconciled: the API and queued worker use the shared `MaintenanceService.reindex_chunks` path to select non-indexed dense/sparse chunks, replay both backends, mark rows indexed, and support cursor-paginated force repair. Focused production-candidate proof passed with `14 passed`:

`docker run --rm -v "${pwdPath}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_reindex_idempotency.py tests/test_index_cleanup.py tests/test_qdrant_repair_all_script.py tests/test_qdrant_repair_proof_script.py`

The full generated OpenAPI contract is complete and reconciled under RM-002.
Current proof records 51 paths, 68 operations, and 118 schema components. Every
JSON request body and 2xx response body is component-backed; native responses
are runtime-bound, vector-store null bodies retain named nullable contracts, and
multipart/raw-text responses keep their correct media types. The focused
contract and OpenAI route suites pass with `141 passed`.

Still not complete:

- rollback locks, PITR, and future schema revisions beyond the frozen Alembic baseline
- external production-scale observability/SLO/load proof beyond local-cell metric visibility
- external/offsite restore drill against a real backup target
- operator live-provider bakeoff proof, fine-tuning, and multimodal research features
