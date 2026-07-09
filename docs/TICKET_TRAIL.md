# Ticket Trail

Status legend:

- `scaffolded`: file/code/docs exist in this repo.
- `implemented`: behavior is wired and covered by focused proof.
- `ready-to-build`: interface and location exist; needs implementation.
- `requires-provider-account`: needs external provider credentials or deployment.

## EPIC-001 Base repo/product

- SVS-001 Monorepo structure — scaffolded.
- SVS-002 Docker Compose local stack — scaffolded.
- SVS-003 Versioned image release model — ready-to-build.
- SVS-004 CI image build/push with digests — ready-to-build.

## EPIC-002 Tenancy/security

- SVS-010 Tenant/business/user/group schema — scaffolded.
- SVS-011 API key hashing/scopes/resolution — implemented for hashed bearer resolution, scoped create/list/revoke lifecycle with optional create-time expiration, stable OpenAI-style `after` list cursors, OpenAI-compatible project API-key list/retrieve/delete aliases with redacted metadata-only payloads, OpenAI-compatible organization admin API-key create/list/retrieve/delete aliases with one-time create `value`, scope-inherited create policy, redacted metadata-only list/retrieve payloads, and `order=asc|desc` list support, endpoint scope checks, per-principal OpenAI-compatible route rate-limit buckets, and idempotency-key protection for retry-sensitive OpenAI-compatible mutating routes.
- SVS-012 Security levels 0–5 — scaffolded.
- SVS-013 Postgres RLS policy draft — scaffolded.
- SVS-014 Cross-tenant leakage tests — implemented for FORCE RLS table coverage, plain-SQL tenant isolation, and OpenAI-compatible ID helper tenant/business scoping proof.
- SVS-015 Output redaction/citation guard — scaffolded.

## EPIC-003 OpenAI-compatible vector store API

- SVS-020 Create/list/get/delete vector stores — implemented for OpenAI-shaped vector-store object routes, stable cursor list pagination controls, update/delete, expiration fields, metadata limit validation, named OpenAPI response components for vector-store CRUD, and mutating-route idempotency.
- SVS-021 Attach files/content — implemented for OpenAI file upload/list/retrieve/content/delete, current `file-...` public IDs for newly uploaded OpenAI files while preserving legacy `file_...` lookup, stable uploaded-file list cursors, vector-store file attach/update/list/content/delete, named OpenAPI response components for `/v1/files`, standalone vector-store file routes, and file-batch routes, upload text encoding parity, created-at anchored upload expiration, vector-store-file attribute limit validation, OpenAI static chunking-strategy validation, vector-store create-with-file_ids chunking propagation, per-vector-store add-file route limiting, and mutating-route idempotency.
- SVS-022 Search vector store — implemented for OpenAI-shaped search, hybrid ranking options, request-scoped `ranker: none`, query planning, citation output, direct search response OpenAPI component coverage, direct search `next_page` cursor paging, and safe metadata filter parity including list and range comparisons.
- SVS-023 File batches — implemented with OpenAI create/retrieve/cancel/list-files parity, named OpenAPI response components for file batches and batch file pages, and focused proof.
- SVS-024 Expiration policies — implemented for strict OpenAI `expires_after` request validation, `last_active_at` activity refresh, fail-closed retrieval, and maintenance sweeper proof for expired row marking plus stale-vector cleanup enqueue.
- RM-002 OpenAPI contract reconciliation — OpenAI-compatible vector-store, file, file-batch, Responses, citation, and API-key surfaces have named generated request/response components and pass focused contract proof. The production-candidate image currently generates 49 paths (26 native and 23 OpenAI-compatible) with 77 schema components; `tests/test_openapi_contract.py` and the focused OpenAI route suites pass with `137 passed`. The full contract remains incomplete: most native success responses are still untyped, and several JSON request bodies remain inline dictionaries or optional-body wrappers. These are explicit follow-up gaps, not reopened OpenAI parity work.

## EPIC-004 Ingestion/indexing

- SVS-030 Markdown ingestion — scaffolded.
- SVS-031 External PDF-to-Markdown ingestion — scaffolded.
- SVS-032 Raw PDF research mode — config scaffolded.
- SVS-033 Code/table/log specialized parsers — implemented with code-symbol chunks, JSON/CSV/Markdown-table record chunks, log event-boundary chunks, and focused router/chunker proof.
- SVS-034 Idempotent reindexing — implemented with cursor-aware repair, stable dense point/sparse doc replay, force/non-force selection proof, and repair-all script coverage. RM-001 reconciliation proof: `docker run --rm -v "${pwdPath}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_reindex_idempotency.py tests/test_index_cleanup.py tests/test_qdrant_repair_all_script.py tests/test_qdrant_repair_proof_script.py` -> `14 passed`.
- SVS-035 Blue/green index versions — implemented with optional active index version suffixes for Qdrant/OpenSearch, default-name compatibility, and reindex collection/point metadata persistence proof.

## EPIC-005 Model gateway/router

- SVS-040 Vectorization mode registry — scaffolded; routed multimodal
  retrieval profile resolution implemented.
- SVS-041 Model registry — scaffolded.
- SVS-042 OpenAI embedding adapter — scaffolded.
- SVS-043 TEI/Infinity/RunPod provider adapter — scaffolded.
- SVS-044 Reranker adapter — implemented for deterministic local rerank plus model-gateway rerank adapter; direct provider-specific reranker APIs remain behind the gateway boundary.
- SVS-045 Provider cost tables — implemented with static per-1M-token registry cost metadata, model-gateway estimate-cost responses, and ingestion preview candidate cost hints.

## EPIC-006 Retrieval

- SVS-050 Qdrant dense indexing/search — implemented for versioned business/profile collections, strict adapter failures, health checks, dense candidate search, stale-point cleanup, and repair proof.
- SVS-051 OpenSearch sparse indexing/search — implemented for tenant/business/security-scoped sparse candidate search, phrase-aware text matching, safe file-attribute filters, strict adapter failures, stale-doc cleanup, and Postgres FTS fallback for small cells.
- SVS-052 RRF hybrid fusion — implemented with dense/sparse RRF, candidate-aware local lexical reranking, and phrase-aware sparse retrieval across Postgres FTS and OpenSearch.
- SVS-053 Post-retrieval ACL verification — implemented for tenant/business/security scoped candidate filters, authoritative Postgres hydration, group/role/security-level post-ACL filtering, and focused regression proof.
- SVS-054 Context pack with citations — implemented for retrieval/search/context-pack citation objects, native context-pack visible `【n†source】` markers with exact annotation offsets, native context-pack/answer OpenAI recommended model citation markers with optional line locators, native `/retrieval/answer` extractive cited answers with shared OpenAI citation-span integrity checks, OpenAI Responses file-search annotation proof, default `file_search_call.results: null` and `search_results: null` parity, OpenAI-shaped included file-search results, direct vector-store search visible citation markers, direct vector-store search query-array parity, OpenAI safe file-attribute `ne`/`nin` filters, lexical MMR result diversity, exact code-symbol boosting, multi-store duplicate citation dedupe, Responses query-planning parity, native citation `annotation` mirrors, Responses SSE citation events, stored Responses stream resume cursors, stream obfuscation parity, file-search stream added-item in-progress shape, file-search `tool_choice` citation guards, generation-time citation integrity checks, stored Responses replay citation integrity checks, orphan visible citation-marker rejection, Responses background-cancel route parity, Responses input-token count preflight parity, Responses compact handoff parity, stored `previous_response_id` continuation, Responses request OpenAPI component coverage, Responses citation response OpenAPI component coverage, Responses citation stream OpenAPI component coverage, an OpenAI guide-shape citation parity lock, same-index multi-citation parity, client-replaceable citation marker mapping with native replacement spans and OpenAI message-annotation export, OpenAI recommended model citation marker formatting/parsing, `response.output_text.done` stream ordering proof for cited text, Responses `file_search.max_num_results` default-20 parity with OpenAPI 1..50 bounds, and a reusable strict `file_citation` annotation contract for marker offsets plus non-negative/non-empty scalar validation.
- SVS-055 Neighbor/parent expansion — implemented for profile-driven same-document neighbor windows and parent-heading section expansion in native context packs, preserving OpenAI search/Responses result counts, tenant/business/security/file filters, post-ACL checks, token trimming, and native relation citation metadata.

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

- SVS-080 Eval schema/metrics — implemented for recall@k, precision@k, MRR,
  NDCG@k, leakage counts, and chunk/document judged golden-query metrics.
- SVS-081 Model bakeoff runner — implemented for persisted bakeoff runs/results,
  per-candidate golden metric comparison when judged result IDs are supplied,
  and deterministic proxy fallback; live retrieval/provider fan-out remains
  ready-to-build.
- SVS-082 Fine-tuning lab — ready-to-build.

## EPIC-010 Frontend/admin workflow

- SVS-090 Admin UI mode selector — scaffolded.
- SVS-091 Vector store create UI — scaffolded.
- SVS-092 Ingest/search UI — scaffolded.
- SVS-093 Production auth/session UI — ready-to-build.
- SVS-094 Fleet/version dashboard — ready-to-build.
