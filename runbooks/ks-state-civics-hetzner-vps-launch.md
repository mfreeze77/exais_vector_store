# KS State Civics Hetzner VPS Launch

This runbook turns the generic customer-cell launch process into a concrete
deployment path for the standalone `ks-state-civics` cell.

Use this for one dedicated VPS running one isolated Docker Compose stack:
`exais-vector-store-ks-state-civics`.

## Current Boundary

- The repo has a committed instance manifest:
  `instances/ks-state-civics/instance.yaml`.
- Generic customer-cell launch tooling already exists:
  `runbooks/customer-cell-launch.md`, `scripts/release/generate-cell-env.py`,
  `scripts/release/cell-up.py`, `scripts/release/cell-smoke.py`, and
  `scripts/release/cell-access-proof.py`.
- The local `.release/cells/ks-state-civics/.env.cell` is ignored dev proof
  state. Do not copy it to production.
- Production requires secret references only: `sops://`, `age://`,
  `vault://`, or `envref://`.
- The generic Terraform/Ansible files are scaffolds. Treat Hetzner host
  creation, DNS, firewall, TLS, and offsite backups as operator proof gates.

## Required Operator Inputs

- Hetzner project, region, server type, SSH key, firewall, and optional Volume.
- API FQDN and admin FQDN.
- External registry namespace, for example `docker.io/expertaiservices` or a
  private registry.
- Approved release commit and external-registry release manifest.
- Secret source for this cell:
  `configs/cell-secrets.ks-state-civics.sops.yaml`, Vault path, or external
  `envref://` injector.
- Embedding provider choice. Do not use `hash_mock` for the production corpus.
- Kansas court decision source corpus path or transfer plan.

## Recommended VPS Shape

For the Kansas legal/civics pilot, start with a dedicated business cell class:

- 16+ vCPU or dedicated CPU equivalent.
- 64 GB RAM minimum; 128 GB preferred if OpenSearch is enabled later.
- Local NVMe preferred.
- At least 500 GB usable disk for the pilot and rebuild headroom.
- Server backups/snapshots enabled, plus an external object/storage backup
  target. Hetzner Cloud server backups/snapshots do not include attached
  Volumes, so Volume data needs its own backup process.

## Host Firewall

Expose only:

- `22/tcp` from operator IPs only.
- `80/tcp` and `443/tcp` for reverse proxy / certificate issuance.

Do not expose Postgres, Redis, Qdrant, MinIO, model-gateway, or worker ports to
the public internet. Keep Compose service ports private behind the reverse
proxy where possible.

## External Registry Proof

Run this after Docker login to the chosen registry:

```bash
export CELL=ks-state-civics
export REGISTRY_PREFIX=docker.io/expertaiservices

python scripts/release/external-registry-proof.py \
  --registry-prefix "$REGISTRY_PREFIX" \
  --cell "$CELL"
```

This writes:

- `.release/cells/ks-state-civics/release-manifest.json`
- `.release/cells/ks-state-civics/external-registry-proof.json`

Copy the approved `release-manifest.json` to the VPS proof path used by
`cell-up.py`.

## Production Env

On the VPS:

```bash
export CELL=ks-state-civics
export REGISTRY_PREFIX=docker.io/expertaiservices
export APP_DIR=/opt/exais/vector-store
export CELL_ENV_FILE="$APP_DIR/.env.cell"

git clone <repo-url> "$APP_DIR"
cd "$APP_DIR"
git checkout <approved-release-commit>

python scripts/release/generate-cell-env.py \
  --cell "$CELL" \
  --production \
  --registry-prefix "$REGISTRY_PREFIX" \
  --public-api-base "https://api.<your-domain>" \
  --admin-origin "https://admin.<your-domain>" \
  --reference-source-env .env.production.example

cp ".release/cells/$CELL/.env.cell" "$CELL_ENV_FILE"
```

Edit `$CELL_ENV_FILE` and keep every secret-bearing value as a reference. Add or
confirm these Kansas-specific values:

```text
SVS_QUERY_PLANNER_PROFILE_ID=ks_civics_legal_v1
SVS_KSCOURTS_GRAPHRAG_ENABLED=true
SVS_KSCOURTS_GRAPHRAG_MAX_EXPANSIONS=3
QDRANT_COLLECTION_PREFIX=ks_civics_
OPENSEARCH_INDEX_PREFIX=ks_civics_
S3_BUCKET=exai-vector-store-ks-state-civics
SVS_OBJECT_STORE_STRICT=true
SVS_DEV_MODE=false
DEFAULT_EMBEDDING_PROVIDER=openai
```

Validate without printing secrets:

```bash
python scripts/release/prod-env-preflight.py --env-file "$CELL_ENV_FILE"
```

## Launch

```bash
python scripts/release/cell-up.py \
  --cell "$CELL" \
  --worker-scale 4 \
  --release-manifest /opt/exais/proof/operator-approved-release-manifest.json

python scripts/release/cell-smoke.py \
  --cell "$CELL" \
  --worker-scale 4

python scripts/release/cell-access-proof.py \
  --cell "$CELL"
```

## Bootstrap Tenant And Admin Key

The current migrations seed the default Expert AI Services dev records. For a
production customer cell, create an explicit Kansas tenant/business/bootstrap
packet before ingestion. Use owner/migration credentials through a one-time
operator script or psql session, then create scoped API keys through the API.

Minimum records:

```sql
INSERT INTO tenants(id, name, slug)
VALUES ('ten_ks_state_civics', 'KS State Civics', 'ks-state-civics')
ON CONFLICT DO NOTHING;

INSERT INTO business_instances(id, tenant_id, name, slug)
VALUES ('biz_ks_state_civics', 'ten_ks_state_civics', 'KS State Civics', 'ks-state-civics')
ON CONFLICT DO NOTHING;

INSERT INTO users(id, tenant_id, email, display_name)
VALUES ('usr_ks_state_civics_admin', 'ten_ks_state_civics', '<operator-email>', 'KS State Civics Admin')
ON CONFLICT DO NOTHING;

INSERT INTO groups(id, tenant_id, business_instance_id, name, slug)
VALUES ('grp_ks_state_civics_admins', 'ten_ks_state_civics', 'biz_ks_state_civics', 'Admins', 'admins')
ON CONFLICT DO NOTHING;

INSERT INTO group_memberships(tenant_id, group_id, user_id, role)
VALUES ('ten_ks_state_civics', 'grp_ks_state_civics_admins', 'usr_ks_state_civics_admin', 'owner')
ON CONFLICT DO NOTHING;

INSERT INTO knowledge_bases(id, tenant_id, business_instance_id, name, slug)
VALUES ('kb_ks_state_civics', 'ten_ks_state_civics', 'biz_ks_state_civics', 'KS State Civics KB', 'ks-state-civics')
ON CONFLICT DO NOTHING;
```

Do not store the resulting admin bearer key in the repo. The first admin key
must include at least:

```text
admin:read,api_keys:read,api_keys:write,vector_stores:read,vector_stores:write,documents:write,retrieval:read
```

Agent keys should be narrower:

```text
retrieval:read,vector_stores:read
```

## Corpus Load

After the cell is healthy and the bootstrap tenant/business exists:

```bash
python scripts/release/kscourts-ingest.py \
  --cell ks-state-civics \
  --source-root <path-to-ksa-diff-collector-main> \
  --manifest data/raw/kscourts-decisions/decisions_manifest.csv \
  --vector-store-name "Kansas Court Decisions" \
  --knowledge-base-id kb_ks_state_civics \
  --full-corpus
```

Then build/load the graph artifact:

```bash
python scripts/release/kscourts-graphrag-extract.py \
  --vector-store-id <created-vector-store-id> \
  --tenant-id ten_ks_state_civics \
  --business-instance-id biz_ks_state_civics \
  --output-dir .release/cells/ks-state-civics/graphrag/full

python scripts/release/kscourts-graphrag-load.py \
  --graph-artifact .release/cells/ks-state-civics/graphrag/full \
  --vector-store-id <created-vector-store-id> \
  --tenant-id ten_ks_state_civics \
  --business-instance-id biz_ks_state_civics
```

Run the recall proof:

```bash
python scripts/release/kscourts-recall-eval.py \
  --api https://api.<your-domain> \
  --vector-store-id <created-vector-store-id> \
  --output .release/cells/ks-state-civics/evals/vps-recall.json
```

## DNS And TLS Proof

Follow `runbooks/dns-tls-secrets.md`. The proof packet must include:

- DNS A/AAAA resolution for API and admin FQDNs.
- HTTPS readiness for `/readyz` and admin UI.
- Certificate SAN/validity evidence.
- CORS configured to the exact admin/API origins, not wildcard.

## Backup Proof

Follow `runbooks/backup-restore.md` and
`runbooks/external-restore-drill.md`.

Before onboarding a real customer, prove:

- Postgres metadata backup.
- Qdrant vector backup or rebuild plan.
- MinIO/object artifact backup.
- Graph artifact backup.
- Restore preflight into a temporary cell.

## Acceptance Checklist

- External registry proof exists for the approved release.
- VPS host evidence is captured.
- Production env preflight passes.
- Cell launch, smoke, and access proof pass.
- DNS/TLS proof passes.
- Tenant/business/bootstrap key packet is recorded without secrets.
- Kansas corpus ingest completes or has a bounded failure report.
- Recall eval passes the agreed threshold.
- GraphRAG tables load and graph expansion smoke passes.
- Backup and restore-preflight proof exists.
