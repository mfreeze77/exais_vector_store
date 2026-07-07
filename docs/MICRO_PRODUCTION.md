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
  -> push to registry
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
