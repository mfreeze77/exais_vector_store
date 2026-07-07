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
python scripts/release/cell-down.py --cell local --volumes
python scripts/release/cell-up.py --cell local --worker-scale 4
python scripts/release/cell-smoke.py --cell local
```

The generated env command intentionally prints names only. Generated local env
files live under `.release/` and are ignored by git.

Default local public ports are product-specific high ports: API `18080`, model
gateway `18081`, admin UI `13080`, instance agent `18090`, Postgres `15432`,
Redis `16379`, Qdrant `16333`/`16334`, and MinIO `19000`/`19001`.

## Scale Gate

```bash
python scripts/release/seed-scale.py --cell local --documents 10000 --headings-per-doc 8
python scripts/release/search-bench.py --cell local --vector-store-id <id-from-seed-scale> --queries 200 --p95-ms 500
python scripts/release/qdrant-chaos-repair.py --cell local --documents 500
```

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
python scripts/release/build-images.py --registry-prefix docker.io/expertaiservices
python scripts/release/publish-images.py --registry-prefix docker.io/expertaiservices
```

## VPS Cell Launch

On a VPS with Docker and Compose installed:

```bash
git clone <repo-url> /opt/exais/vector-store
cd /opt/exais/vector-store
cp .env.production.example /opt/exais/vector-store/.env.cell
# Fill the placeholder values in /opt/exais/vector-store/.env.cell.
SVS_CELL_ENV_FILE=/opt/exais/vector-store/.env.cell \
  docker-compose --env-file /opt/exais/vector-store/.env.cell \
  -f infra/docker/compose.cell.yml \
  -p exais-vector-store-customer-001 \
  up -d --pull always
```

Use a registry prefix such as `docker.io/expertaiservices` or a private registry
namespace. Keep `SVS_VERSION` pinned to `VERSION`; do not use `latest` for cells.
