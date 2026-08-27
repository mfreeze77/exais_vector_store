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
- First VPS rollout is gated on WAVE-117: the Kansas Court Decisions vector
  store must have a validated instance source package before migrated-volume
  handoff, reingestion, or production update is called complete.

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
- Validated source package for each vector store being migrated or replayed.
  For the pilot this means
  `instances/ks-state-civics/vector-stores/kansas-court-decisions`.

## Recommended VPS Shape

For the first Kansas legal/civics customer cell, size the VPS for API,
queue/worker orchestration, Postgres, Qdrant, MinIO, graph tables, retrieval,
and backup/restore headroom. Do not size it as a local PDF/OCR or local
embedding-model host.

Practical starting shapes:

- 16 GB RAM: sane first VPS target for the current Kansas court-decision
  corpus when embeddings and PDF conversion are external.
- 32 GB RAM: comfortable production pilot with rebuild, backup, graph, and
  moderate growth headroom.
- 64 GB+ RAM: only for future-heavy cells, high concurrency, OpenSearch,
  transcript-scale corpora, or multiple large stores on one customer box.
- Dedicated CPU is preferred over shared CPU when p99 retrieval latency matters.
- Local NVMe preferred.
- At least 500 GB usable disk for the pilot and rebuild headroom.
- Server backups/snapshots enabled, plus an external object/storage backup
  target. Hetzner Cloud server backups/snapshots do not include attached
  Volumes, so Volume data needs its own backup process.

## Runtime Responsibility Boundary

Keep these responsibilities separate. This is a hard deployment boundary for
all downstream planning:

- RunPod Marker handles raw PDF/OCR/PDF-to-Markdown conversion through the
  configured remote Marker endpoint.
- Voyage/OpenAI or another configured embedding provider creates embeddings
  over HTTPS; the VPS does not load or run embedding models locally.
- The VPS runs ExAIS API, workers, Postgres, Qdrant, MinIO, graph tables,
  retrieval, key management, source-package update orchestration, and proof
  scripts.
- Agents call the ExAIS API over HTTPS with ExAIS bearer keys. They do not call
  Qdrant, Postgres, MinIO, Marker, or the embedding provider directly.
- Local PDF text extraction in the Kansas importer is an optional importer
  optimization/fallback path, not a customer VPS sizing requirement and not the
  general product default.

## Host Firewall

Expose only:

- `22/tcp` from operator IPs only.
- `80/tcp` and `443/tcp` for reverse proxy / certificate issuance.

Do not expose Postgres, Redis, Qdrant, MinIO, model-gateway, or worker ports to
the public internet. Keep Compose service ports private behind the reverse
proxy where possible.

## Provider-Neutral Public API Mode

If this cell runs outside Hetzner or outside the same Hetzner private network as
`kansasaccountability`, treat the ExAIS API as the only supported network
boundary. This is valid for OVH, RackNerd, netcup, Oracle, or another VPS
provider when these gates are met:

- Public ingress is HTTPS only on `443/tcp`, plus `80/tcp` only for certificate
  issuance or redirect.
- SSH is restricted to operator IPs and key-only authentication.
- No data-plane service ports are reachable from the internet:
  Postgres `5432`, Redis `6379`, Qdrant `6333/6334`, MinIO `9000/9001`,
  model-gateway, and worker ports must remain private to the host/Compose
  network.
- Docker published ports are audited with an external probe, not only `ufw`
  status, because Docker can install iptables rules outside `ufw` policy.
- Agents receive only the public `EXAIS_API_BASE`, selected vector-store IDs,
  and read-only ExAIS bearer keys. They do not receive Qdrant, database,
  object-store, Marker, or embedding-provider credentials.
- CORS is restricted to the exact admin/caller origins; do not use wildcard
  origins for production.
- If the caller app has static egress IPs, enforce an API allowlist. If it does
  not, rely on HTTPS, bearer-key scope, rate limits, audit logs, and key
  rotation. Add mTLS only when customer policy requires device/client
  certificate binding.

Public HTTPS mode must include a remote caller smoke test from outside the VPS
provider network: `/readyz`, one scoped-key search, one citation-bearing result,
and one graph-intent search for legal instances.

## Caller IP Allowlist Gate

When the customer agent runs server-side on `kansasaccountability`, all ExAIS
search calls should originate from that VPS public egress IP unless the app is
later moved behind another NAT, proxy, CDN, or job platform. Verify the current
public IP immediately before applying firewall or reverse-proxy rules.

For a provider-neutral deployment, restrict the API hostname to:

- `kansasaccountability` public IPv4 as a `/32` caller allowlist entry.
- Current operator/admin IPs as temporary `/32` entries.
- Certificate renewal traffic on `80/tcp` only as needed.

Do not assume the allowlist works when:

- The agent calls ExAIS directly from a browser or mobile client.
- The caller runs inside OpenAI-hosted tools, ChatGPT, or another external agent
  platform.
- The app uses a CDN, outbound proxy, serverless function, or worker queue with
  different egress IPs.

In those cases, put a server-side proxy/tool adapter on `kansasaccountability`
or use the new platform's documented static egress IPs. Keep the ExAIS API
closed to unknown source IPs whenever a stable caller egress path exists.

Proof requirement:

- From the allowed caller IP, `/readyz` and a scoped-key search return expected
  responses.
- From a non-allowed external IP, the API is rejected at the firewall or reverse
  proxy before it reaches the ExAIS app.
- External scans show only `22/tcp` from operator IPs and `80/443` as intended;
  data-plane ports remain closed.

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

## Source Package Gate

Before migrating local volumes, replaying the corpus, or calling the first VPS
launch complete, validate the instance source package:

```bash
python scripts/release/validate-instance-source-packages.py \
  --instance ks-state-civics \
  --production
```

Then capture the dry-run update plan:

```bash
python scripts/release/instance-source-update.py \
  --instance ks-state-civics \
  --vector-store kansas-court-decisions \
  --source kscourts-decisions \
  --dry-run \
  --production
```

The dry-run must report `api_only_update_path=true`,
`direct_storage_writes=false`, and `mutation_performed=false`.

## Local Staging And SSH Handoff

For the first Kansas cell, it is acceptable and often preferable to do the
expensive rebuild/reingest work on a powerful local machine, then transfer a
consistent restore bundle to the VPS over SSH. This keeps the VPS sized for
serving search instead of full-corpus rebuilds.

Use this mode when:

- The local cell has the approved release images and production-equivalent env.
- Remote Marker and the configured embedding provider are available from the
  local cell.
- Full ingest, graph extraction/load, recall eval, and search smoke pass
  locally.
- The VPS is intended to start as a serving cell, not as the rebuild machine.

Hard rules:

- Reingest locally through the ExAIS API; do not write directly to local or VPS
  Postgres, Qdrant, MinIO, or graph tables.
- SSH/rsync/scp is only the transport for an approved restore bundle or
  snapshots. It is not approval to run ad hoc SQL updates on the VPS.
- Quiesce writes before capturing the handoff bundle so Postgres metadata,
  Qdrant points, MinIO artifacts, graph tables, and source-package locks
  describe the same corpus instant.
- Prefer logical backup artifacts over raw Docker volume copies:
  Postgres `pg_dump`, Qdrant collection snapshots or a proven rebuild plan,
  object-store export/mirror, graph artifacts, source package files, env
  references, and release manifest.
- After restore on the VPS, run readiness, caller lifecycle proof, recall eval,
  and graph-expansion smoke before exposing the endpoint.

This local-staging path can reduce the first VPS shape to a search-serving
profile such as 4-8 GB RAM for a demo or 8-16 GB for a paid read-mostly pilot.
It does not replace offsite backup/restore proof before customer production.

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
DEFAULT_EMBEDDING_PROVIDER=voyage
VOYAGE_API_KEY=sops://configs/cell-secrets.ks-state-civics.sops.yaml#VOYAGE_API_KEY
MARKER_MODE=remote
MARKER_RUNPOD_API_KEY=sops://configs/cell-secrets.ks-state-civics.sops.yaml#MARKER_RUNPOD_API_KEY
MARKER_RUNPOD_ENDPOINT_ID=envref://MARKER_RUNPOD_ENDPOINT_ID
```

The existing loaded Kansas Court Decisions collection is
`ks_civics_biz_ks_state_civics_voyage_4_docs_1024`, backed by Voyage
`voyage-4` at 1024 dimensions. Do not change the embedding provider/model or
dimensions for this store unless you are intentionally creating a new vector
collection and rerunning recall proof.

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
packet before ingestion. Use owner/migration credentials through the one-time
bootstrap helper, then create scoped API keys through the API.

Preferred helper:

Run it with the resolved production `DATABASE_URL` and `SVS_API_KEY_PEPPER` in
the process environment. Do not pass secret references that have not been
resolved yet.

```bash
python scripts/release/bootstrap-instance-admin-key.py \
  --database-url "$DATABASE_URL" \
  --tenant-id ten_ks_state_civics \
  --tenant-name "KS State Civics" \
  --tenant-slug ks-state-civics \
  --business-instance-id biz_ks_state_civics \
  --business-name "KS State Civics" \
  --business-slug ks-state-civics \
  --user-id usr_ks_state_civics_admin \
  --user-email "<operator-email>" \
  --user-display-name "KS State Civics Admin" \
  --group-id grp_ks_state_civics_admins \
  --knowledge-base-id kb_ks_civics \
  --knowledge-base-name "KS State Civics KB" \
  --knowledge-base-slug ks-state-civics \
  --secret-output "<path-outside-repo>/ks-state-civics-admin-key.json"
```

The helper sets tenant/business RLS context, creates the minimum records below
with `ON CONFLICT DO NOTHING`, inserts the first admin API-key hash, and refuses
to write the raw key under the repo path. Use `--print-secret` only for an
interactive one-time console handoff.

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
VALUES ('kb_ks_civics', 'ten_ks_state_civics', 'biz_ks_state_civics', 'KS State Civics KB', 'ks-state-civics')
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

Run the caller lifecycle proof before handoff:

```bash
python scripts/release/instance-caller-lifecycle-proof.py \
  --api-base "$EXAIS_API_BASE" \
  --admin-key "$EXAIS_ADMIN_KEY" \
  --output .release/cells/ks-state-civics/caller-lifecycle-proof.json
```

This creates temporary ingestion/search keys, creates two vector stores, uploads
a fixture file, attaches it directly and through a file batch, searches the
exposed stores with the search-only key, verifies citations, verifies
multi-store `/v1/responses` file search, writes a redacted proof artifact, and
revokes temporary keys unless `--keep-created-keys` is passed.

## Corpus Load

After the cell is healthy and the bootstrap tenant/business exists:

Confirm the PDF-processing boundary before any corpus run. Raw PDF upload and
general customer ingestion should use remote RunPod Marker conversion, then
ingest returned Markdown as `pdf_markdown_external_v1`. The Kansas court
importer may use local text extraction for already text-extractable court PDFs
as a cost/speed optimization, with Marker fallback for encrypted, scanned, or
low-text PDFs. This local importer behavior is not a requirement for customer
VPS sizing.

Before seeding a customer-facing corpus, decide where the converted Markdown or
HTML artifacts will be hosted for the caller app. The ingestion payload should
use the caller-hosted HTTPS artifact URL as `source_uri` when user-facing
citations need to open the extracted source text. Preserve internal object-store
keys and checksums for audit/restore, but do not rely on internal object keys as
the only citation target.

Prepare the source-package seed skeleton before the first scrape or replay:

```bash
python scripts/release/prepare-instance-source-seeds.py \
  --instance ks-state-civics \
  --vector-store kansas-court-decisions \
  --source kscourts-decisions \
  --production \
  --execute
```

For normal scraped web URLs, the canonical source URL can remain the public
`source_uri` and therefore the returned `citation.url`. In that case, store the
extracted Markdown/HTML snapshot in the instance seed folder for audit and
rebuilds, but the caller app does not need to host a duplicate copy unless it
wants a preserved evidence page.

For the existing local Kansas Court Decisions seed, `kscourts-ingest.py` used
the official PDF URL as `source_uri`. That does not break current search or PDF
citations. It only means caller-hosted Markdown/HTML evidence pages need an
additional artifact export/publish plus source-URI remap before the caller UI
can open extracted text directly from `citation.url`. This is a metadata/artifact
handoff step; do not re-vectorize solely to change citation URL targets.

```bash
python scripts/release/kscourts-ingest.py \
  --cell ks-state-civics \
  --source-root <path-to-ksa-diff-collector-main> \
  --manifest data/raw/kscourts-decisions/decisions_manifest.csv \
  --vector-store-name "Kansas Court Decisions" \
  --knowledge-base-id kb_ks_civics \
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
- Provider-neutral public API mode proof passes if the VPS is not on the
  Hetzner private network with the caller.
- Caller IP allowlist proof passes when the caller has stable server-side
  egress.
- Production env preflight passes.
- Cell launch, smoke, and access proof pass.
- DNS/TLS proof passes.
- Tenant/business/bootstrap key packet is recorded without secrets.
- Caller-hosted converted artifact URL pattern is recorded if citations need to
  open Markdown/HTML source pages.
- Kansas corpus ingest completes or has a bounded failure report.
- Recall eval passes the agreed threshold.
- GraphRAG tables load and graph expansion smoke passes.
- Backup and restore-preflight proof exists.
