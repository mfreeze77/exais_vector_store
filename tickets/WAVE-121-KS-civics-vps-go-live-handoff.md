# WAVE-121 KS Civics VPS Go-Live Handoff

## Summary

Close the remaining repo-side gap before the `ks-state-civics` customer cell can
be promoted from the local Docker instance to a standalone VPS: service ports
must bind safely, the public edge must expose only the ExAIS API/admin surfaces,
and the existing local corpus must have a reproducible restore bundle instead of
an informal volume-copy plan.

## Background

The local cell already has customer-facing Kansas Court Decisions and Topeka
Municipal Code stores. A VPS promotion should not require re-vectorizing the
same corpus on the smaller server. The production handoff needs a consistent
local export that captures Postgres metadata, graph tables, Qdrant vectors,
object artifacts, source package metadata, release pins, and restore checksums.

The hard boundary remains: agents call ExAIS over HTTPS with scoped bearer keys.
Qdrant, Postgres, MinIO, Marker, embedding providers, and model-gateway are not
caller-facing services.

## Scope

- Make Compose-published service ports bind through `SVS_BIND_IP`.
- Make production env generation/preflight require a loopback bind for service
  ports.
- Remove model-gateway from the public Caddy reverse-proxy surface.
- Keep generated restore bundles and local proof extracts out of Docker release
  build contexts.
- Add a restorable customer-cell export script for local-to-VPS handoff.
- Extend backup manifest discovery so real Qdrant snapshot indexes and object
  volume indexes count as backup evidence.
- Document the exact Kansas cell export and VPS restore sequence.

## Out Of Scope

- Creating or provisioning the actual VPS.
- Running external DNS/TLS changes.
- Publishing registry images unless registry credentials are already available.
- Re-vectorizing the Kansas or Topeka corpora.
- Implementing a full Qdrant/MinIO overwrite restore command that runs
  unattended against an existing non-empty production cell.

## Acceptance Criteria

- [x] Production `.env` examples and generated production envs set
  `SVS_BIND_IP=127.0.0.1`.
- [x] Production preflight rejects wildcard Compose binds.
- [x] Cell Compose ports use `SVS_BIND_IP` for every published port.
- [x] Caddy no longer routes public traffic to model-gateway.
- [x] Docker release build context excludes `.release`, `.tmp`, `backups`, and
  `restore-work`.
- [x] A cell export script can produce a restore bundle with `postgres/svs.dump`,
  `qdrant/snapshots.json`, object volume indexes, `manifest.json`,
  `CHECKSUMS.sha256`, and a restore note while excluding secret env files.
- [x] A Python restore preflight validates the bundle manifest, checksums,
  indexed Qdrant snapshot files, and indexed object volume archives without
  mutating a running cell.
- [x] Backup manifest discovery accepts `qdrant/snapshots.json` and
  `object-store/volumes.json` as first-class artifacts.
- [x] KS Civics launch runbook includes the local export command and the VPS
  restore order.
- [x] Focused unit tests and production-env preflight pass in the Docker proof
  environment.

## Verification

```powershell
python scripts\release\prod-env-preflight.py --env-file .env.production.example

docker run --rm -v "${PWD}:/work" -w /work `
  -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent `
  localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate `
  python -m pytest -q -rs `
  tests/test_prod_env_preflight_script.py `
  tests/test_generate_cell_env.py `
  tests/test_instance_agent_release.py `
  tests/test_backup_integrations.py `
  tests/test_vps_restore_bundle.py

docker run --rm -v "${PWD}:/work" -w /work `
  -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent `
  localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate `
  python -m py_compile `
  scripts/release/generate-cell-env.py `
  scripts/release/prod-env-preflight.py `
  scripts/release/export-cell-restore-bundle.py `
  scripts/release/restore-cell-restore-bundle.py

python scripts\release\export-cell-restore-bundle.py `
  --cell ks-state-civics `
  --dry-run

python scripts\release\restore-cell-restore-bundle.py `
  .release\cells\ks-state-civics\vps-handoff\<bundle>.tar.gz `
  .tmp\vps-restore-preflight `
  --preflight-only
```

## Notes

The export script is allowed to stop local API/worker briefly only when
`--quiesce-writes` is passed. The real VPS restore still requires operator proof:
external registry release manifest, production env preflight, TLS, firewall/IP
allowlist, caller lifecycle proof, recall proof, graph smoke, and external
backup/restore drill.

## Implementation Proof

Completed on 2026-08-28.

Changed source:

- `infra/docker/compose.cell.yml`
- `.dockerignore`
- `infra/caddy/Caddyfile`
- `.env.production.example`
- `scripts/release/generate-cell-env.py`
- `scripts/release/prod-env-preflight.py`
- `scripts/release/backup_common.py`
- `scripts/release/export-cell-restore-bundle.py`
- `scripts/release/restore-cell-restore-bundle.py`
- `tests/test_prod_env_preflight_script.py`
- `tests/test_generate_cell_env.py`
- `tests/test_instance_agent_release.py`
- `tests/test_vps_restore_bundle.py`
- `runbooks/ks-state-civics-hetzner-vps-launch.md`
- `tickets/README.md`
- `tickets/WAVE-121-KS-civics-vps-go-live-handoff.md`

Verification:

- Production env preflight:
  `python scripts\release\prod-env-preflight.py --env-file .env.production.example`
  -> `PREFLIGHT PASS`.
- Docker focused tests:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_prod_env_preflight_script.py tests/test_generate_cell_env.py tests/test_instance_agent_release.py tests/test_backup_integrations.py tests/test_vps_restore_bundle.py`
  -> `37 passed`.
- Docker compile proof:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m py_compile scripts/release/generate-cell-env.py scripts/release/prod-env-preflight.py scripts/release/export-cell-restore-bundle.py scripts/release/restore-cell-restore-bundle.py`
  -> passed.
- Source package production gate:
  `python scripts\release\validate-instance-source-packages.py --instance ks-state-civics --production`
  -> `PASS instance=ks-state-civics packages=3 issues=0`.
- Kansas court source update dry run:
  `python scripts\release\instance-source-update.py --instance ks-state-civics --vector-store kansas-court-decisions --source kscourts-decisions --dry-run --production`
  -> `api_only_update_path=true`, `direct_storage_writes=false`,
  `mutation_performed=false`, `manifest_status=matches_lock`, and zero added,
  changed, or removed source records.
- Local serving-cell readiness:
  `/readyz` over the Docker network returned HTTP `200` with
  `{"ready":true,"db":true,"qdrant":true}` after the export restarted
  `api` and `worker`.
- Caller-style Topeka search:
  `POST /v1/vector_stores/vs_d4185d1004604f08a55299fa/search`
  returned three cited results from the full Topeka store.
- Caller-style Kansas court citator lens:
  `POST /v1/vector_stores/vs_a0d3ac76893e4f6f83bf2992/search`
  with `lens="court_citator"` returned five results with
  `graph_applied=true`, `graph_candidate_count=12`, and relation types
  `cited_authority`, `related_party`, and `same_docket`.
- Caller lifecycle proof:
  temporary admin, ingest, and search keys proved vector-store creation,
  file upload, direct file attach, file-batch attach, search with citations,
  and multi-store Responses file search. Temporary keys were revoked and the
  temporary proof stores/file were deleted after proof.
- Restorable local VPS bundle:
  `.release/cells/ks-state-civics/vps-handoff/ks-state-civics-vps-restore-20260828T152348Z.tar.gz`
  was generated with `--quiesce-writes` and validated with
  `restore-cell-restore-bundle.py --preflight-only`.
  The archive is `1,061,502,763` bytes with SHA-256
  `56f69e23ff828c8615f06309933aa29e78a359212e0574b8c9314141f96aadab`.
  It contains a `301,950,593` byte Postgres dump, two Qdrant collection
  snapshots, `object-store.tar.gz`, `minio-data.tar.gz`, `manifest.json`,
  `CHECKSUMS.sha256`, and `RESTORE.md` with Qdrant restore commands routed
  through the Compose network.

Remaining external operator gates:

- Publish the final committed images to an external registry and capture
  `.release/cells/ks-state-civics/external-registry-proof.json`. Post-commit
  attempt on 2026-08-28 built the images from a clean Docker context, then
  failed at Docker Hub push with `insufficient_scope: authorization failed` for
  `docker.io/expertaiservices/exai-vector-store-api`. Resolve Docker Hub
  authorization or switch to an approved registry, then rerun
  `external-registry-proof.py`.
- Provision the VPS, DNS, TLS, firewall/IP allowlist, and production secrets.
- Restore the generated bundle into the fresh VPS cell, then rerun cell smoke,
  caller lifecycle proof, recall proof, graph smoke, and external backup/restore
  proof from the VPS endpoint.
