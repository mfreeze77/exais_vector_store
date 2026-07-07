# Ticket Trail

Status legend:

- `scaffolded`: file/code/docs exist in this repo.
- `ready-to-build`: interface and location exist; needs implementation.
- `requires-provider-account`: needs external provider credentials or deployment.

## EPIC-001 Base repo/product

- SVS-001 Monorepo structure — scaffolded.
- SVS-002 Docker Compose local stack — scaffolded.
- SVS-003 Versioned image release model — ready-to-build.
- SVS-004 CI image build/push with digests — ready-to-build.

## EPIC-002 Tenancy/security

- SVS-010 Tenant/business/user/group schema — scaffolded.
- SVS-011 API key hashing/scopes/resolution — scaffolded.
- SVS-012 Security levels 0–5 — scaffolded.
- SVS-013 Postgres RLS policy draft — scaffolded.
- SVS-014 Cross-tenant leakage tests — scaffolded base tests, expand required.
- SVS-015 Output redaction/citation guard — ready-to-build.

## EPIC-003 OpenAI-compatible vector store API

- SVS-020 Create/list/get/delete vector stores — scaffolded.
- SVS-021 Attach files/content — scaffolded.
- SVS-022 Search vector store — scaffolded.
- SVS-023 File batches — DB table scaffolded, API ready-to-build.
- SVS-024 Expiration policies — DB fields scaffolded, worker ready-to-build.

## EPIC-004 Ingestion/indexing

- SVS-030 Markdown ingestion — scaffolded.
- SVS-031 External PDF-to-Markdown ingestion — scaffolded.
- SVS-032 Raw PDF research mode — config scaffolded.
- SVS-033 Code/table/log specialized parsers — ready-to-build.
- SVS-034 Idempotent reindexing — ready-to-build.
- SVS-035 Blue/green index versions — ready-to-build.

## EPIC-005 Model gateway/router

- SVS-040 Vectorization mode registry — scaffolded.
- SVS-041 Model registry — scaffolded.
- SVS-042 OpenAI embedding adapter — scaffolded.
- SVS-043 TEI/Infinity/RunPod provider adapter — scaffolded.
- SVS-044 Reranker adapter — scaffolded lexical fallback; production providers ready-to-build.
- SVS-045 Provider cost tables — ready-to-build.

## EPIC-006 Retrieval

- SVS-050 Qdrant dense indexing/search — scaffolded.
- SVS-051 OpenSearch sparse indexing/search — scaffolded.
- SVS-052 RRF hybrid fusion — scaffolded.
- SVS-053 Post-retrieval ACL verification — scaffolded.
- SVS-054 Context pack with citations — scaffolded.
- SVS-055 Neighbor/parent expansion — ready-to-build.

## EPIC-007 Micro-production deployment

- SVS-060 Instance manifests — scaffolded.
- SVS-061 Instance agent — scaffolded.
- SVS-062 Fleet upgrade script — scaffolded.
- SVS-063 Encrypted secrets workflow — ready-to-build.
- SVS-064 Signed releases/digest pinning — ready-to-build.

## EPIC-008 Production ops

- SVS-070 Hetzner sizing — scaffolded.
- SVS-071 Terraform/Ansible stubs — scaffolded.
- SVS-072 Backups/restore runbooks — scaffolded.
- SVS-073 Actual backup integrations — ready-to-build.
- SVS-074 Observability stack — ready-to-build.

## EPIC-009 Evals/fine-tuning

- SVS-080 Eval schema/metrics — scaffolded.
- SVS-081 Model bakeoff runner — ready-to-build.
- SVS-082 Fine-tuning lab — ready-to-build.

## EPIC-010 Frontend/admin workflow

- SVS-090 Admin UI mode selector — scaffolded.
- SVS-091 Vector store create UI — scaffolded.
- SVS-092 Ingest/search UI — scaffolded.
- SVS-093 Production auth/session UI — ready-to-build.
- SVS-094 Fleet/version dashboard — ready-to-build.
