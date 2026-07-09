# Completion Matrix

| Area | Scaffolded | Production hardening next |
|---|---|---|
| API | FastAPI native + OpenAI-compatible routes; OpenAI-compatible named-component contract proof | native success response/request component typing, several inline OpenAI request bodies, pagination tuning, rate-limit tuning |
| DB | schema + RLS + Alembic baseline | rollback locks, PITR, forward-fix revisions for future changes |
| Ingestion | markdown + PDF-MD stub | resumability, dedupe, parser plugins |
| Retrieval | dense+sparse+RRF+ACL+context | rerankers, expansion, latency tuning |
| Security | levels/scope/post-ACL/API-key hashing and lookup | secrets, output guards, OIDC |
| Model routing | mode/model registries | provider-specific adapters/pricing |
| RunPod | handler/Dockerfile | GPU image, warm pool, autoscaling |
| Micro production | manifests/agent/scripts | signed releases, canaries |
| Ops | Terraform/Ansible/runbooks; backup artifact manifests and restore preflight | monitoring, external/offsite restore proof |
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

Reindex repair is complete and reconciled: the API and queued worker use the shared `MaintenanceService.reindex_chunks` path to select non-indexed dense/sparse chunks, replay both backends, mark rows indexed, and support cursor-paginated force repair. Focused production-candidate proof passed with `14 passed`:

`docker run --rm -v "${pwdPath}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_reindex_idempotency.py tests/test_index_cleanup.py tests/test_qdrant_repair_all_script.py tests/test_qdrant_repair_proof_script.py`

Still not complete:

- rollback locks, PITR, and future schema revisions beyond the frozen Alembic baseline
- full OpenAPI contract. RM-002 generated proof records 49 paths (26 native, 23 OpenAI-compatible) and 77 schema components; the focused production-candidate contract/OpenAI suites passed with `137 passed`. OpenAI-compatible vector-store, file, file-batch, Responses, citation, and API-key surfaces are component-backed. Remaining gaps are explicit: most native success responses are untyped, and several JSON request bodies remain inline dictionaries or optional-body wrappers.
- production observability dashboards
- external/offsite restore drill against a real backup target
- live bakeoff fan-out, fine-tuning, and multimodal research features
