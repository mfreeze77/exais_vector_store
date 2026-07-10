# Micro-Production Cells

Micro-production means many isolated instances share one base product image set.

```text
Base product:
  ${SVS_REGISTRY_PREFIX}/exai-vector-store-api@sha256:<manifest-digest>
  ${SVS_REGISTRY_PREFIX}/exai-vector-store-worker@sha256:<manifest-digest>
  ${SVS_REGISTRY_PREFIX}/exai-vector-store-model-gateway@sha256:<manifest-digest>
  ${SVS_REGISTRY_PREFIX}/exai-vector-store-admin-ui@sha256:<manifest-digest>
  ${SVS_REGISTRY_PREFIX}/exai-vector-store-instance-agent@sha256:<manifest-digest>

Instance:
  instance.yaml
  secrets.sops.yaml or Vault/envref references
  retrieval profiles
  security policies
  storage prefixes
  domain routing
  backup policy
```

## Upgrade flow

```text
CI builds pinned images
  -> write and verify release manifest
  -> push to registry for the target proof gate
  -> atomically write digest/provenance candidate manifest
  -> verify local RepoDigests or pull missing refs by digest
  -> atomically activate per-cell repository@digest image refs
  -> backup/preflight
  -> migrations
  -> compose up --pull never
  -> health check
  -> smoke retrieval
  -> deployment record
```

Do not use `latest` in production.

The local release gate proves this with
`SVS_REGISTRY_PREFIX=localhost:5000/expertaiservices` before any Docker Hub or
VPS launch claim.

RM-004 closes the repo-buildable image provenance lane: CI can build the API,
worker, model-gateway, admin-ui, and instance-agent images from
`scripts/release/release_common.py:APP_IMAGES`; release scripts emit JSON
manifests with fixed version tags, OCI service/version labels, and `sha256`
digest metadata. The publish/startup path derives one exact five-service
`repository@sha256:digest` mapping. Publication atomically replaces only the
release manifest; it never changes the active cell. Startup rejects bare local
image IDs and mismatched repository provenance, verifies cached `RepoDigests`,
pulls only missing digest references, and only then atomically activates the
cell's non-secret `.env.images`. Candidate failure preserves the previous pins.
Every compose-based release command consumes the active file and startup uses
`--pull never`, so a moved version tag cannot select unapproved bytes. Compose
or health failure restores the previous pin artifact without claiming automatic
container/data rollback.

The narrow instance-agent RM-004 path applies the same rule to API, worker, and
model-gateway. Deploy and rollback callers must provide a verified release
manifest through `release_manifest_path` or `--release-manifest`; the agent
preflights all three digests, writes project-local active pins, supplies the
verified refs as the compose process environment, and uses `--pull never`.
Failed compose activation restores the previous pin artifact.

The packaged agent includes the Docker CLI and Compose v2 plugin. Its release
cell profile mounts the operator-controlled `instances/` tree and release-cell
tree read-only at `/workspace/instances` and `/workspace/.release/cells`; only
the instance pin root at `/workspace/.release/instances` is writable. Override
the host roots with `SVS_AGENT_INSTANCE_ROOT`,
`SVS_AGENT_RELEASE_CELL_ROOT`, and `SVS_AGENT_PIN_ROOT`. Put each instance's
`.env.instance` beside its `instance.yaml`, or pass another mounted path as
`env_file_path`. Relative API paths are resolved below `/workspace`. Agent dry
run performs digest preflight and `docker compose config` through a temporary
pin file without changing active pins or containers.

This does not claim fleet polling, deployment history, customer-host execution,
or live orchestration. External registry publication proof, customer/VPS
startup evidence, and live operator credentials remain later proof gates.

RM-005 closes the repo-buildable encrypted-secret reference lane. Production
cell env files use reference values such as
`sops://configs/cell-secrets.example.sops.yaml#POSTGRES_PASSWORD`,
`age://...#KEY`, `vault://kv/exais/customer-001#KEY`, or `envref://KEY`.
`scripts/release/prod-env-preflight.py` rejects plaintext secret-bearing values
and DSNs with embedded passwords while reporting variable names only.
`scripts/release/generate-cell-env.py --production --reference-source-env ...`
imports only valid secret references. Live SOPS/Vault execution and customer
host secret-manager proof remain operator proof gates.

RM-006 closes the repo-buildable backup manifest and restore-preflight lane.
`scripts/backup-instance.sh` now writes schema-versioned artifact manifests for
Postgres metadata, Qdrant vectors, OpenSearch sparse indexes, object-store
metadata, config metadata, audit exports, and checksum metadata. Restore
preflight validates and enumerates those artifacts without requiring
`DATABASE_URL_SYNC` or invoking `pg_restore`. Real offsite target proof and an
external restore drill remain later operator gates.

## Fleet/version admin visibility

RM-009 exposes a repo-buildable read contract for fleet version evidence through
`/api/v1/admin/fleet/versions`. The route uses the production admin principal,
`db_for_principal`, and `admin:read` or `fleet:read`; it reads
`business_instances` and `instance_deployments` under their existing RLS
policies. `business_instances` remains tenant-scoped, while deployment records
remain tenant plus `business_instance_id` scoped with tenant-level records
visible only when the table policy permits them.

The report normalizes the five application components from
`scripts/release/release_common.py:APP_IMAGES` and existing release manifest
metadata from `scripts/release/provenance_common.py`. The admin UI can show the
selected business instance, declared component versions, image references,
digests, latest visible deployment records, and per-component `current`,
`stale`, or `unverifiable` status. Missing deployment rows, missing digests,
non-completed deployment statuses, or absent running-version evidence are
reported as unverifiable instead of implied live VPS proof.
