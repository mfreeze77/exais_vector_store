# Gate 1: Publish And Pulled-Image Boot

This gate proves ExAIS Vector Store is Docker-first locally before any Docker
Hub or VPS claim is made.

- [x] `python scripts/release/generate-cell-env.py --cell local --registry-prefix localhost:5000/expertaiservices` prints variable names only, never values.
- [x] `python scripts/release/build-images.py --registry-prefix localhost:5000/expertaiservices` builds every app image with the tag from `VERSION`.
- [x] `python scripts/release/publish-images.py --registry-prefix localhost:5000/expertaiservices` pushes all 5 app images and proves each pushed tag with `docker manifest inspect` or, for an insecure local HTTP registry, a registry manifest GET from the registry network.
- [x] `python scripts/release/remove-local-app-images.py --registry-prefix localhost:5000/expertaiservices` removes the local app image tags and follow-up `docker image inspect` fails for those tags.
- [x] `python scripts/release/cell-up.py --cell local --worker-scale 4` completes through registry pull and `--pull always`; compose `ps` shows core services healthy.
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

Docker Hub follow-up is mechanical only after this gate passes:

```bash
docker login
python scripts/release/build-images.py --registry-prefix docker.io/expertaiservices
python scripts/release/publish-images.py --registry-prefix docker.io/expertaiservices
```
