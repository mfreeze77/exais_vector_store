# SVS Micro-Production Cells

This supplement changes the production architecture from one large shared platform into a cell-based product model. The goal is to let the same base product run many isolated business/user instances while still supporting controlled upgrades, rollbacks, backups, security, per-instance API keys, and per-instance retrieval behavior.

## 1. Core idea

A micro-production instance is a small production data plane with its own identity, configuration, storage boundaries, quotas, API keys, retrieval profiles, audit trail, and backup/restore lifecycle.

The base product is immutable. Instances are mutable only through configuration, secrets, data, migrations, and deployment records.

```text
Base SVS Product
  ├── svs-api image
  ├── svs-worker image
  ├── svs-retriever image
  ├── svs-admin image
  ├── svs-migrator image
  ├── compose templates
  ├── schema migrations
  ├── policy templates
  └── instance controller

Instance Configuration
  ├── tenant/business/user identifiers
  ├── domains
  ├── quotas
  ├── security mode
  ├── embedding providers
  ├── storage backend
  ├── retrieval profiles
  ├── backup policy
  ├── retention policy
  └── secrets references
```

The correct production pattern is not "copy and modify the app for every customer." The correct pattern is:

```text
single versioned product image set
+ per-instance manifest
+ per-instance secrets
+ per-instance data plane
+ controlled deployment/upgrade orchestrator
```

## 2. Definitions

| Term | Meaning |
|---|---|
| Product | The versioned SVS software: APIs, workers, migrations, retrieval engine, admin UI, SDKs. |
| Image set | A release group of container images with one version, such as `svs-api:1.8.4`, `svs-worker:1.8.4`, `svs-migrator:1.8.4`. |
| Control plane | The management layer that knows which instances exist, where they run, what version they use, and how to deploy/upgrade them. |
| Data plane | The actual per-instance runtime where ingestion, storage, indexing, search, and retrieval happen. |
| Cell | A deployment boundary. A cell may hold one instance or multiple small instances. |
| Business instance | A production instance for one company, organization, customer, project, or internal business unit. |
| User vault | An isolated personal retrieval area for one user. Usually this should be a scoped sub-instance, not a full VPS. |
| Dedicated instance | A full stack dedicated to one business or one high-value user. |
| Shared-cell instance | A business/user instance sharing host capacity with other instances but separated by database, collections, buckets, keys, and network/policy boundaries. |

## 3. Isolation ladder

Use an isolation ladder instead of treating every customer the same.

| Tier | Name | Use case | Isolation model | Cost | Recommended default? |
|---:|---|---|---|---:|---|
| 0 | Logical tenant | Tiny/internal users | Shared API, shared DB, tenant_id filters, shared vector collection with strict payload filters | Lowest | Only for low-risk/internal test data |
| 1 | Shared-cell instance | Small businesses/users | Shared host, separate DB/schema, separate Qdrant collections, separate object bucket/prefix, separate API keys | Low | Yes for small paid instances |
| 2 | Business micro-cell | Normal business instance | Dedicated compose project, dedicated databases/collections/buckets, shared physical VPS or dedicated VPS | Medium | Best default for paid business instances |
| 3 | Dedicated VPS cell | Higher-value business/customer | Full Docker Compose stack on its own VPS/dedicated host | Higher | Yes for serious customers |
| 4 | Dedicated server cell | Heavy retrieval/security | Full stack on dedicated NVMe server | High | Use for 500GB+ retrieval or confidential data |
| 5 | HA isolated cell | Regulated/enterprise | Multi-node data plane, replicated DB/vector/search/object storage | Highest | Use for enterprise/regulatory customers |

Default recommendation:

```text
Per business: Tier 2 or Tier 3.
Per normal user: scoped user vault inside Tier 1 or Tier 2.
Per high-value/private user: Tier 3.
Per regulated/high-value business: Tier 4 or Tier 5.
```

Do not create a full VPS per normal user unless they are paying for isolation or the data sensitivity demands it.

## 4. Product release model

Never deploy anonymous `latest` to production.

Use immutable, semver-tagged, digest-pinned image sets:

```text
ghcr.io/expertaiservices/exai-vector-store-api:1.8.4
ghcr.io/expertaiservices/exai-vector-store-worker:1.8.4
ghcr.io/expertaiservices/exai-vector-store-retriever:1.8.4
ghcr.io/expertaiservices/exai-vector-store-admin:1.8.4
ghcr.io/expertaiservices/exai-vector-store-migrator:1.8.4
```

For production deployment records, store the resolved digest too:

```yaml
product_version: 1.8.4
images:
  api: ghcr.io/expertaiservices/exai-vector-store-api:1.8.4@sha256:...
  worker: ghcr.io/expertaiservices/exai-vector-store-worker:1.8.4@sha256:...
  retriever: ghcr.io/expertaiservices/exai-vector-store-retriever:1.8.4@sha256:...
  migrator: ghcr.io/expertaiservices/exai-vector-store-migrator:1.8.4@sha256:...
```

The instance manifest should not contain app code. It should contain only settings.

## 5. Repository layout

```text
svs/
  apps/
    api/
    worker/
    retriever/
    admin/
    migrator/
    instance-agent/

  packages/
    sdk-js/
    sdk-python/
    shared-types/
    policy-engine/
    retrieval-core/

  db/
    migrations/
    seeds/
    rls/

  infra/
    docker/
      base/
        compose.base.yml
        compose.data.yml
        compose.observability.yml
      instance/
        compose.instance.yml
        compose.business-cell.yml
        compose.dedicated.yml
      caddy/
        Caddyfile.template
      systemd/
        svs-instance-agent.service
    terraform/
      hetzner-cloud/
      hetzner-dedicated/
      dns/
    ansible/
      roles/
        base-hardening/
        docker-host/
        svs-cell/
        backup-agent/

  instances/
    _templates/
      business-small.instance.yaml
      business-dedicated.instance.yaml
      user-vault.instance.yaml
    expert-ai-services/
      prod/
        instance.yaml
        compose.override.yml
        policies/
        retrieval-profiles/
        secrets.sops.yaml
      staging/
        instance.yaml
    mfrieson-vault/
      prod/
        instance.yaml

  control-plane/
    api/
    ui/
    deployer/
    scheduler/

  ops/
    runbooks/
    checklists/
    backups/
    restore-drills/
    incident-response/

  tests/
    integration/
    tenancy/
    security/
    migration/
    load/
    retrieval-evals/
```

## 6. Instance manifest

Every deployed instance should be declared by a manifest.

```yaml
apiVersion: svs/v1
kind: Instance
metadata:
  instanceId: inst_expert_ai_services_prod
  slug: expert-ai-services-prod
  environment: production
  ownerTenantId: ten_expert_ai_services
  businessInstanceId: biz_expert_ai_services_main
  labels:
    customer_tier: business
    isolation: business_micro_cell
    region: fsn1

product:
  version: 1.8.4
  releaseChannel: stable
  autoUpgrade: false
  maintenanceWindow: "Sun 02:00-04:00 America/Chicago"

runtime:
  deploymentMode: business_micro_cell
  host:
    provider: hetzner
    hostId: svs-cell-fsn1-003
    dockerContext: svs-cell-fsn1-003
  composeProjectName: svs_expert_ai_services_prod
  domain:
    api: api.expertaiservices.com
    admin: admin.expertaiservices.com

resources:
  api:
    replicas: 2
    cpuLimit: "2"
    memoryLimit: 2g
  worker:
    replicas: 2
    cpuLimit: "4"
    memoryLimit: 8g
  retriever:
    replicas: 2
    cpuLimit: "4"
    memoryLimit: 8g
  storageQuotaGb: 500
  vectorQuotaGb: 250
  monthlyRetrievalLimit: 1000000

security:
  maxSecurityLevel: 3
  isolationTier: 2
  requirePostRetrievalAclCheck: true
  requireCitations: true
  redactPiiBeforeModel: true
  logRawQueries: false
  allowedAuthModes:
    - api_key
    - jwt
  secretProvider: sops_age
  encryption:
    disk: host_luks
    appSecrets: sops_age
    objectStorage: server_side_encryption

storage:
  postgres:
    mode: shared_cluster_dedicated_db
    database: svs_inst_expert_ai_services_prod
    usernameRef: secrets/postgres/user
    passwordRef: secrets/postgres/password
  qdrant:
    mode: shared_cluster_dedicated_collections
    collectionPrefix: expert_ai_services_prod_
    apiKeyRef: secrets/qdrant/api_key
  opensearch:
    mode: shared_cluster_dedicated_indexes
    indexPrefix: expert_ai_services_prod_
  object:
    mode: bucket_prefix
    bucket: exai-vector-store-prod-fsn1
    prefix: instances/expert-ai-services-prod/
    accessKeyRef: secrets/object/access_key
    secretKeyRef: secrets/object/secret_key

embedding:
  defaultProvider: openai
  profiles:
    markdown_docs_v1:
      provider: openai
      model: text-embedding-3-small
      dimensions: 1536
    code_symbols_v1:
      provider: openai
      model: text-embedding-3-large
      dimensions: 3072

retrieval:
  defaultProfile: hybrid_secure_v1
  profiles:
    hybrid_secure_v1:
      denseTopK: 80
      sparseTopK: 80
      fusion: rrf
      rerankTopN: 20
      finalTopK: 8
      expandNeighbors: true
      maxContextTokens: 24000

backup:
  schedule: "0 3 * * *"
  retentionDays: 30
  offsite: true
  include:
    postgres: true
    qdrantSnapshots: true
    opensearchSnapshots: true
    objectManifest: true
    instanceManifest: true

retention:
  deletedDocumentPurgeDays: 7
  auditRetentionDays: 365
  rawQueryRetentionDays: 0
```

## 7. Compose template for a micro-production instance

Use the same compose template for every instance. Let the environment file and manifest select the instance.

```yaml
name: ${COMPOSE_PROJECT_NAME}

networks:
  svs_internal:
    name: ${COMPOSE_PROJECT_NAME}_internal
    internal: true
  svs_edge:
    name: ${COMPOSE_PROJECT_NAME}_edge

volumes:
  api_tmp:
  worker_tmp:

services:
  api:
    image: ${SVS_REGISTRY}/svs-api:${SVS_VERSION}
    restart: unless-stopped
    env_file:
      - ./.env.instance
    environment:
      SVS_INSTANCE_ID: ${SVS_INSTANCE_ID}
      SVS_INSTANCE_MANIFEST: /run/svs/instance.yaml
    volumes:
      - ./instance.yaml:/run/svs/instance.yaml:ro
      - api_tmp:/tmp
    networks:
      - svs_internal
      - svs_edge
    healthcheck:
      test: ["CMD", "wget", "-qO-", "http://127.0.0.1:8080/healthz"]
      interval: 15s
      timeout: 5s
      retries: 5
    security_opt:
      - no-new-privileges:true
    read_only: true

  worker:
    image: ${SVS_REGISTRY}/svs-worker:${SVS_VERSION}
    restart: unless-stopped
    env_file:
      - ./.env.instance
    environment:
      SVS_INSTANCE_ID: ${SVS_INSTANCE_ID}
      SVS_WORKER_QUEUES: ingest,embed,index,backup
    volumes:
      - ./instance.yaml:/run/svs/instance.yaml:ro
      - worker_tmp:/tmp
    networks:
      - svs_internal
    depends_on:
      api:
        condition: service_healthy
    security_opt:
      - no-new-privileges:true
    read_only: true

  retriever:
    image: ${SVS_REGISTRY}/svs-retriever:${SVS_VERSION}
    restart: unless-stopped
    env_file:
      - ./.env.instance
    environment:
      SVS_INSTANCE_ID: ${SVS_INSTANCE_ID}
    volumes:
      - ./instance.yaml:/run/svs/instance.yaml:ro
    networks:
      - svs_internal
    security_opt:
      - no-new-privileges:true
    read_only: true

  migrator:
    image: ${SVS_REGISTRY}/svs-migrator:${SVS_VERSION}
    profiles: ["migration"]
    env_file:
      - ./.env.instance
    volumes:
      - ./instance.yaml:/run/svs/instance.yaml:ro
    networks:
      - svs_internal
    command: ["svs-migrate", "up", "--instance", "${SVS_INSTANCE_ID}"]
```

For a dedicated VPS cell, the compose file also includes Postgres, Qdrant, OpenSearch, Redis/Valkey, MinIO, Caddy, and observability. For a shared-cell instance, those stateful services are provided by the host/cell and the instance only runs API/workers/retriever with dedicated credentials and namespaces.

## 8. Per-instance environment file

```bash
COMPOSE_PROJECT_NAME=svs_expert_ai_services_prod
SVS_INSTANCE_ID=inst_expert_ai_services_prod
SVS_VERSION=1.8.4
SVS_REGISTRY=ghcr.io/expertaiservices
SVS_ENV=production
SVS_CONFIG_MODE=manifest
SVS_LOG_LEVEL=info
SVS_PUBLIC_API_BASE_URL=https://api.expertaiservices.com
SVS_ADMIN_BASE_URL=https://admin.expertaiservices.com
```

Sensitive values should be injected from a secret manager or decrypted at deploy time. Do not commit plaintext production secrets.

## 9. Host layout

A cell host can run many micro instances.

```text
/srv/svs/
  cell.yaml
  bin/
    svsctl
    svs-instance-agent
  instances/
    expert-ai-services-prod/
      instance.yaml
      .env.instance
      compose.yml
      policies/
      backups/
      logs/
    beta-prod/
      instance.yaml
      .env.instance
      compose.yml
  shared/
    caddy/
    backup-agent/
    monitoring-agent/
```

Each instance gets a separate Docker Compose project name. That gives separate container names, networks, and volumes. For stronger isolation, move the instance to its own VPS or dedicated server cell.

## 10. Control-plane data model

```sql
create table control_instances (
  id text primary key,
  slug text not null unique,
  environment text not null,
  owner_tenant_id text not null,
  business_instance_id text,
  user_vault_owner_id text,
  isolation_tier int not null,
  deployment_mode text not null,
  host_id text,
  compose_project_name text,
  domain_api text,
  domain_admin text,
  current_product_version text not null,
  desired_product_version text,
  release_channel text not null default 'stable',
  auto_upgrade boolean not null default false,
  max_security_level int not null default 2,
  status text not null default 'provisioning',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table control_instance_deployments (
  id text primary key,
  instance_id text not null references control_instances(id),
  from_version text,
  to_version text not null,
  image_set jsonb not null,
  migration_plan jsonb not null,
  status text not null,
  started_at timestamptz,
  completed_at timestamptz,
  rollback_deployment_id text,
  operator_user_id text,
  created_at timestamptz not null default now()
);

create table control_hosts (
  id text primary key,
  provider text not null,
  region text not null,
  docker_context text,
  public_ip inet,
  private_ip inet,
  capacity_cpu int,
  capacity_memory_gb int,
  capacity_storage_gb int,
  status text not null,
  created_at timestamptz not null default now()
);

create table control_instance_backups (
  id text primary key,
  instance_id text not null references control_instances(id),
  backup_type text not null,
  product_version text not null,
  manifest_hash text not null,
  object_location text not null,
  includes jsonb not null,
  restore_tested_at timestamptz,
  status text not null,
  created_at timestamptz not null default now()
);
```

## 11. Control-plane API

### Instance lifecycle

```http
POST   /control/v1/instances
GET    /control/v1/instances
GET    /control/v1/instances/{instance_id}
PATCH  /control/v1/instances/{instance_id}
DELETE /control/v1/instances/{instance_id}
```

### Provisioning

```http
POST /control/v1/instances/{instance_id}/provision
POST /control/v1/instances/{instance_id}/deprovision
POST /control/v1/instances/{instance_id}/pause
POST /control/v1/instances/{instance_id}/resume
```

### Deployment and update

```http
POST /control/v1/instances/{instance_id}/deployments
GET  /control/v1/instances/{instance_id}/deployments
GET  /control/v1/deployments/{deployment_id}
POST /control/v1/deployments/{deployment_id}/approve
POST /control/v1/deployments/{deployment_id}/cancel
POST /control/v1/deployments/{deployment_id}/rollback
```

### Upgrade planning

```http
POST /control/v1/instances/{instance_id}/upgrade-plan
POST /control/v1/instances/{instance_id}/upgrade
POST /control/v1/instances/{instance_id}/migrate
POST /control/v1/instances/{instance_id}/smoke-test
```

### Backups and restore

```http
POST /control/v1/instances/{instance_id}/backups
GET  /control/v1/instances/{instance_id}/backups
POST /control/v1/backups/{backup_id}/restore-plan
POST /control/v1/backups/{backup_id}/restore
POST /control/v1/backups/{backup_id}/verify
```

### Secrets and keys

```http
POST   /control/v1/instances/{instance_id}/api-keys
GET    /control/v1/instances/{instance_id}/api-keys
DELETE /control/v1/instances/{instance_id}/api-keys/{key_id}
POST   /control/v1/instances/{instance_id}/secrets/rotate
```

### Health and operations

```http
GET  /control/v1/instances/{instance_id}/health
GET  /control/v1/instances/{instance_id}/metrics
GET  /control/v1/instances/{instance_id}/logs
POST /control/v1/instances/{instance_id}/diagnostics
POST /control/v1/instances/{instance_id}/repair
```

## 12. Data-plane API per instance

Every instance exposes an API with instance-specific API keys and/or JWTs.

```http
POST   /v1/vector_stores
GET    /v1/vector_stores
GET    /v1/vector_stores/{vector_store_id}
PATCH  /v1/vector_stores/{vector_store_id}
DELETE /v1/vector_stores/{vector_store_id}

POST   /v1/vector_stores/{vector_store_id}/files
GET    /v1/vector_stores/{vector_store_id}/files
GET    /v1/vector_stores/{vector_store_id}/files/{file_id}
DELETE /v1/vector_stores/{vector_store_id}/files/{file_id}

POST   /v1/vector_stores/{vector_store_id}/file_batches
GET    /v1/vector_stores/{vector_store_id}/file_batches/{batch_id}
POST   /v1/vector_stores/{vector_store_id}/file_batches/{batch_id}/cancel

POST   /v1/vector_stores/{vector_store_id}/search
POST   /v1/retrieval/context-pack
POST   /v1/ingest/files
POST   /v1/ingest/markdown
POST   /v1/ingest/url
POST   /v1/ingest/git
POST   /v1/documents/{document_id}/reindex
POST   /v1/documents/{document_id}/delete

GET    /v1/jobs/{job_id}
GET    /v1/audit/events
GET    /v1/usage
```

Every call must resolve:

```text
instance_id
actor_id
tenant_id
business_instance_id
user_id or service_account_id
security_scope
rate_limit_bucket
retrieval_profile
```

## 13. `svsctl` CLI

```bash
svsctl instance init expert-ai-services-prod --template business-small
svsctl instance render expert-ai-services-prod
svsctl instance validate expert-ai-services-prod
svsctl instance provision expert-ai-services-prod
svsctl instance deploy expert-ai-services-prod --version 1.8.4
svsctl instance upgrade-plan expert-ai-services-prod --to 1.9.0
svsctl instance upgrade expert-ai-services-prod --to 1.9.0 --approve
svsctl instance rollback expert-ai-services-prod --deployment dep_123
svsctl instance backup expert-ai-services-prod
svsctl instance restore expert-ai-services-prod --backup bkp_123 --target expert-ai-services-restore-test
svsctl instance smoke-test expert-ai-services-prod
svsctl instance health expert-ai-services-prod
svsctl fleet list
svsctl fleet upgrade --channel stable --max-concurrent 3 --exclude-tier 4,5
```

## 14. Update flow

Production updates must be controlled and reversible.

```text
1. Developer merges code to main.
2. CI builds image set.
3. CI runs unit, integration, migration, tenancy, retrieval, and security tests.
4. CI produces SBOM/provenance and signs images if signing is enabled.
5. CI pushes versioned images to registry.
6. Control plane creates release record.
7. A staging instance upgrades first.
8. Smoke tests and retrieval regression tests run.
9. Canary production instances upgrade.
10. Remaining instances upgrade by maintenance window and risk tier.
11. Each instance records deployment result and current version.
```

Do not push code directly to the VPS as the normal deployment path. Push images to a registry. VPS hosts should pull the approved image version and apply the rendered instance manifest.

Emergency path:

```text
build image tar
copy to host
load image
run svsctl deploy with explicit digest
record emergency deployment
replace with registry release later
```

## 15. Per-instance upgrade algorithm

```text
1. Lock instance deployment.
2. Fetch current deployment record.
3. Validate target version compatibility.
4. Render new compose files from manifest.
5. Pull target images.
6. Run preflight health checks.
7. Create backup or verify recent valid backup.
8. Run migrator in dry-run mode if supported.
9. Stop write-heavy workers.
10. Run schema migrations.
11. Run index migrations/reindex jobs if needed.
12. Start new containers.
13. Run health checks.
14. Run smoke retrieval query set.
15. Flip traffic if using blue/green.
16. Mark deployment successful.
17. Unlock instance.
```

If the migration is destructive or not reversible, require an explicit backup checkpoint and manual approval for high-security tiers.

## 16. Blue/green for micro-production

For small instances, in-place updates are acceptable if backups are good.

For important instances, use blue/green:

```text
current: expert-ai-services-prod-blue
new:     expert-ai-services-prod-green

1. Green starts with new image version.
2. Green connects to copied/staged or migrated state as appropriate.
3. Smoke tests run against green.
4. Caddy/router switches traffic to green.
5. Blue stays warm for rollback window.
6. Blue is destroyed after retention window.
```

Use blue/green for:

```text
security tier >= 3
regulated customers
schema-breaking migrations
embedding model migrations
major retrieval engine changes
paid customers with uptime expectations
```

## 17. Push-to-hub vs push-to-VPS

Recommended:

```text
CI/CD -> registry -> VPS pulls image -> deploy agent runs compose
```

Not recommended as the main path:

```text
local machine -> ssh -> build on VPS -> run latest
```

The registry path gives traceability, reproducibility, rollback, and fleet updates. The VPS should be a runtime target, not the build system.

## 18. Per-business versus per-user

### Per-business

Usually create a business micro-production instance.

```text
business = instance boundary
users = auth scopes inside that instance
teams/departments = ACL scopes inside that instance
projects = knowledge bases inside that instance
```

### Per-user

Usually create a user vault inside a business or shared cell.

```text
user = owner scope
vault = vector store / knowledge base
ACL = user-only by default
storage = bucket prefix / collection prefix
API = same instance API with user-scoped key/JWT
```

Create a dedicated user instance only when:

```text
user pays for dedicated isolation
user has very sensitive data
user needs private embedding model/provider settings
user needs separate backup/retention/legal policy
user has large storage/retrieval load
```

## 19. Micro-production sizing guide

These are starting points. Measure actual chunk count, vector dimensions, query rate, ingestion rate, and index overhead before final procurement.

| Instance type | Retrieval corpus | Suggested deployment | Starting resources |
|---|---:|---|---|
| User vault | 1–10 GB | shared-cell scoped vault | no dedicated VPS |
| Heavy user vault | 10–50 GB | shared-cell dedicated collections or tiny VPS | 2–4 vCPU, 8–16 GB RAM, 100–250 GB NVMe |
| Small business | 10–100 GB | business micro-cell | 4–8 vCPU, 16–32 GB RAM, 250–750 GB NVMe |
| Normal business | 100–500 GB | dedicated VPS or dedicated cell | 8–16 vCPU, 64–128 GB RAM, 1–2 TB NVMe |
| Large business | 500 GB–2 TB | dedicated server cell | 16–32+ threads, 128–256 GB RAM, 4–8 TB local NVMe usable |
| Enterprise | 2 TB+ or strict uptime | HA isolated cell | multi-node cluster |

For a 2 TB fleet, do not allocate 2 TB to every micro-production instance. Allocate by quota and pack instances into cells while maintaining restore headroom.

## 20. Fleet packing model

A host should advertise capacity:

```yaml
hostId: svs-cell-fsn1-003
capacity:
  cpuThreads: 32
  memoryGb: 128
  localNvmeGb: 3500
  volumeGb: 0
  maxInstances: 20
  maxSecurityTier: 3
reservations:
  cpuThreads: 8
  memoryGb: 32
  localNvmeGb: 1000
```

The control plane should place instances using constraints:

```text
same tenant cannot share host with forbidden tenant
security tier <= host max tier
required region matches host region
sum reserved storage <= 70% host storage
sum reserved memory <= 75% host memory
high-write instances spread across hosts
backup windows staggered
```

## 21. Security per micro-production instance

Every instance gets:

```text
unique instance_id
unique API keys
unique service credentials
unique database or schema
unique Qdrant collection prefix
unique OpenSearch index prefix
unique object bucket/prefix
unique audit namespace
unique backup namespace
unique retrieval profiles
unique rate limits
unique quotas
```

For stronger tiers, also use:

```text
unique VPS/host
unique LUKS disk keys
unique private network
unique Caddy site/router
unique secrets file/key
unique backup encryption key
```

## 22. Required runtime checks

Every data-plane request must check:

```text
API key/JWT validity
instance status
actor status
tenant/business/user scope
rate limit
quota
security level
source ACL
document ACL
retrieval profile permission
operation permission
```

Every retrieval result must pass:

```text
pre-filter by instance/security metadata
post-search ACL verification against source of truth
document active/not deleted check
retention/legal hold check
output citation check
```

## 23. Backup bundle per instance

A complete instance backup includes:

```text
instance manifest
product version
image digests
postgres dump or base backup reference
qdrant snapshots
opensearch snapshots
object storage manifest
source file checksums
retrieval profile definitions
policy definitions
audit checkpoint
secret references, not plaintext secrets
restore instructions
```

Backup object layout:

```text
s3://exai-vector-store-backups/instances/expert-ai-services-prod/2026-07-06T03-00-00Z/
  manifest.yaml
  deployment.json
  postgres.dump.zst.enc
  qdrant/
    collection_a.snapshot
    collection_b.snapshot
  opensearch/
    snapshot-manifest.json
  object-manifest.json
  checksums.txt
```

## 24. Restore drill

Every production instance should be restorable into a new temporary instance.

```bash
svsctl instance restore expert-ai-services-prod \
  --backup bkp_20260706_030000 \
  --target expert-ai-services-prod-restore-test \
  --no-public-route

svsctl instance smoke-test expert-ai-services-prod-restore-test
svsctl instance destroy expert-ai-services-prod-restore-test --confirm
```

## 25. Observability per instance

Metrics must include labels:

```text
instance_id
tenant_id
business_instance_id
host_id
product_version
retrieval_profile
security_tier
```

Track:

```text
query latency
retrieval latency
embedding latency
indexing latency
ingestion queue depth
failed jobs
Qdrant search errors
OpenSearch errors
Postgres pool saturation
storage quota usage
vector quota usage
API rate limit hits
ACL denies
backup success/failure
upgrade success/failure
```

## 26. Instance agent

Each VPS/cell host should run an instance agent.

Responsibilities:

```text
receive signed deployment commands from control plane
pull approved images
render compose files
run migrations
run docker compose up/down
collect health and metrics
create local backup artifacts
upload backups
rotate logs
report status
refuse unauthorized or unsigned commands
```

Agent API:

```http
GET  /agent/v1/health
GET  /agent/v1/capacity
POST /agent/v1/deploy
POST /agent/v1/upgrade
POST /agent/v1/rollback
POST /agent/v1/backup
POST /agent/v1/restore
POST /agent/v1/smoke-test
GET  /agent/v1/instances
GET  /agent/v1/instances/{id}/status
```

The control plane talks to the agent. Operators should rarely SSH into hosts for routine deployment.

## 27. Release channels

```text
dev        internal only
staging    staging validation instances
canary     small selected production instances
stable     normal production
pinned     manually held version
lts        long-support branch for high-risk customers
```

Upgrade policy by tier:

| Tier | Default upgrade behavior |
|---:|---|
| 0 | automatic stable updates |
| 1 | automatic within maintenance window |
| 2 | automatic minor/patch, manual major |
| 3 | manual approval for major, backup required |
| 4 | manual approval, blue/green preferred |
| 5 | customer/change-window driven |

## 28. What changes from the giant-cluster production plan

The giant-cluster plan optimizes centralization. Micro-production optimizes repeatability and isolation.

| Area | Giant cluster | Micro-production cells |
|---|---|---|
| Deployment | one large platform | many small instances/cells |
| Failure blast radius | larger | smaller |
| Cost per small tenant | lower if shared | slightly higher unless packed well |
| Isolation | logical + cluster policy | logical, per-cell, or dedicated |
| Updates | platform-wide rollout | fleet/canary per instance |
| Backups | cluster plus tenant restore | per-instance backup bundle |
| Migration | global migration concern | versioned per instance |
| Sales model | central SaaS | SaaS, private instance, appliance, managed VPS |

## 29. Strong recommendation

Build the product as a fleet of micro-production cells.

Use this as the default shape:

```text
shared control plane
+ many cell hosts
+ many instance manifests
+ immutable image sets
+ per-instance data boundaries
+ deploy agent on each host
+ registry-based updates
+ per-instance backups/restore
+ per-instance retrieval/security profiles
```

Do not make every user a full VPS by default. Make every business a first-class instance. Make every user a scoped security principal and optionally a user vault. Promote a user or business to a dedicated cell only when cost, scale, sensitivity, or sales tier justifies it.
