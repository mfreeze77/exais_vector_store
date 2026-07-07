# WAVE-009 Local Restore And Ops Preflight

## Summary

Close the next set of Docker-proven operations gaps after Wave 008. This wave
stays local-first and excludes Docker Hub push, DNS/TLS, and real VPS launch. It
focuses on restore confidence, drift repair coverage, production env preflight,
host/admin access proof, and doc/proof convergence.

## Tickets

| Ticket | Status | Specialist | Scope |
| --- | --- | --- | --- |
| W9-001 | Complete | Test/Proof | Add a local backup/restore drill that proves a restored cell can boot, answer `/readyz`, preserve SQL counts, rebuild/verify Qdrant, and serve search. |
| W9-002 | Complete | Implementation | Add a repair-all drift operation that loops forced reindex batches or otherwise verifies Qdrant drift is resolved beyond a single ordered batch. |
| W9-003 | Complete | Implementation | Add a secret-safe production env preflight that rejects placeholders, dev mode, bad registry/version settings, missing required variables, and port collisions without printing secret values. |
| W9-004 | Complete | Test/Proof | Prove host/admin access on Windows Docker or document and automate the reliable fallback path for admin/API access when host loopback fails. |
| W9-005 | Complete | Test/Proof | Converge stale docs/proof counts after Waves 007-009 so README, gate docs, and ticket proof all describe the current verified surface. |

## Out Of Scope

- Docker Hub push.
- VPS launch.
- DNS/TLS setup.
- Real provider credentials.
- Changing tenant isolation, auth, RLS, ingestion atomicity, retrieval semantics,
  or security guardrails to make operations pass.

## Acceptance Criteria

- [x] W9-001 creates a reusable local restore drill command.
- [x] W9-001 drill creates a backup artifact without printing secrets.
- [x] W9-001 drill boots or uses a distinct restored cell namespace.
- [x] W9-001 drill proves `/readyz` returns HTTP `200` after restore.
- [x] W9-001 drill proves restored SQL counts match the source vector store.
- [x] W9-001 drill proves Qdrant contains restored or rebuilt points.
- [x] W9-001 drill proves restored search returns results from restored data.
- [x] W9-002 repair-all proof starts from deliberate Qdrant drift and exits only
  after count/search proof is clean.
- [x] W9-003 preflight prints variable names and issue classes only, never secret
  values.
- [x] W9-004 records a reproducible admin/API access path for this Windows Docker
  environment.
- [x] W9-005 removes or annotates stale proof counts that conflict with current
  Docker-cell evidence.

## Verification

```bash
PYTHONPATH=packages/svs_common;apps/api;apps/worker;apps/model_gateway;apps/instance_agent python -m compileall -f -q packages apps tests scripts
docker run --rm -v "${PWD}:/work" -w /work --network exais-vector-store-local_default -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_local_restore_drill_script.py tests/test_readyz.py tests/test_release_cell_network.py tests/test_qdrant_repair_proof_script.py
python scripts/release/local-restore-drill.py --source-cell restore-src --restore-cell restore --documents 12 --headings-per-doc 3 --source-port-base 28080 --restore-port-base 28180 --timeout-seconds 300
python scripts/release/qdrant-repair-all.py --cell local --proof --documents 24 --headings-per-doc 3 --batch-size 25 --delete-count 55 --timeout-seconds 600
python scripts/release/prod-env-preflight.py --env-file .env.production.example
python scripts/release/cell-access-proof.py --cell local
```

## Reusable Commands

Operator repair-all sweep for an existing vector store:

```bash
python scripts/release/qdrant-repair-all.py --cell local --vector-store-id vs_... --batch-size 250 --timeout-seconds 600
```

Deliberate drift proof, which creates a proof vector store and deletes Qdrant
points before repair:

```bash
python scripts/release/qdrant-repair-all.py --cell local --proof --documents 24 --headings-per-doc 3 --batch-size 25 --delete-count 55 --timeout-seconds 600
```

Production env preflight before VPS or customer-cell launch:

```bash
python scripts/release/prod-env-preflight.py --env-file /opt/exais/vector-store/.env.cell
```

Windows Docker API/admin access proof:

```bash
python scripts/release/cell-access-proof.py --cell local --timeout-seconds 60
```

## Proof Notes

- 2026-07-07 W9-001 added `scripts/release/local-restore-drill.py` and
  `tests/test_local_restore_drill_script.py`.
- Focused containerized script tests passed:
  `2 passed in 0.35s`.
- Live restore drill passed from registry-pulled images with distinct
  `restore-src` and `restore` compose namespaces. The script generated env files
  by printing variable names only and `No values printed.`
- Live restore proof values:
  - `restore_readyz_status=200`
  - `restore_sql_counts_before_reindex={"active_chunks": 48, "active_jobs": 0, "failed_jobs": 0, "indexed_chunks": 48}`
  - `restore_reindex_response processed=48`
  - `restore_qdrant_count=48`
  - `restore_search_results=5`
  - `restore_sql_counts_final={"active_chunks": 48, "active_jobs": 0, "failed_jobs": 0, "indexed_chunks": 48}`
- The restore drill cleaned up both temporary cell volumes after proof; the dump
  artifact and manifest remain under `.release/cells/restore/restore-drill-backup/`.
- 2026-07-07 W9-002 added cursor-aware `after_chunk_id` support to
  `/api/v1/maintenance/reindex`, returning `details.batch_size`,
  `details.has_more`, and `details.last_chunk_id` so repair operations can
  advance beyond the first ordered batch.
- `python scripts\release\build-images.py` rebuilt all app images from
  `VERSION=0.9.8-production-candidate`; the API image id was
  `sha256:1b7623b810f64967af01008196b5393bd9b82551b70e4ff9ca9f4111dbe6ec70`
  and worker image id was
  `sha256:a601bf3ddcfa3c579536ad92d7786104f5589595ce06ccdfec415e3186de0652`.
- `python scripts\release\publish-images.py` pushed the rebuilt tags to the
  local registry. Direct `docker manifest inspect localhost:5000/...` still hit
  the known Windows localhost lookup failure; the script verified manifests
  through `--network container:exais-local-registry`.
- `python scripts\release\cell-up.py --cell local --worker-scale 4
  --timeout-seconds 300` pulled the registry images and recreated app
  containers; compose showed all services healthy.
- Live repair-all proof:
  - `VECTOR_STORE_ID=vs_28771ee8d0a9441eb54ba7cb`
  - `repair_all_seed_sql_counts={"active_chunks": 96, "active_jobs": 0, "failed_jobs": 0, "indexed_chunks": 96}`
  - `qdrant_total_before_repair=96`
  - `repair_all_deleted_points=55`
  - `qdrant_total_after_delete=41`
  - `repair_all_iteration=1 processed=25 has_more=true last_chunk_id=chk_4f40172d2f314f418fecfa64`
  - `repair_all_iteration=2 processed=25 has_more=true last_chunk_id=chk_67710b5cfc2a4d79a459104e`
  - `repair_all_iteration=3 processed=25 has_more=true last_chunk_id=chk_c70ec06d4ecb447cbba43113`
  - `repair_all_iteration=4 processed=21 has_more=false last_chunk_id=chk_a372e003e19a464e8b466a79`
  - `repair_all_total_processed=96`
  - `qdrant_total_after_repair_all=96`
  - `repair_all_search_results=5`
  - `repair_all_sql_counts_final={"active_chunks": 96, "active_jobs": 0, "failed_jobs": 0, "indexed_chunks": 96}`
- 2026-07-07 W9-003 added `scripts/release/prod-env-preflight.py`,
  `tests/test_prod_env_preflight_script.py`, and port/public API settings to
  `.env.production.example`.
- Focused preflight tests passed inside the registry-pulled API image:
  `3 passed in 0.25s`.
- `.env.production.example` preflight failed as expected while printing only
  variable names and issue classes:
  - `Issue count: 10`
  - `FAIL PLACEHOLDER POSTGRES_PASSWORD`
  - `FAIL PLACEHOLDER POSTGRES_APP_PASSWORD`
  - `FAIL PLACEHOLDER DATABASE_URL`
  - `FAIL PLACEHOLDER DATABASE_URL_SYNC`
  - `FAIL PLACEHOLDER DATABASE_URL_MIGRATIONS`
  - `FAIL PLACEHOLDER OPENSEARCH_PASSWORD`
  - `FAIL PLACEHOLDER S3_ACCESS_KEY_ID`
  - `FAIL PLACEHOLDER S3_SECRET_ACCESS_KEY`
  - `FAIL PLACEHOLDER OPENAI_API_KEY`
  - `FAIL PLACEHOLDER SVS_API_KEY_PEPPER`
- Ignored proof env `.release/preflight/good.env` passed:
  - `Issue count: 0`
  - `PREFLIGHT PASS`
- Ignored proof env `.release/preflight/bad.env` failed targeted checks without
  printing values:
  - `Issue count: 5`
  - `FAIL DEV_MODE_ENABLED SVS_DEV_MODE`
  - `FAIL BAD_VERSION SVS_VERSION`
  - `FAIL LATEST_TAG SVS_VERSION`
  - `FAIL LOCAL_REGISTRY_PREFIX SVS_REGISTRY_PREFIX`
  - `FAIL PORT_COLLISION SVS_API_PORT,SVS_ADMIN_UI_PORT`
- 2026-07-07 W9-004 added `scripts/release/cell-access-proof.py`,
  `tests/test_cell_access_proof_script.py`, and a narrow Vite `allowedHosts`
  config for `admin-ui`, `localhost`, and `127.0.0.1`.
- `python scripts\release\build-images.py --service admin-ui` rebuilt the admin
  UI image as
  `sha256:4179f3841c703c7f6c4c6377db3c430f479cbe3aa5fc6f5bad3a2cd562584a69`.
- `python scripts\release\publish-images.py --service admin-ui` pushed the
  rebuilt tag and verified the manifest through the local registry container
  fallback.
- `python scripts\release\cell-up.py --cell local --worker-scale 4
  --timeout-seconds 300` pulled the registry image and recreated the admin UI
  container; compose showed all services healthy.
- Live access proof:
  - `API_HOST_STATUS=UNAVAILABLE`
  - `API_HOST_REASON=URLError`
  - `API_CELL_NETWORK_STATUS=200`
  - `ADMIN_UI_HOST_STATUS=UNAVAILABLE`
  - `ADMIN_UI_HOST_REASON=URLError`
  - `ADMIN_UI_CELL_NETWORK_STATUS=200`
  - `ACCESS_PATH=cell-network-fallback`
- 2026-07-07 W9-005 converged current proof docs:
  - `README.md`
  - `VALIDATION.md`
  - `docs/GATE_1_PUBLISH.md`
  - `docs/GATE_2_SCALE.md`
  - `docs/ARTIFACT_MANIFEST.md`
  - `docs/COMPLETION_MATRIX_V0_9_8.md`
  - `docs/V0_9_8_PATCH_REPORT.md`
- Current non-integration pulled-image test count is
  `46 passed, 2 warnings in 5.56s`; focused Wave 009 release tests are
  `20 passed, 2 warnings in 6.03s`.
- Current API route counts remain `FastAPI routes: 45` and `OpenAPI paths: 34`.
- Updated docs explicitly keep Docker Hub push, DNS/TLS, real provider
  credentials, and VPS launch outside the local proof claim.
