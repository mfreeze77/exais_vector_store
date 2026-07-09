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
  secrets.sops.yaml
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
