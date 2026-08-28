# Tickets

This folder contains the ExAIS Vector Store roadmap and implementation tickets.

Use `WAVE-*` tickets for release or production-hardening waves. Use
`TEMPLATE.md` for narrower follow-up tickets that need a standard shape.

## Current Ticket Index

- [WAVE-001 Security and Correctness Hardening](./WAVE-001-security-correctness-hardening.md)
- [WAVE-002 Ingestion Repair Expiration](./WAVE-002-ingestion-repair-expiration.md)
- [WAVE-003 Router Bakeoff Control Plane](./WAVE-003-router-bakeoff-control-plane.md)
- [WAVE-004 v0.9.6 Security Production Gate](./WAVE-004-v0.9.6-security-production-gate.md)
- [WAVE-005 v0.9.7 Live Postgres JSONB Portability](./WAVE-005-v0.9.7-live-postgres-jsonb-portability.md)
- [WAVE-005 v0.9.7 Live Postgres Portability](./WAVE-005-v0.9.7-live-postgres-portability.md)
- [WAVE-006 v0.9.8 Worker Attempt Atomicity](./WAVE-006-v0.9.8-worker-attempt-atomicity.md)
- [WAVE-007 Docker-First Local Cell Release Gate](./WAVE-007-docker-first-local-cell-release-gate.md)
- [WAVE-008 Operations Bug Hardening](./WAVE-008-operations-bug-hardening.md)
- [WAVE-009 Local Restore And Ops Preflight](./WAVE-009-local-restore-and-ops-preflight.md)
- [WAVE-010 RunPod Marker PDF Ingestion](./WAVE-010-runpod-marker-pdf-ingestion.md)
- [WAVE-011 Real Embedding Provider Gate](./WAVE-011-real-embedding-provider-gate.md)
- [WAVE-012 Vector Store Delete RLS Soft-Delete](./WAVE-012-vector-store-delete-rls-soft-delete.md)
- [WAVE-013 Real Embedding Scale Repair Regate](./WAVE-013-real-embedding-scale-repair-regate.md)
- [WAVE-014 OpenAI File Search Parity](./WAVE-014-openai-file-search-parity.md)
- [WAVE-015 OpenAI Vector Store Object Parity](./WAVE-015-openai-vector-store-object-parity.md)
- [WAVE-016 OpenAI Files Upload Parity](./WAVE-016-openai-files-upload-parity.md)
- [WAVE-017 OpenAI Vector Store File Route Parity](./WAVE-017-openai-vector-store-file-route-parity.md)
- [WAVE-018 OpenAI Responses File Search Citation Parity](./WAVE-018-openai-responses-file-search-citation-parity.md)
- [WAVE-019 OpenAI Responses Lifecycle Parity](./WAVE-019-openai-responses-lifecycle-parity.md)
- [WAVE-020 OpenAI Citation Marker Parity](./WAVE-020-openai-citation-marker-parity.md)
- [WAVE-021 Profile-Driven Rerank Retrieval](./WAVE-021-profile-driven-rerank-retrieval.md)
- [WAVE-022 OpenAI Hybrid Ranking Options](./WAVE-022-openai-hybrid-ranking-options.md)
- [WAVE-023 Context Pack Neighbor Expansion](./WAVE-023-context-pack-neighbor-expansion.md)
- [WAVE-024 Context Pack Parent Section Expansion](./WAVE-024-context-pack-parent-section-expansion.md)
- [WAVE-025 OpenAI Output Guard Citation Redaction](./WAVE-025-openai-output-guard-citation-redaction.md)
- [WAVE-026 OpenAI Vector Store Expiration Activity](./WAVE-026-openai-vector-store-expiration-activity.md)
- [WAVE-027 OpenAI File Batch Lifecycle Parity](./WAVE-027-openai-file-batch-lifecycle-parity.md)
- [WAVE-028 API Key Lifecycle Scope Parity](./WAVE-028-api-key-lifecycle-scope-parity.md)
- [WAVE-029 OpenAI Citation Route Proof](./WAVE-029-openai-citation-route-proof.md)
- [WAVE-030 Specialized Table And Log Chunking](./WAVE-030-specialized-table-log-chunking.md)
- [WAVE-031 OpenAI Tenant Leakage Proof](./WAVE-031-openai-tenant-leakage-proof.md)
- [WAVE-032 Idempotent Reindexing Proof](./WAVE-032-idempotent-reindexing-proof.md)
- [WAVE-033 Blue/Green Index Versioning](./WAVE-033-blue-green-index-versioning.md)
- [WAVE-034 Model-Gateway Reranker Adapter](./WAVE-034-model-gateway-reranker-adapter.md)
- [WAVE-035 Provider Cost Tables](./WAVE-035-provider-cost-tables.md)
- [WAVE-036 OpenAI File Search Call Default Parity](./WAVE-036-openai-file-search-call-default-parity.md)
- [WAVE-037 Responses File Search Query Planning](./WAVE-037-responses-file-search-query-planning.md)
- [WAVE-038 OpenAI Metadata Filter Parity](./WAVE-038-openai-metadata-filter-parity.md)
- [WAVE-039 OpenAI Range Filter Parity](./WAVE-039-openai-range-filter-parity.md)
- [WAVE-040 OpenAI File Search Result Citation Shape](./WAVE-040-openai-file-search-result-citation-shape.md)
- [WAVE-041 Responses Multi-Store Duplicate Citation Dedupe](./WAVE-041-responses-multistore-duplicate-citation-dedupe.md)
- [WAVE-042 OpenAI File Upload Text Encoding Parity](./WAVE-042-openai-file-upload-text-encoding-parity.md)
- [WAVE-043 OpenAI Citation Annotation Mirror](./WAVE-043-openai-citation-annotation-mirror.md)
- [WAVE-044 OpenAI File Upload Expiration Parity](./WAVE-044-openai-file-upload-expiration-parity.md)
- [WAVE-045 OpenAI Vector Store Expiration Policy Validation](./WAVE-045-openai-vector-store-expiration-policy-validation.md)
- [WAVE-046 Responses Streaming Citation Events](./WAVE-046-responses-streaming-citation-events.md)
- [WAVE-047 Responses Stream Resume Cursor](./WAVE-047-responses-stream-resume-cursor.md)
- [WAVE-048 Responses Stream Obfuscation Parity](./WAVE-048-responses-stream-obfuscation-parity.md)
- [WAVE-049 Responses File Search Tool Choice Citation Guard](./WAVE-049-responses-file-search-tool-choice-citation-guard.md)
- [WAVE-050 Responses Citation Integrity Guard](./WAVE-050-responses-citation-integrity-guard.md)
- [WAVE-051 Vector Store Search Visible Citation Markers](./WAVE-051-vector-store-search-visible-citation-markers.md)
- [WAVE-052 Rerank Diversity MMR](./WAVE-052-rerank-diversity-mmr.md)
- [WAVE-053 OpenAI Vector Store Search Multi-Query](./WAVE-053-openai-vector-store-search-multi-query.md)
- [WAVE-054 OpenAI Negation Filter Parity](./WAVE-054-openai-negation-filter-parity.md)
- [WAVE-055 Multimodal Retrieval Profile Contract](./WAVE-055-multimodal-retrieval-profile-contract.md)
- [WAVE-056 Context Pack OpenAI Citation Markers](./WAVE-056-context-pack-openai-citation-markers.md)
- [WAVE-057 Native Retrieval Answer Citation Integrity](./WAVE-057-native-retrieval-answer-citation-integrity.md)
- [WAVE-058 Stored Responses Citation Replay Integrity](./WAVE-058-stored-responses-citation-replay-integrity.md)
- [WAVE-059 OpenAI Mutating Route Idempotency](./WAVE-059-openai-mutating-route-idempotency.md)
- [WAVE-060 Expiration Sweeper Proof](./WAVE-060-expiration-sweeper-proof.md)
- [WAVE-061 OpenAI Update/Delete Idempotency](./WAVE-061-openai-update-delete-idempotency.md)
- [WAVE-062 OpenAI Responses Cancel Parity](./WAVE-062-openai-responses-cancel-parity.md)
- [WAVE-063 OpenAI Responses Input Tokens Parity](./WAVE-063-openai-responses-input-tokens-parity.md)
- [WAVE-064 OpenAI Citation Span Contract](./WAVE-064-openai-citation-span-contract.md)
- [WAVE-065 OpenAI File Search Citation Result Alias](./WAVE-065-openai-file-search-citation-result-alias.md)
- [WAVE-066 OpenAI Responses Compact Parity](./WAVE-066-openai-responses-compact-parity.md)
- [WAVE-067 OpenAI Citation Parity Lock](./WAVE-067-openai-citation-parity-lock.md)
- [WAVE-068 OpenAI Previous Response Continuation](./WAVE-068-openai-previous-response-continuation.md)
- [WAVE-069 OpenAI Route Rate-Limit Coverage](./WAVE-069-openai-route-rate-limit-coverage.md)
- [WAVE-070 OpenAI Responses OpenAPI Contract](./WAVE-070-openai-responses-openapi-contract.md)
- [WAVE-071 OpenAI Citation OpenAPI Response Contract](./WAVE-071-openai-citation-openapi-response-contract.md)
- [WAVE-072 OpenAI Vector Store Search OpenAPI Response Contract](./WAVE-072-openai-vector-store-search-openapi-response-contract.md)
- [WAVE-073 OpenAI Vector Store Search Ranker None Parity](./WAVE-073-openai-vector-store-search-ranker-none-parity.md)
- [WAVE-074 OpenAI Metadata Attribute Limit Contract](./WAVE-074-openai-metadata-attribute-limit-contract.md)
- [WAVE-075 Code Symbol Exact Match Boost](./WAVE-075-code-symbol-exact-match-boost.md)
- [WAVE-076 OpenAI Vector Store Add Rate Limit](./WAVE-076-openai-vector-store-add-rate-limit.md)
- [WAVE-077 OpenAI Same-Index Citation Parity](./WAVE-077-openai-same-index-citation-parity.md)
- [WAVE-078 API Key Expiration Create](./WAVE-078-api-key-expiration-create.md)
- [WAVE-079 OpenAI Vector Store List Stable Cursors](./WAVE-079-openai-vector-store-list-stable-cursors.md)
- [WAVE-080 OpenAI Files List Stable Cursors](./WAVE-080-openai-files-list-stable-cursors.md)
- [WAVE-081 Phrase-Aware Sparse Retrieval](./WAVE-081-phrase-aware-sparse-retrieval.md)
- [WAVE-082 API Key List After Cursor Parity](./WAVE-082-api-key-list-after-cursor-parity.md)
- [WAVE-083 Candidate-Aware Local Rerank](./WAVE-083-candidate-aware-local-rerank.md)
- [WAVE-084 OpenAI Citation Scalar Contract](./WAVE-084-openai-citation-scalar-contract.md)
- [WAVE-085 OpenAI Chunking Strategy Validation](./WAVE-085-openai-chunking-strategy-validation.md)
- [WAVE-086 OpenAI Citation Orphan Marker Guard](./WAVE-086-openai-citation-orphan-marker-guard.md)
- [WAVE-087 OpenAI Vector Store Create File IDs Chunking](./WAVE-087-openai-vector-store-create-file-ids-chunking.md)
- [WAVE-088 OpenAI Vector Store Search Next Page Cursor](./WAVE-088-openai-vector-store-search-next-page-cursor.md)
- [WAVE-089 OpenAI Citation Stream Done Event Contract](./WAVE-089-openai-citation-stream-done-event-contract.md)
- [WAVE-090 Responses File Search Default Result Count](./WAVE-090-responses-file-search-default-result-count.md)
- [WAVE-091 Responses File Search Max Results OpenAPI Bounds](./WAVE-091-responses-file-search-max-results-openapi-bounds.md)
- [WAVE-092 OpenAI File Search Stream Added Item State](./WAVE-092-openai-file-search-stream-added-item-state.md)
- [WAVE-093 OpenAI Citation Client Marker Contract](./WAVE-093-openai-citation-client-marker-contract.md)
- [WAVE-094 OpenAI Project API Key Route Parity](./WAVE-094-openai-project-api-key-route-parity.md)
- [WAVE-095 OpenAI Citation Stream OpenAPI Contract](./WAVE-095-openai-citation-stream-openapi-contract.md)
- [WAVE-096 OpenAI Admin API Key Route Parity](./WAVE-096-openai-admin-api-key-route-parity.md)
- [WAVE-097 OpenAI Recommended Citation Marker Contract](./WAVE-097-openai-recommended-citation-marker-contract.md)
- [WAVE-098 OpenAI Admin API Key Create Parity](./WAVE-098-openai-admin-api-key-create-parity.md)
- [WAVE-099 OpenAI Citation Replacement Span Contract](./WAVE-099-openai-citation-replacement-span-contract.md)
- [WAVE-100 Retrieval Capability Tracker Proof](./WAVE-100-retrieval-capability-tracker-proof.md)
- [WAVE-101 Native Context OpenAI Citation Marker Contract](./WAVE-101-native-context-openai-citation-marker-contract.md)
- [WAVE-102 OpenAI Message Citation Annotation Export](./WAVE-102-openai-message-citation-annotation-export.md)
- [WAVE-103 OpenAI File Batch OpenAPI Contract](./WAVE-103-openai-file-batch-openapi-contract.md)
- [WAVE-104 OpenAI Vector Store File OpenAPI Contract](./WAVE-104-openai-vector-store-file-openapi-contract.md)
- [WAVE-105 OpenAI Vector Store CRUD OpenAPI Contract](./WAVE-105-openai-vector-store-crud-openapi-contract.md)
- [WAVE-106 OpenAI Files OpenAPI Contract](./WAVE-106-openai-files-openapi-contract.md)
- [WAVE-107 OpenAI Uploaded File ID Citation Parity](./WAVE-107-openai-uploaded-file-id-citation-parity.md)
- [WAVE-108 Golden Query Bakeoff Metrics](./WAVE-108-golden-query-bakeoff-metrics.md)
- [WAVE-109 Expert AI Services Live Retrieval Quality Gate](./WAVE-109-expertaiservices-live-retrieval-quality-gate.md)
- [WAVE-110 Customer Private VPS Operator Console](./WAVE-110-customer-private-vps-operator-console.md)
- [WAVE-111 Kansas Court Decisions Corpus Ingestion](./WAVE-111-kansas-court-decisions-ingestion.md)
- [WAVE-112 Kansas Court Decisions GraphRAG Readiness](./WAVE-112-kansas-court-decisions-graphrag-readiness.md)
- [WAVE-113 Kansas Civics Instance Query Planner](./WAVE-113-kansas-civics-instance-query-planner.md)
- [WAVE-114 Kansas Civics Legal Exact Result Diversity](./WAVE-114-kansas-civics-legal-exact-result-diversity.md)
- [WAVE-115 Kansas Civics GraphRAG Search Expansion](./WAVE-115-kansas-civics-graphrag-search-expansion.md)
- [WAVE-116 Instance-Scoped Caller Vector Store Lifecycle](./WAVE-116-instance-scoped-caller-vector-store-lifecycle.md)
- [WAVE-117 Instance Vector-Store Source Package Contract](./WAVE-117-instance-vector-store-source-package-contract.md)
- [WAVE-118 Topeka Municipal Code Source Seeding](./WAVE-118-topeka-municipal-code-source-seeding.md)
- [WAVE-119 Topeka Workbench Canonical Projection](./WAVE-119-topeka-workbench-canonical-projection.md)
- [WAVE-120 GraphRAG Search Lenses](./WAVE-120-graphrag-search-lenses.md)

## Execution Model

The reusable Codex ticket execution model lives in
[codex-agents/README.md](./codex-agents/README.md).

Short discoverable skills live under `.agents/skills`:

- `.agents/skills/exais-ticket-orchestrator/SKILL.md`
- `.agents/skills/exais-ticket-implementation/SKILL.md`
- `.agents/skills/exais-quality-control/SKILL.md`
- `.agents/skills/exais-test-proof/SKILL.md`
- `.agents/skills/exais-ui-refactor-extraction/SKILL.md`
- `.agents/skills/exais-registry-contract/SKILL.md`

The tranche-generation skill lives at `.codex/skills/ticket-tranche`.

## Proof Expectations

Tickets should name the commands or proof needed for completion. Use the narrowest
proof that validates the ticket, then escalate only when the blast radius requires
it.

Common ExAIS proof commands:

```bash
PYTHONPATH=packages/svs_common:apps/api:apps/worker:apps/model_gateway:apps/instance_agent \
  python -m compileall -f -q packages apps tests
PYTHONPATH=packages/svs_common:apps/api:apps/worker:apps/model_gateway:apps/instance_agent \
  pytest -q -rs
npm --prefix apps/admin_ui run build
docker compose config
```

When host Python/npm dependencies or the Docker Compose plugin are unavailable,
use the Docker-first proof helper instead:

```powershell
python scripts/release/local-proof.py --cell ks-state-civics
```

Use `./scripts/smoke-test.sh`, migrations, Docker services, or live integration
proof only when the ticket requires those surfaces.
