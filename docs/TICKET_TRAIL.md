# Ticket Trail

Status legend:

- `scaffolded`: file/code/docs exist in this repo.
- `implemented`: behavior is wired and covered by focused proof.
- `ready-to-build`: interface and location exist; needs implementation.
- `requires-provider-account`: needs external provider credentials or deployment.

## EPIC-001 Base repo/product

- SVS-001 Monorepo structure — scaffolded.
- SVS-002 Docker Compose local stack — scaffolded.
- SVS-003 Versioned image release model — implemented for the
  `scripts/release/release_common.py:APP_IMAGES` app image set, build/publish
  manifest emission, and immutable digest-pinned local-cell startup.
- SVS-004 CI image build/push with digests — implemented for repo-buildable CI
  image builds and digest/provenance manifest verification. RM-004 is complete:
  publication atomically writes the candidate manifest without mutating active
  pins; startup derives and preflights all five `repository@sha256:digest`
  references before atomically activating the per-cell image env. Cell and
  instance compose paths have no mutable app-tag fallback and use
  `--pull never`. External registry credential proof, clean pull-by-digest
  evidence, VPS/customer-cell launch, and Docker Hub claims remain separate
  operator proof gates.

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
- RM-002 OpenAPI contract reconciliation — complete. The generated contract covers 51 paths and 68 operations (31 native and 37 OpenAI-compatible) with 118 schema components. Every JSON request body and 2xx response body resolves directly to a named component. Native response contracts are runtime-bound; named nullable wrappers preserve vector-store create/update JSON `null`; multipart uploads and HTTP-proven raw-text responses retain correct media types. `tests/test_openapi_contract.py` freezes every valid OpenAPI HTTP method across the exact operation inventory, while the focused contract/OpenAI route suites pass with `141 passed`. This closes contract drift without reopening OpenAI parity behavior.

## EPIC-004 Ingestion/indexing

- SVS-030 Markdown ingestion — scaffolded.
- SVS-031 External PDF-to-Markdown ingestion — scaffolded.
- SVS-032 Raw PDF research mode — config scaffolded.
- SVS-033 Code/table/log specialized parsers — implemented with code-symbol chunks, JSON/CSV/Markdown-table record chunks, log event-boundary chunks, and focused router/chunker proof.
- SVS-034 Idempotent reindexing — implemented with cursor-aware repair, stable dense point/sparse doc replay, force/non-force selection proof, and repair-all script coverage. RM-001 reconciliation proof: `docker run --rm -v "${pwdPath}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_reindex_idempotency.py tests/test_index_cleanup.py tests/test_qdrant_repair_all_script.py tests/test_qdrant_repair_proof_script.py` -> `14 passed`.
- SVS-035 Blue/green index versions — implemented with optional active index version suffixes for Qdrant/OpenSearch, default-name compatibility, and reindex collection/point metadata persistence proof.
- SVS-036 Kansas Court Decisions corpus ingestion — implemented via WAVE-111
  for manifest-driven, resumable ingestion of the local Kansas court decision
  PDF corpus. The pilot importer performs text-first PDF extraction into
  `pdf_markdown_external_v1`, preserves legal metadata, records failed PDFs,
  supports bounded Marker fallback retries, blocks full-corpus runs on
  `hash_mock` unless explicitly overridden, and produced local Docker proof for
  `29` indexed pilot documents and `248` indexed chunks.
- SVS-037 Kansas Court Decisions GraphRAG readiness — implemented via WAVE-112
  with deterministic citation/entity extraction, source-grounded JSONL graph
  artifacts, artifact-level authority/cited-by/related/filter eval proof, and a
  Postgres-first backend recommendation before any production graph service is
  introduced.
- SVS-038 Kansas Civics GraphRAG search expansion — implemented via WAVE-115
  with tenant-scoped Postgres graph staging tables, an idempotent Kansas graph
  artifact loader, profile-scoped opt-in OpenAI vector-store search expansion,
  graph relation citation metadata, and live `ks-state-civics` proof. This is
  still additive GraphRAG, not a graph database or replacement retrieval path.

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
- SVS-061 Instance agent — scaffolded overall; RM-004 deploy/rollback image
  activation is implemented for explicit verified release manifests, exact
  three-service digest preflight, process-env-safe compose pins, `--pull never`,
  failed-up pin restoration, packaged Docker/Compose tooling, mounted instance
  and release-state roots, and mutation-free Compose dry-run validation. Live
  customer-host orchestration remains unproved.
- SVS-062 Fleet upgrade script — scaffolded; deploy callers now forward the
  required verified release-manifest path, without claiming fleet execution.
- SVS-063 Encrypted secrets workflow — implemented for host-side production
  cell launch. `svs_common.secrets` resolves SOPS/age, Vault, and `envref://`
  references; production preflight rejects plaintext secret-bearing values and
  DSNs with embedded passwords while reporting names only; and
  `generate-cell-env.py --production` imports only valid references.
  `cell-up.py` resolves them into a restricted process-scoped Compose env before
  image-pin activation or Docker and removes the file after the command;
  `cell-smoke.py` does the same across worker stop/recreate and restoration.
  `runbooks/encrypted-secrets.md` documents setup, failure handling, rotation,
  and rollback. Authenticated reads and successful launch on a selected
  customer host remain operator proof gates.
- SVS-064 Signed releases/digest pinning — implemented for local digest
  provenance manifests, exact five-service repository-digest pins, persistent
  compose consumption, failure-atomic activation, and startup rejection of
  unpinned, mismatched, or locally unverifiable app images. Failed compose or
  health activation restores the prior pin artifact without claiming runtime
  data rollback. The narrow instance compose/agent path requires three verified
  digest pins. Cryptographic signing and external registry proof remain
  operator-dependent follow-up gates.

## EPIC-008 Production ops

- SVS-070 Hetzner sizing — scaffolded.
- SVS-071 Terraform/Ansible stubs — scaffolded.
- SVS-072 Backups/restore runbooks — implemented for repo-buildable backup
  manifest/preflight workflow in `runbooks/backup-restore.md`; external restore
  drill proof remains an operator gate.
- SVS-073 Actual backup integrations — implemented for schema-versioned backup
  artifact manifests covering Postgres metadata, Qdrant vectors, OpenSearch
  sparse indexes, object/config/audit artifacts, and checksum metadata, with
  nondestructive restore preflight validation. Real offsite target proof and
  external restore drill evidence remain separate operator gates.
- SVS-074 Observability stack — implemented for local-cell Prometheus,
  Grafana, and Alertmanager overlay wiring, API/model-gateway metric surfaces,
  dashboard panels, alert rules, and smoke proof. External SLO/load proof,
  production-scale observability, and customer-host deployment proof remain
  separate gates.
- SVS-075 Customer-private VPS deployment model — ready-to-build for one
  isolated Docker Compose cell per customer, with public HTTPS API/admin
  endpoints only through a reverse proxy, no exposed data-plane service ports,
  customer-specific secrets, volumes, backups, and upgrade windows. WAVE-110
  owns the operator-console surface for this model; Hetzner provisioning,
  registry credentials, DNS, and offsite restore proof remain operator gates.
- SVS-076 Instance-scoped caller vector-store lifecycle — implemented via
  WAVE-116 for the API-key caller process that creates multiple vector stores,
  uploads files, attaches or batches files, and hands only selected store IDs to
  agents. This intentionally keeps API keys scoped at the customer-instance
  level instead of adding per-key vector-store grant tables. The implementation
  added first-admin-key bootstrap and live caller-lifecycle proof scripts with
  secret-redaction tests; live VPS proof remains an operator handoff gate.
- SVS-077 Instance vector-store source packages — implemented via WAVE-117 as a
  pre-VPS rollout gate. Each customer vector store loaded from scraped or
  externally collected data must have an instance-owned source package with the
  collector entrypoint, portable source reference, manifest/checksum lock,
  API-only update policy, GraphRAG/eval proof policy, validation command, and
  dry-run update planner. KS State Civics now has the first package before
  migrated-volume handoff or first Hetzner launch.

## EPIC-009 Evals/fine-tuning

- SVS-080 Eval schema/metrics — implemented for recall@k, precision@k, MRR,
  NDCG@k, leakage counts, chunk/document judged golden-query metrics, and the
  WAVE-109 live ticket-corpus quality gate. The production default passed all
  19 judged questions at hit@5 with `0.903509` MRR, `0.927944` NDCG@5,
  complete passage support/strict citations, and `465.850 ms` p95. The proof
  applies only to the current `expertaiservices` Markdown ticket corpus.
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
- SVS-095 Customer private VPS operator console — implemented via WAVE-110.
  The UI is now the Expert AI Services operator surface for customer
  onboarding, vector-store/file management, ingestion status, scoped agent API
  keys, OpenAI-compatible endpoint handoff, fleet health, release drift, and
  backup readiness. The local Docker cell proof covered the rebuilt admin UI,
  the OpenAI-compatible vector-store path, Responses file search, fleet version
  reporting, and cleanup of temporary proof artifacts.
