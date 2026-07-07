# WAVE-007 Docker-First Local Cell Release Gate

## Summary

Graduate the repo from product candidate to Docker-proven local product by
building versioned app images, publishing them to a registry namespace, deleting
local image tags, booting a clean cell from pulled images only, and proving
publish, test, scale, search, and repair gates with raw command output.

## Background

The release source of truth is local Docker proof. Docker Hub push and VPS launch
must remain mechanical follow-up until a local registry-pulled cell passes the
same command path.

## Tickets

| Ticket | Status | Specialist | Scope |
| --- | --- | --- | --- |
| W7-001 | Complete | Implementation | Add versioned image, env, registry, cell-up/down, smoke, scale, search, and repair scripts. |
| W7-002 | Complete | Test/Proof | Prove local registry publish, local tag removal, and clean pulled-image boot. |
| W7-003 | Complete | Test/Proof | Prove `/readyz`, compose health, unit tests, and integration tests inside the pulled API image. |
| W7-004 | Complete | Test/Proof | Prove 10,000 queued docs, real Qdrant indexing, SQL counts, hybrid search p95, and repair after Qdrant interruption. |
| W7-005 | Complete | Quality Control | Review changed files, raw command output, acceptance criteria, and Docker Hub/VPS follow-up boundary. |

## Scope

- Docker-first compose file that pulls app images by `SVS_REGISTRY_PREFIX` and `SVS_VERSION`.
- Reusable release scripts for env generation, registry, build, publish, remove local tags, cell up/down, smoke, scale seed, search bench, and repair.
- Secret-safe env generation that prints variable names only.
- Gate docs that preserve auditable acceptance criteria in repo files.
- Containerized proof using pulled images and real Postgres/Qdrant.

## Out Of Scope

- Pushing to Docker Hub without operator credentials.
- Launching a VPS cell without operator-selected host, DNS, TLS, and secret values.
- Weakening auth, tenant isolation, ingestion atomicity, retrieval semantics, or security guardrails.

## Acceptance Criteria

- [x] All app images build with the exact version from `VERSION`.
- [x] All app images can be pushed to a registry namespace and inspected through Docker manifest inspect or the local registry manifest API.
- [x] Local app image tags can be removed before boot.
- [x] A clean cell boots from pulled registry images only.
- [x] `/readyz` returns `200` inside the pulled API container and from the cell network.
- [x] Compose health output shows core services healthy.
- [x] Unit tests run inside the pulled API image.
- [x] Integration tests run inside the pulled API image against cell-real Postgres and Qdrant.
- [x] Scale proof submits 10,000 docs through the queue path and SQL shows zero terminal failed jobs.
- [x] SQL count shows at least 80,000 active chunks with dense and sparse index status indexed.
- [x] Hybrid search bench runs 200 searches with zero errors and p95 under 500ms.
- [x] Qdrant interruption plus repair leaves zero active chunks in pending, failed, or unindexed status.
- [x] Docker Hub push and VPS launch docs are mechanical follow-up commands, not unproven readiness claims.

## Verification

```bash
python scripts/release/generate-cell-env.py --cell local --registry-prefix localhost:5000/expertaiservices
python scripts/release/registry-up.py
python scripts/release/build-images.py --registry-prefix localhost:5000/expertaiservices
python scripts/release/publish-images.py --registry-prefix localhost:5000/expertaiservices
python scripts/release/remove-local-app-images.py --registry-prefix localhost:5000/expertaiservices
python scripts/release/cell-down.py --cell local --volumes
python scripts/release/cell-up.py --cell local --worker-scale 4
python scripts/release/cell-smoke.py --cell local
python scripts/release/seed-scale.py --cell local --documents 10000 --headings-per-doc 8
python scripts/release/search-bench.py --cell local --vector-store-id <id-from-seed-scale> --queries 200 --p95-ms 500
python scripts/release/qdrant-chaos-repair.py --cell local --documents 500
```

## Proof Notes

- Version: `0.9.8-production-candidate` from `VERSION`.
- Registry namespace: `localhost:5000/expertaiservices`.
- Local public ports: API `18080`, model gateway `18081`, admin UI `13080`, instance agent `18090`, Postgres `15432`, Redis `16379`, Qdrant `16333`/`16334`, MinIO `19000`/`19001`.
- Env generation proof printed variable names only; generated values remain under ignored `.release/`.
- Build proof ended with image inspect rows for all five app images, including API `sha256:8f01d821dd51da9bba17f321835a3900a67b72274d4dfb415abe018972c4d18c`.
- Publish proof pushed all five app images. Local HTTP registry manifest fallback returned OCI manifest JSON for each tag after Docker manifest inspect failed against the insecure local registry.
- Local tag removal proof ended with `No such image` for all five app tags.
- Clean boot proof pulled the app images, recreated volumes, and compose `ps` showed all services healthy with registry image names.
- Smoke proof raw output included `{"ready":true,"db":true}` and `200` from the API container and an external curl container on the cell network. Windows host loopback to `localhost:18080` failed in this environment and was not used as the source of truth.
- Unit proof inside the pulled API image: `26 passed in 1.63s`.
- Integration proof inside the pulled API image: `5 passed, 8 warnings in 1.78s`.
- Scale vector store: `vs_221e9fa2ae704898912b1bd5`; final SQL: `completed | 10000`, `failed_jobs=0`, `active_jobs=0`, `active_chunks=90000`, `indexed_chunks=90000`.
- Search bench against the scale vector store: `queries=200`, `errors=0`, `p50_ms=221`, `p95_ms=371`, `avg_ms=239`.
- Qdrant chaos vector store: `vs_a4a1a34865624dfb99970c39`; final SQL tuple: `0|0|0|0|4500|4500`.
