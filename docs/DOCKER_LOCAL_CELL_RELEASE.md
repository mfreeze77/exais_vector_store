# Docker-First Local Cell Release

ExAIS Vector Store release proof starts with a local registry-pulled cell. Do
not claim Docker Hub or VPS readiness until these commands pass with raw output.

## Local Registry Gate

```bash
python scripts/release/generate-cell-env.py --cell local --registry-prefix localhost:5000/expertaiservices
python scripts/release/registry-up.py
python scripts/release/build-images.py --registry-prefix localhost:5000/expertaiservices
python scripts/release/publish-images.py --registry-prefix localhost:5000/expertaiservices
python scripts/release/remove-local-app-images.py --registry-prefix localhost:5000/expertaiservices
# Existing cells only; a fresh cell has no volumes to remove.
python scripts/release/cell-down.py --cell local --volumes
python scripts/release/cell-up.py --cell local --worker-scale 4
python scripts/release/cell-smoke.py --cell local
python scripts/release/cell-access-proof.py --cell local
```

The generated env command intentionally prints names only. Generated local env
files live under `.release/` and are ignored by git.

`build-images.py` writes `.release/image-build-manifest.json` for the full
`APP_IMAGES` set. `publish-images.py` writes the cell-scoped
`.release/cells/local/release-manifest.json` atomically after registry manifest
inspection. Publication does not change the active cell image set. `cell-up.py`
validates that candidate manifest, derives all five approved
`repository@sha256:digest` references, and proves every digest locally or by a
digest pull before atomically replacing the non-secret active
`.release/cells/local/.env.images` file. A validation or pull failure preserves
the previous pin file byte-for-byte. A later compose or health-check failure
restores that previous pin artifact before the command exits; container rollback
remains an explicit operator action when compose changed runtime state.

Activation rejects missing metadata, `latest`, mismatched registry/version
tags, missing app services, bare local image IDs, or repository-digest
provenance that does not match the manifest. Compose requires the active pinned
image file for every release command, so a moved version tag cannot change the
bytes used by startup or worker recovery.

Before boot, `cell-up.py` verifies each approved reference against local Docker
`RepoDigests`; a matching local image needs no registry pull. Missing images are
pulled by digest and re-inspected, and any mismatch fails before compose starts.
Infrastructure images are pulled separately and the cell boots with
`--pull never`. This proves local digest/provenance automation only; it is not
Docker Hub, VPS, or customer-cell proof.

`local-restore-drill.py` requires an explicit published, registry-resolvable
`--release-manifest`. It preflights the full digest set before writing either
fresh-cell pin file, boots infrastructure, and runs `scripts/migrate.sh` from
the pinned API image before starting source apps or restoring the target dump.
Clean build manifests backed only by local image IDs are rejected.

The optional `agent` profile uses the pinned instance-agent image and Docker
socket. It exposes `${SVS_AGENT_INSTANCE_ROOT:-../../instances}` read-only as
`/workspace/instances`,
`${SVS_AGENT_RELEASE_CELL_ROOT:-../../.release/cells}` read-only as
`/workspace/.release/cells`, and
`${SVS_AGENT_PIN_ROOT:-../../.release/instances}` read-write as
`/workspace/.release/instances`. Keep instance manifests and `.env.instance`
files under the first root and release manifests under the second so paths sent
by `svsctl.py` resolve inside the container. Only the dedicated pin root is
writable. The image carries Docker CLI plus Compose v2; deploy dry-run proves
digest availability and Compose rendering without activating pins or starting
instance containers.

Default local public ports are product-specific high ports: API `18080`, model
gateway `18081`, admin UI `13080`, instance agent `18090`, Postgres `15432`,
Redis `16379`, Qdrant `16333`/`16334`, and MinIO `19000`/`19001`.

On Windows Docker hosts where `localhost` loopback is unavailable from Python or
curl, use `cell-access-proof.py` as the reproducible fallback. It probes API and
admin UI through host loopback first, then proves access through a
`curlimages/curl` container on the compose network.

## Scale Gate

```bash
python scripts/release/seed-scale.py --cell local --documents 10000 --headings-per-doc 8
python scripts/release/search-bench.py --cell local --vector-store-id <id-from-seed-scale> --queries 200 --warmup-queries 100 --p95-ms 500 --pace-ms 800
python scripts/release/qdrant-chaos-repair.py --cell local --documents 500
```

The search benchmark warms repeated query embeddings before measurement and
paces requests so a local proof does not bypass or trip the default API
`120/min` rate limit. Cold external-provider query embedding latency should be
recorded separately when comparing provider performance.

The Qdrant repair command must prove actual repair work: it deletes real Qdrant
points for the test vector store, shows the count drop, calls
`/api/v1/maintenance/reindex` with `force=true`, and shows the count recover
with a non-zero `processed` value.

If a scale proof needs to be resumed without submitting another 10,000
documents, use the generated vector store id:

```bash
python scripts/release/seed-scale.py --cell local --documents 10000 --headings-per-doc 8 --vector-store-id <id-from-seed-scale> --skip-submit
```

## Docker Hub Push

Run this only after the local registry gate passes:

```bash
docker login
python scripts/release/external-registry-proof.py \
  --registry-prefix docker.io/expertaiservices \
  --cell external-registry
```

External registry credential use, clean pull-by-digest evidence, and Docker
Hub/private-registry operator proof remain separate proof gates. Do not mark a
VPS or customer cell ready from the local manifest alone. See
`runbooks/external-registry-push.md` for the repo-local proof package.

## VPS Cell Launch

On a VPS with Docker and Compose installed:

```bash
git clone <repo-url> /opt/exais/vector-store
cd /opt/exais/vector-store
python scripts/release/generate-cell-env.py \
  --cell customer-001 \
  --production \
  --registry-prefix docker.io/expertaiservices \
  --reference-source-env .env.production.example
python scripts/release/prod-env-preflight.py \
  --env-file .release/cells/customer-001/.env.cell
python scripts/release/cell-up.py \
  --cell customer-001 \
  --release-manifest /opt/exais/proof/operator-approved-release-manifest.json
```

Use a registry prefix such as `docker.io/expertaiservices` or a private registry
namespace. The operator-approved manifest must match the generated cell registry
and `SVS_VERSION`; app containers are started from its immutable digest
references, never by resolving the version tag. Do not use `latest` for cells.

Production env files must carry secret references, not plaintext values.
Accepted forms are documented in `runbooks/encrypted-secrets.md` and include
`sops://...#KEY`, `age://...#KEY`, `vault://...#KEY`, and `envref://KEY`.
`prod-env-preflight.py` validates those references and rejects plaintext
passwords, API keys, access keys, peppers, tokens, and DSNs with embedded
passwords while printing variable names only. `cell-up.py` automatically runs
that preflight, resolves the references before image-pin activation or Docker,
and gives Compose a restricted process-scoped env file that is removed after
the release command. `cell-smoke.py` repeats resolution while it stops and
recreates workers, retaining the temporary file through restoration and then
removing it. SOPS/Vault credentials, DNS/TLS, and successful launch on the
selected customer host remain operator proof gates outside the local release
proof. Use `runbooks/customer-cell-launch.md` to package selected-host launch
evidence without reusing local or registry-only proof as a VPS readiness claim.
