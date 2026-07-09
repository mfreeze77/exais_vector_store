# Micro-Production Cells

Micro-production means many isolated instances share one base product image set.

```text
Base product:
  ${SVS_REGISTRY_PREFIX}/exai-vector-store-api:${SVS_VERSION}
  ${SVS_REGISTRY_PREFIX}/exai-vector-store-worker:${SVS_VERSION}
  ${SVS_REGISTRY_PREFIX}/exai-vector-store-model-gateway:${SVS_VERSION}
  ${SVS_REGISTRY_PREFIX}/exai-vector-store-admin-ui:${SVS_VERSION}
  ${SVS_REGISTRY_PREFIX}/exai-vector-store-instance-agent:${SVS_VERSION}

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
  -> write digest/provenance manifest
  -> instance-agent pulls version
  -> backup/preflight
  -> migrations
  -> compose up
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
digest metadata; and local cell startup rejects unpinned or unverifiable app
image sets before pull/up. External registry publication proof, customer/VPS
startup evidence, and live operator credentials are later proof gates.

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
