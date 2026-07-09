# Production-Ready Delta — exai_vector_store

This document overrides the earlier “MVP/one-box first” framing. It turns `exai_vector_store` into a production-grade, self-hosted retrieval platform for many tenants, business instances, users, data classes, security levels, and retrieval workloads.

The biggest change: **production-ready does not mean one large VPS**. It means a self-owned platform with redundancy, isolation, operability, repeatable restores, versioned indexes, and clear SLOs. A single dedicated server can be a solo production appliance for low-risk workloads, but it is not high availability and should not be the default for a business-critical 2 TB retrieval platform.

---

## 1. Production target assumptions

### 1.1 Workload target

Design target:

- 2 TB active retrieval corpus, including originals, parsed text, chunks, vector payloads, sparse indexes, metadata, and active snapshots.
- Multi-tenant usage: many organizations, many business instances per organization, many users/API keys per business instance.
- Security classifications from public to isolated/high-risk.
- Search types: dense vector, keyword/BM25, metadata-filtered search, hybrid fusion, reranking, graph expansion, context-pack creation.
- Data types: Markdown, code, PDFs, HTML, tickets, CRM records, JSON/CSV, database rows, logs, contracts, support articles, policies, and future adapters.

### 1.2 SLOs and recovery objectives

Set explicit production objectives before implementation:

| Area | Target |
|---|---:|
| API availability | 99.9% single-region target, 99.95% later with multi-region read failover |
| Metadata RPO | <= 5 minutes |
| Metadata RTO | <= 30 minutes |
| Object/original file RPO | <= 15 minutes |
| Vector index RPO | <= 30 minutes, plus reindex-from-source capability |
| Vector index RTO | <= 4 hours for full service, <= 30 minutes degraded search |
| Search p95 latency | <= 500 ms internal retrieval before rerank for common tenant-scoped queries |
| Context-pack p95 latency | <= 2 seconds before LLM call for normal top-k queries |
| Index freshness | <= 5 minutes for normal docs, <= 30 seconds for priority docs |
| Restore drill | Monthly for metadata, quarterly full-platform DR |
| Tenant leakage tolerance | Zero accepted cross-tenant retrieval or output leakage |

### 1.3 Core production principle

Every source record must be recoverable without trusting the vector index:

```text
Original object + metadata + chunking profile + embedding profile + ACL version
  => deterministic rebuild of parsed docs, chunks, sparse index, vector index, and context citations
```

Vectors are indexes. The document registry, object store, metadata DB, and index-version ledger are the source of truth.

---

## 2. Architecture change: from app stack to platform stack

### 2.1 Production control plane

```text
Public/API network
  |
  +--> L4/L7 load balancer
        |
        +--> API nodes, horizontally scaled
        +--> Admin UI nodes
        +--> Webhook receiver nodes

Private service network
  |
  +--> Auth/session service
  +--> Policy service / OPA-compatible authorization
  +--> Retrieval planner
  +--> Ingestion orchestrator
  +--> Worker pools
  +--> Queue/event bus

Data plane
  |
  +--> PostgreSQL HA cluster: metadata, ACLs, audit, jobs, usage, registry
  +--> Qdrant cluster: dense vectors + payload filters
  +--> OpenSearch cluster: sparse/BM25 text search at scale
  +--> Object storage: originals, parsed artifacts, exports, snapshots, backups
  +--> Redis/Valkey: cache, rate limiting, ephemeral queues only
```

### 2.2 Production service split

Do not keep everything inside one API process. Split services by operational behavior:

| Service | Purpose | Scaling dimension |
|---|---|---|
| `svs-api` | Public/native/OpenAI-compatible API | requests/sec |
| `svs-admin` | Admin UI/backend endpoints | admins/ops |
| `svs-authz` | policy decisions, scope resolution | request count |
| `svs-ingest-orchestrator` | ingestion job state machine | job count |
| `svs-parser-worker` | parsing/chunking/classification | CPU/I/O |
| `svs-embed-worker` | embedding batches/provider calls | external API limits/GPU if local |
| `svs-index-worker` | Qdrant/OpenSearch writes | write IOPS |
| `svs-retrieval-planner` | dense/sparse/graph query plan | query complexity |
| `svs-reranker` | optional cross-encoder rerank | CPU/GPU |
| `svs-audit-writer` | immutable audit/usage stream | event volume |
| `svs-maintenance` | compaction, expiry, snapshots, reindexing | scheduled ops |

---

## 3. Infrastructure change: production-ready Hetzner layout

### 3.1 The key advice change

For production-ready 2 TB retrieval, prefer **dedicated servers with local NVMe** for vector and database nodes. Hetzner Cloud Volumes are useful, but they attach to one server at a time, do not have native volume backups/snapshots, and have lower throughput/IOPS than local NVMe. Use them for non-critical expansion, staging, or object/cache space, not as the only durable high-performance vector/data disk.

### 3.2 Production deployment modes

#### Mode A — Solo production appliance, not HA

Use only when downtime is acceptable and every important byte is backed up/rebuildable.

```text
1 dedicated server
  - 128–256 GB RAM
  - 16–32 physical threads or better
  - 4 × 3.84 TB NVMe RAID10, or 2 × 7.68 TB NVMe mirror
  - LUKS full-disk encryption
  - local Qdrant + Postgres + OpenSearch + MinIO cache
  - remote object storage backups
```

This is strong for a private solo business system, but it is **not high availability**.

#### Mode B — Minimum serious single-region production

```text
3 dedicated data nodes
  - each 128–256 GB RAM
  - each 16–32 cores/threads minimum
  - each 2 × 3.84 TB NVMe mirror minimum
  - better: 4 × 3.84 TB NVMe RAID10
  - run Qdrant data nodes
  - run OpenSearch data nodes

3 PostgreSQL HA nodes
  - each 64–128 GB RAM
  - 2 × 1.92 TB NVMe mirror
  - Patroni + etcd/Consul + HAProxy/PgBouncer

3 app/control nodes
  - cloud CCX/general-purpose instances or small dedicated nodes
  - API, admin, workers, schedulers

Object storage
  - Hetzner Object Storage or distributed MinIO cluster
  - plus offsite backup target in a second provider/account
```

This is the first architecture I would personally call production-ready for business-critical multi-tenant retrieval.

#### Mode C — Enterprise/isolation-ready production

```text
3–5 control/app nodes
3 PostgreSQL HA nodes
3–6 Qdrant nodes
3–6 OpenSearch nodes
4+ object-storage nodes if self-hosting MinIO
separate monitoring/logging node pool
separate bastion/VPN/access layer
optional dedicated cluster per regulated enterprise tenant
```

Mode C is what you move to when customer isolation, compliance, and uptime become selling points.

---

## 4. Storage and sizing model for 2 TB retrieval

### 4.1 Stop sizing by “2 TB” alone

You need to size by:

```text
active original data
+ parsed text artifacts
+ chunk records
+ dense vectors
+ vector HNSW/index overhead
+ sparse/BM25 index
+ metadata and audit
+ snapshots
+ rebuild headroom
+ replication factor
+ backup copies
```

A 2 TB active retrieval platform can easily require **8–15 TB of raw disk across the cluster**, depending on replication, snapshots, and how much original content you retain locally.

### 4.2 Dense vector sizing formula

For float32 embeddings:

```text
raw_vector_bytes = vector_count × dimensions × 4
with_qdrant_memory_estimate = vector_count × dimensions × 4 × 1.5
with_replication = raw_or_indexed_size × replication_factor
```

Example raw vector sizes, excluding payload, HNSW/index overhead, sparse index, object storage, snapshots, and replication:

| Chunks/vectors | 1536-dim float32 | 3072-dim float32 |
|---:|---:|---:|
| 10 million | ~61 GB | ~123 GB |
| 50 million | ~307 GB | ~614 GB |
| 100 million | ~614 GB | ~1.23 TB |
| 250 million | ~1.54 TB | ~3.07 TB |

Production notes:

- For cost-efficient storage, prefer `text-embedding-3-small`-class 1536-dim vectors or a reduced-dimension profile unless quality tests prove you need larger vectors.
- Keep hot/current tenants in faster collections.
- Use on-disk/memmap storage for cold vectors.
- Use payload indexes only for fields used in filters.
- Keep source text outside Qdrant when possible; store only chunk IDs and retrieval payload needed for filtering/ranking.

### 4.3 Recommended capacity envelope

For 2 TB active retrieval with replication factor 2:

| Layer | Minimum usable target | Notes |
|---|---:|---|
| Qdrant local NVMe | 6–10 TB usable | RF=2, shards, snapshots, optimizer headroom |
| OpenSearch local NVMe | 3–6 TB usable | BM25/sparse text can be large; depends on stored fields |
| PostgreSQL NVMe | 1–2 TB usable | metadata, jobs, ACL, audit, usage; not raw object store |
| Object store active | 4–8 TB | originals, parsed artifacts, exports, Qdrant snapshots |
| Offsite backups | 8–20 TB | retention-dependent |

A realistic first production buy is **3 data nodes with 4 × 3.84 TB NVMe RAID10 each**, plus separate Postgres HA and object backup capacity.

---

## 5. Data plane changes

### 5.1 PostgreSQL: source of truth, HA required

Use Postgres for:

- organizations
- business instances
- users and service accounts
- API keys
- roles, groups, memberships
- policies and security labels
- document registry
- chunk registry
- embedding/index versions
- ingestion jobs and state transitions
- ACL records
- audit ledger
- usage/cost ledger
- source connector state
- retention and deletion registry

Production requirements:

- Patroni-managed HA cluster.
- 3-node etcd/Consul or Kubernetes control for leader election.
- PgBouncer for connection pooling.
- WAL archiving to object storage.
- PITR backups.
- Monthly restore drills.
- Partition large audit/job tables by time.
- Row-Level Security remains useful, but application-level policy checks are still required.

### 5.2 Qdrant: dense vector search only, not the truth store

Use Qdrant for:

- dense vectors
- payload filters needed during retrieval
- collection-level tenant/security partitioning
- nearest-neighbor candidates
- snapshots for faster DR

Production requirements:

- 3+ nodes minimum.
- `replication_factor >= 2` for important collections.
- shard count planned per tenant/security class.
- local NVMe, not NFS/S3-mounted storage.
- payload indexes for every security/filter field used in queries.
- no raw sensitive text in Qdrant payload unless necessary.
- collection aliases for blue/green reindexing.
- snapshots exported to object storage.

### 5.3 OpenSearch: production sparse search

In the earlier version, Postgres FTS was acceptable. In production at 2 TB, add OpenSearch or another Lucene/BM25 engine.

Use OpenSearch for:

- BM25 keyword search
- exact-ish text retrieval
- analyzers/synonyms
- code symbol search
- phrase search
- field boosts
- multi-field sparse scoring
- retrieval diagnostics

Production retrieval should usually run:

```text
Qdrant dense top 100
+ OpenSearch BM25 top 100
+ optional graph expansion
+ RRF/weighted fusion
+ post-ACL verification
+ reranker top 20 -> top 5/10 context pack
```

### 5.4 Object storage: durable originals and snapshots

Use object storage for:

- original uploaded files
- parsed artifacts
- normalized text
- extraction manifests
- large chunk text if not stored inline
- Qdrant snapshots
- Postgres WAL/base backups
- OpenSearch snapshots
- exports
- customer portability packages

Production requirement:

- Object storage must be versioned where possible.
- Enable retention/object lock for backup buckets where supported.
- Use lifecycle rules for old snapshots.
- Keep one offsite backup copy outside the primary failure domain.

---

## 6. Security changes

### 6.1 Security becomes a first-class subsystem

Production-ready SVS must ship with:

- tenant isolation modes
- security classification levels 0–5
- RBAC + ABAC
- source-system ACL inheritance
- per-document ACLs
- per-chunk inherited security labels
- API-key scopes
- service-account scopes
- policy decision logs
- break-glass admin workflow
- audit exports
- deletion/retention workflows

### 6.2 Isolation modes

| Mode | Use case | Storage design |
|---|---|---|
| Shared collection + filters | public/low-risk docs | cheapest, not for sensitive tenants |
| Collection per tenant | default SMB/business | good boundary, simple operations |
| Collection per tenant/security tier | confidential departments | stronger blast-radius control |
| Cluster per enterprise tenant | regulated/high-value customers | best isolation, higher cost |
| Air-gapped/self-contained deployment | strict enterprise/private data | appliance-style install |

Default production: **collection per business instance plus security-tier collections for confidential data**.

### 6.3 Required retrieval security pipeline

```text
1. Authenticate user/API key.
2. Resolve org, tenant, business instance, roles, groups, policies.
3. Build RetrievalScope.
4. Select allowed indexes/collections only.
5. Apply pre-search filters in Qdrant/OpenSearch.
6. Retrieve candidates.
7. Verify every result against Postgres ACL source of truth.
8. Build context pack from only authorized chunks.
9. Redact/transform sensitive fields as required.
10. Verify final answer citations and classification boundary.
11. Write audit event.
```

### 6.4 Encryption and secrets

Production requirements:

- TLS everywhere externally.
- mTLS or private-network service auth internally.
- LUKS or equivalent disk encryption on dedicated servers.
- Per-environment secrets stored in Vault/SOPS/age or injected through a
  documented `envref://KEY` runtime contract, not plaintext `.env` files in
  production.
- Production env files carry only secret references for passwords, API keys,
  access keys, peppers, tokens, and production DSNs. `prod-env-preflight.py`
  validates `sops://...#KEY`, `age://...#KEY`, `vault://...#KEY`, and
  `envref://KEY` references, rejects DSNs with embedded passwords, and reports
  variable names only.
- Rotation and rollback handling live in `runbooks/encrypted-secrets.md`.
  Repo-buildable validation does not claim live SOPS/Vault access, DNS/TLS, or
  customer-host secret-manager proof.
- API keys stored hashed, never reversible.
- Embedding provider keys scoped per environment and rotated.
- Customer-managed key support later for enterprise tenants.

---

## 7. API changes for production completeness

### 7.1 All mutating APIs need production behavior

Every `POST`, `PUT`, `PATCH`, and `DELETE` must support:

- idempotency key
- request ID
- audit correlation ID
- actor ID
- tenant/business-instance scope
- permission check
- rate-limit bucket
- structured error code
- pagination for list endpoints
- async job option for slow operations

### 7.2 Add production API areas

```text
/api/v1/orgs
/api/v1/business-instances
/api/v1/users
/api/v1/groups
/api/v1/roles
/api/v1/policies
/api/v1/api-keys
/api/v1/service-accounts
/api/v1/security/classifications
/api/v1/sources
/api/v1/connectors
/api/v1/documents
/api/v1/chunks
/api/v1/vector-stores
/api/v1/indexes
/api/v1/retrieval/search
/api/v1/retrieval/context-pack
/api/v1/retrieval/explain
/api/v1/retrieval/evaluate
/api/v1/retention/policies
/api/v1/deletions
/api/v1/audit/events
/api/v1/audit/exports
/api/v1/usage
/api/v1/quotas
/api/v1/billing-ledger
/api/v1/backups
/api/v1/restores
/api/v1/health/live
/api/v1/health/ready
/api/v1/health/dependencies
/api/v1/ops/reindex
/api/v1/ops/reembed
/api/v1/ops/snapshots
/api/v1/ops/dr-status
```

### 7.3 Retrieval explain API

Production systems need explainability.

`POST /api/v1/retrieval/explain` should return:

```json
{
  "query_id": "qry_...",
  "retrieval_profile_id": "rp_...",
  "security_scope_summary": {
    "tenant_id": "tenant_...",
    "business_instance_id": "bi_...",
    "max_security_level": 3,
    "groups_count": 8
  },
  "dense": {
    "collection": "qdrant_bi_..._confidential_v3",
    "top_k": 100,
    "candidate_count": 100
  },
  "sparse": {
    "index": "os_bi_..._chunks_v3",
    "candidate_count": 100
  },
  "fusion": {
    "method": "rrf",
    "rrf_k": 60
  },
  "acl": {
    "candidates_before_acl": 146,
    "denied": 3,
    "final": 20
  },
  "rerank": {
    "enabled": true,
    "model": "bge-reranker-v2-m3",
    "input_count": 20,
    "output_count": 8
  }
}
```

---

## 8. Ingestion changes

### 8.1 Ingestion must be idempotent and versioned

Every ingestion job needs:

- source ID
- source connector ID
- source content hash
- parser profile version
- chunking profile version
- embedding profile version
- ACL version
- classification version
- status transitions
- retry count
- dead-letter state
- audit event

### 8.2 Never overwrite live indexes blindly

For production reindexing:

```text
current alias: bi_expert_ai_services_docs -> collection bi_expert_ai_services_docs_v12
new collection: bi_expert_ai_services_docs_v13_building
run ingestion/reembedding
run evals and spot checks
mark v13 ready
atomically update alias to v13
keep v12 for rollback window
expire v12 after retention window
```

### 8.3 Required ingestion states

```text
RECEIVED
VALIDATING_SOURCE
STORING_ORIGINAL
PARSING
CLASSIFYING
SCANNING_SECRETS
SCANNING_PROMPT_INJECTION
CHUNKING
EMBEDDING_QUEUED
EMBEDDING
INDEXING_DENSE
INDEXING_SPARSE
VERIFYING_INDEX
READY
FAILED_RETRYABLE
FAILED_PERMANENT
QUARANTINED
DELETED
```

---

## 9. Retrieval changes

### 9.1 Production retrieval planner

Retrieval should not be a hardcoded vector search. Build a query planner:

```text
input query
  -> classify query intent
  -> choose retrieval profile
  -> choose indexes/collections allowed by security scope
  -> expand query if enabled
  -> run dense retrieval
  -> run sparse retrieval
  -> run graph/entity retrieval if enabled
  -> fuse candidates
  -> post-ACL verify
  -> rerank
  -> expand neighboring chunks/parent sections
  -> build context pack
  -> cite every chunk
  -> write query/retrieval audit
```

### 9.2 Retrieval profiles by data type

```yaml
profiles:
  markdown_docs:
    dense: qdrant
    sparse: opensearch
    fusion: rrf
    chunk_expansion: heading_parent_and_neighbors
    rerank: true

  code_search:
    dense: qdrant_symbol_embeddings
    sparse: opensearch_code_analyzer
    fusion: weighted
    chunking: ast_symbol_aware
    exact_symbol_boost: true

  customer_support:
    dense: qdrant
    sparse: opensearch
    recency_boost: true
    product_version_filter: true
    rerank: true

  legal_contracts:
    dense: qdrant
    sparse: opensearch_phrase
    require_citations: true
    max_quote_tokens: strict
    security_level_minimum: confidential
```

---

## 10. Observability changes

Production-ready means you can see the system fail before customers do.

Required dashboards:

- API latency/error rate by tenant and endpoint
- ingestion jobs by state
- embedding provider latency/cost/error rate
- Qdrant query latency, write latency, collection size, optimizer pressure
- OpenSearch indexing/search latency, heap, disk watermarks
- Postgres replication lag, locks, slow queries, WAL growth, bloat
- object storage PUT/GET errors and backup freshness
- ACL-denied retrieval attempts
- cross-tenant anomaly detector
- retrieval quality evals over time
- cost per business instance

Required alerts:

- cross-tenant ACL anomaly
- failed backup
- stale WAL archive
- Postgres replica lag
- Qdrant shard/replica unavailable
- OpenSearch disk watermark
- object backup lag
- ingestion queue age
- embedding provider error spike
- p95 retrieval latency breach
- unauthorized admin action
- restore drill overdue

---

## 11. Backup, restore, and disaster recovery changes

### 11.1 Backup hierarchy

| Data | Backup method | Frequency |
|---|---|---:|
| Postgres metadata | WAL archive + base backup | continuous WAL, daily base |
| Qdrant | collection snapshots + rebuild-from-source | hourly/daily depending class |
| OpenSearch | snapshots | daily/hourly for hot tenants |
| Object storage | versioning + replication/offsite | continuous/daily |
| Config/secrets | encrypted GitOps backup | every change |
| Audit exports | immutable object storage | daily |

### 11.2 Restore drills

Monthly:

- restore Postgres to staging from backup
- verify tenants/users/docs/chunks/audit
- restore one Qdrant collection snapshot
- restore one OpenSearch index snapshot
- run retrieval evals against restored environment

Quarterly:

- full new-environment rebuild from object storage + Postgres backup
- simulate loss of one Qdrant node
- simulate failed Postgres primary
- simulate accidental tenant deletion and recovery

### 11.3 Disaster mode behavior

If Qdrant is unavailable:

```text
fallback to OpenSearch BM25 + cached context packs + degraded semantic answers disabled
```

If OpenSearch is unavailable:

```text
fallback to Qdrant dense retrieval + exact metadata filters
```

If embedding provider is unavailable:

```text
accept uploads, queue embeddings, serve existing indexes
```

If object storage is unavailable:

```text
serve existing indexed chunks, pause ingestion requiring original writes
```

---

## 12. CI/CD and release changes

Production repo additions:

```text
.github/workflows/
  ci.yml
  security-scan.yml
  integration-tests.yml
  migration-tests.yml
  load-tests.yml
  image-build.yml
  deploy-staging.yml
  deploy-prod-canary.yml

charts/
  svs-api/
  svs-worker/
  svs-admin/
  svs-observability/

ansible/
  inventories/prod/
  roles/base-hardening/
  roles/docker-or-containerd/
  roles/k3s/
  roles/postgres-patroni/
  roles/qdrant/
  roles/opensearch/
  roles/backup-agent/

terraform/
  hetzner-cloud/
  hetzner-robot-dedicated/
  dns/
  object-storage/

runbooks/
  postgres-failover.md
  qdrant-node-replace.md
  opensearch-watermark.md
  tenant-restore.md
  backup-restore-drill.md
  security-incident.md
  api-key-rotation.md
  reembed-migration.md

load-tests/
  ingestion-k6.js
  retrieval-k6.js
  tenant-isolation-test.py

evals/
  golden-query-sets/
  retrieval-regression/
  security-red-team/
```

Release rules:

- no direct prod deploys from laptop
- every DB migration tested against production-like snapshot
- backward-compatible migrations first; destructive migrations later
- canary one tenant/business instance first
- rollback path documented for every release
- index schema migrations use blue/green index aliases

Migration discipline:

- `scripts/migrate.sh` is the only supported schema entrypoint and runs `alembic upgrade head`.
- The initial Alembic baseline preserves the existing SQL and role-management semantics but is intentionally not destructively reversible.
- For a failed forward migration, restore the last verified database backup or snapshot, then rerun the release after fixing the revision. Once data has crossed a revision boundary, ship a new backward-compatible forward-fix revision; do not edit an applied revision or replay files from `db/migrations` directly.
- The legacy `db/migrations` files remain frozen source material. The drift check fails if they change, if a new legacy file is added, or if a raw Compose/initdb or shell loop bypass is reintroduced.

---

## 13. Production build sequence, not MVP

This is a production-first sequence. Each stage is shippable but not framed as a throwaway MVP.

### Stage 1 — Production foundation

- Repo layout
- Terraform/Ansible/k8s skeleton
- CI/CD
- secrets management
- service identity
- logging/metrics/tracing
- Postgres HA design
- Qdrant/OpenSearch cluster design
- object storage and backups

### Stage 2 — Tenancy and security

- orgs, business instances, users, groups, roles
- API keys/service accounts
- RBAC/ABAC policy engine
- security levels
- audit ledger
- tenant isolation test suite

### Stage 3 — Ingestion platform

- source registry
- object storage originals
- content hashing/dedupe
- parser abstraction
- chunk registry
- classification/PII/secrets scans
- ingestion job state machine
- dead-letter workflows

### Stage 4 — Indexing platform

- embedding provider abstraction
- batch embedding workers
- index versioning
- Qdrant dense indexing
- OpenSearch sparse indexing
- blue/green collection/index aliases
- snapshot export

### Stage 5 — Retrieval platform

- retrieval planner
- security-scoped filters
- dense retrieval
- sparse retrieval
- hybrid fusion
- post-ACL verification
- context packs
- explain endpoint
- citation verification

### Stage 6 — Operations and DR

- backup automation
- restore automation
- restore drills
- monitoring dashboards
- alerts
- rate limits/quotas
- cost ledger
- retention/deletion workflows

### Stage 7 — OpenAI-compatible surface

- vector stores
- vector-store files
- batches
- search
- attributes
- file content retrieval
- expiration policies
- compatibility tests

### Stage 8 — Enterprise readiness

- tenant-dedicated clusters
- customer-managed keys
- regional data policies
- immutable audit exports
- SSO/SAML/OIDC
- SCIM provisioning
- compliance evidence reports

---

## 14. Final production recommendation

For the Expert AI Services goal, build SVS as a **production appliance cluster**, not a single VPS.

The first serious target should be:

```text
3 data nodes with local NVMe
3 PostgreSQL HA nodes
3 app/control nodes
object storage with offsite copy
Qdrant dense retrieval
OpenSearch sparse retrieval
Postgres metadata/ACL/audit source of truth
blue/green index versions
pre-search filtering + post-search ACL verification
continuous backups + restore drills
```

A one-server install can still exist as `deployment_mode=solo`, but it should be labeled honestly:

```text
solo = production-capable for private/low-risk workloads, not HA
ha-single-region = first business-critical production target
enterprise-isolated = high-security customer target
```
