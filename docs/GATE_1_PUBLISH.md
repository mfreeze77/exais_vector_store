# Gate 1: Publish And Pulled-Image Boot

This gate proves ExAIS Vector Store is Docker-first locally before any Docker
Hub or VPS claim is made.

- [x] `python scripts/release/generate-cell-env.py --cell local --registry-prefix localhost:5000/expertaiservices` prints variable names only, never values.
- [x] `python scripts/release/build-images.py --registry-prefix localhost:5000/expertaiservices` builds every app image with the tag from `VERSION`.
- [x] `python scripts/release/publish-images.py --registry-prefix localhost:5000/expertaiservices` pushes all 5 app images and proves each pushed tag with `docker manifest inspect` or, for an insecure local HTTP registry, a registry manifest GET from the registry network.
- [x] `python scripts/release/remove-local-app-images.py --registry-prefix localhost:5000/expertaiservices` removes the local app image tags and follow-up `docker image inspect` fails for those tags.
- [x] `python scripts/release/cell-up.py --cell local --worker-scale 4` derives all 5 manifest-approved repository-digest refs, verifies matching local `RepoDigests` or pulls missing refs by digest, and boots with `--pull never`; compose `ps` shows core services healthy.
- [x] `/readyz` returns `200` from inside the pulled API container and from an external curl container on the cell network; host loopback curl is recorded when the Windows host stack permits it.
- [x] API/worker logs contain zero `Unsafe SVS startup configuration` lines.
- [x] Compile and unit tests pass inside the pulled API image.
- [x] `SVS_RUN_INTEGRATION=1` integration tests pass inside the pulled API image against the cell Postgres and real Qdrant.
- [x] Retrieval/security/ingestion semantics are not weakened to make Docker pass; the retrieval change is covered by a regression test and pulled-image search proof.

## Proof Snapshot

```text
VERSION=0.9.8-production-candidate
localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate sha256:8f01d821dd51da9bba17f321835a3900a67b72274d4dfb415abe018972c4d18c
docker image inspect ...exai-vector-store-api:0.9.8-production-candidate
Error response from daemon: No such image: localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate
exais-vector-store-local-api-1 localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate Up ... (healthy) 0.0.0.0:18080->8080/tcp
{"ready":true,"db":true}
200
26 passed in 1.63s
5 passed, 8 warnings in 1.78s
```

## Wave 009 Current Snapshot

```text
localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate sha256:1b7623b810f64967af01008196b5393bd9b82551b70e4ff9ca9f4111dbe6ec70
localhost:5000/expertaiservices/exai-vector-store-admin-ui:0.9.8-production-candidate sha256:4179f3841c703c7f6c4c6377db3c430f479cbe3aa5fc6f5bad3a2cd562584a69
python -m pytest -q -rs --ignore=tests/integration
46 passed, 2 warnings in 5.56s
python -m pytest -q -rs tests/test_cell_access_proof_script.py tests/test_prod_env_preflight_script.py tests/test_qdrant_repair_all_script.py tests/test_qdrant_repair_proof_script.py tests/test_local_restore_drill_script.py tests/test_readyz.py tests/test_release_cell_network.py
20 passed, 2 warnings in 6.03s
{"ready":true,"db":true,"qdrant":true}
200
ACCESS_PATH=cell-network-fallback
```

The Wave 009 snapshot is a follow-up local-registry proof. It does not replace
the original remove-local-tags proof above and does not claim Docker Hub or VPS
launch.

## RM-004 Digest Activation Snapshot

```text
Version tag moved while running API remained on its prior approved digest.
Publish wrote .release/cells/local/release-manifest.json atomically.
Active .env.images SHA256 before publish = 28b89c0cf031f83a6d159ec54e463366c282c14f5fd544c8a33c5c98cdb69918
Active .env.images SHA256 after publish  = 28b89c0cf031f83a6d159ec54e463366c282c14f5fd544c8a33c5c98cdb69918
python scripts/release/cell-up.py --cell local --worker-scale 4 --timeout-seconds 300
All five candidate RepoDigests verified before active pin replacement.
Compose used --pull never; API, model gateway, admin UI, four workers, and infrastructure healthy.
API digest = sha256:2be494069ee4bbd8d05dddc853330ddc88e7ce09e679b72d06b7a02b906cd9cd
Instance-agent digest = sha256:472c1f1d0e1871237f539e9c08d4771165d5af4684190f2a4e40177d4d746ba2
Pinned release-cell agent profile: Docker 26.1.5, Compose 2.26.1, health=healthy.
Agent dry-run HTTP 200; three digest preflights and compose config passed; no active probe pin created.
python scripts/release/cell-smoke.py --cell local --worker-scale 4
540 passed, 2 warnings
5 passed, 8 warnings
Registry-down recovery restored all four workers from the active digest pin.
python scripts/release/local-restore-drill.py --release-manifest .release/cells/local/release-manifest.json ...
restore_sql_counts_final={"active_chunks": 48, "active_jobs": 0, "failed_jobs": 0, "indexed_chunks": 48}
restore_search_results=5
```

This remains local Docker proof. It does not claim external registry,
customer-host, DNS/TLS, or production secret-manager readiness.

Docker Hub follow-up is mechanical only after this gate passes:

```bash
docker login
python scripts/release/build-images.py --registry-prefix docker.io/expertaiservices
python scripts/release/publish-images.py --registry-prefix docker.io/expertaiservices
```
