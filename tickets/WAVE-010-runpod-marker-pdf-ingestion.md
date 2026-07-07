# WAVE-010 RunPod Marker PDF Ingestion

## Summary

Bring the CSCAi RunPod Marker client contract into ExAIS Vector Store so raw PDF
uploads can enter the existing OpenAI-compatible vector-store ingestion path
without pretending ExAIS runs a local PDF parser.

Source anchors copied/adapted from `C:\Users\mfrie\Ai_Projects\CSCAi-repo`:

- `services/drawing-ingest/src/vendor/marker_client.py`
- `services/drawing-ingest/tests/test_marker_client.py`
- `tickets/TKT-149-vendor-ingest-preprocess-via-external-marker.md`

## Tickets

| Ticket | Status | Specialist | Scope |
| --- | --- | --- | --- |
| W10-001 | Complete | Implementation | Port the raw RunPod Marker `/run` + `/status/{job_id}` client into `svs_common` with secret-safe logging and tests. |
| W10-002 | Complete | Implementation | Route raw PDF multipart upload through RunPod Marker and ingest the returned Markdown as `pdf_markdown_external_v1`. |
| W10-003 | Complete | Test/Proof | Add focused tests for Marker protocol handling, PDF mode routing, and converted upload request metadata. |
| W10-004 | Complete | Test/Proof | Run a real configured RunPod Marker PDF conversion and then prove the rebuilt ExAIS cell uploads/searches page-aware PDF chunks. |
| W10-005 | Complete | Implementation | Add bounded retry for RunPod Marker warm-up/transient failures, including CUDA no-kernel warm-up failures observed during live proof. |

## Out Of Scope

- Docker Hub push or VPS deployment.
- Installing or running Marker inside ExAIS containers.
- CSCAi vendor-corpus folder UI, folder expert creation, or citation basename
  rules.
- Native/raw PDF parsing without the external Marker endpoint.
- Printing or committing any RunPod secret values.

## Acceptance Criteria

- [x] ExAIS has a reusable RunPod Marker client that uses
  `POST /v2/{endpoint_id}/run` and `GET /v2/{endpoint_id}/status/{job_id}`.
- [x] `MARKER_MODE` accepts only `remote`; `local` and `auto` are rejected.
- [x] Missing Marker configuration fails before a raw PDF is silently decoded as
  gibberish text.
- [x] Multipart PDF upload converts to `pdf_markdown_external_v1` before
  chunking/indexing.
- [x] The original PDF is preserved as an object-store source artifact reference.
- [x] Document attributes include only secret-safe parser/source metadata.
- [x] Env templates and generated local-cell envs include the Marker variable
  names without values.
- [x] Unit tests mock RunPod with no network calls and prove API keys do not
  appear in synthetic log lines.
- [x] A terminal RunPod `FAILED` status with CUDA/no-kernel warm-up text retries
  a fresh RunPod job and records attempt logs.
- [x] Real RunPod endpoint proof is captured with raw command output after a
  configured endpoint completes a conversion.
- [x] A rebuilt local ExAIS cell uploads a raw PDF through
  `/api/v1/documents/upload`, ingests the Marker Markdown, and returns a search
  result with page-aware citation fields.

## Verification

```bash
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests scripts
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_marker_client.py tests/test_pdf_marker_upload.py tests/test_router.py tests/test_chunking.py
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
python scripts/release/generate-cell-env.py --cell config-proof --registry-prefix localhost:5000/expertaiservices
docker-compose --env-file .release\cells\config-proof\.env.cell -f infra\docker\compose.cell.yml -p exais-vector-store-config-proof config
docker run --rm -v "${PWD}:/work" -w /work --env-file .env -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python scripts/release/marker-runpod-proof.py --text-fixture "Hello Marker Proof" --attempts 4 --retry-backoff-seconds 30 --timeout-seconds 420
python scripts/release/pdf-upload-search-proof.py --cell local --require-page-start
```

## Proof Notes

- CSCAi's local Marker adapter was not copied. ExAIS uses only the external
  RunPod Marker protocol because local Marker remains outside the container
  product scope.
- Focused mocked-provider proof passed inside the registry-pulled API image
  with the mounted workspace:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_chunking.py tests/test_marker_client.py tests/test_pdf_marker_upload.py tests/test_router.py
................                                                         [100%]
16 passed, 2 warnings in 5.20s
```

- Full mounted-workspace non-integration proof passed inside the
  registry-pulled API image:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
..........................................................               [100%]
58 passed, 2 warnings in 6.29s
```

- Mounted-workspace compile proof passed inside the registry-pulled API image:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests scripts
exit=0
```

- Secret-safe generated env and release compose validation passed. The env
  generator printed variable names only:

```text
python scripts/release/generate-cell-env.py --cell config-proof --registry-prefix localhost:5000/expertaiservices
Generated env file: C:\Users\mfrie\Ai_Projects\exais_vector_store\.release\cells\config-proof\.env.cell
Variable names written:
- MARKER_RUNPOD_API_KEY
- MARKER_RUNPOD_ENDPOINT_ID
- MARKER_MODE
- MARKER_TIMEOUT_SEC
- MARKER_POLL_INTERVAL_SEC
- MARKER_MAX_ATTEMPTS
- MARKER_RETRY_BACKOFF_SEC
No values printed.
```

  Filtered release compose config output shows version-pinned registry images
  and empty Marker secrets for the generated config-proof cell:

```text
docker-compose --env-file .release\cells\config-proof\.env.cell -f infra\docker\compose.cell.yml -p exais-vector-store-config-proof config | findstr /C:"image: localhost:5000/expertaiservices/exai-vector-store" /C:"MARKER_MODE" /C:"MARKER_RUNPOD_API_KEY" /C:"MARKER_RUNPOD_ENDPOINT_ID"
    image: localhost:5000/expertaiservices/exai-vector-store-admin-ui:0.9.8-production-candidate
      MARKER_MODE: remote
      MARKER_RUNPOD_API_KEY: ""
      MARKER_RUNPOD_ENDPOINT_ID: ""
    image: localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate
      MARKER_MODE: remote
      MARKER_RUNPOD_API_KEY: ""
      MARKER_RUNPOD_ENDPOINT_ID: ""
    image: localhost:5000/expertaiservices/exai-vector-store-model-gateway:0.9.8-production-candidate
      MARKER_MODE: remote
      MARKER_RUNPOD_API_KEY: ""
      MARKER_RUNPOD_ENDPOINT_ID: ""
    image: localhost:5000/expertaiservices/exai-vector-store-worker:0.9.8-production-candidate
```

- Initial direct live RunPod Marker proof was attempted with a small CSCAi
  fixture and secret-safe output. The endpoint accepted the job but the remote
  worker failed before returning Markdown:

```text
env_names_present=MARKER_RUNPOD_API_KEY,MARKER_RUNPOD_ENDPOINT_ID,MARKER_MODE
fixture_bytes=750
marker_log=submitted job_id=88478ef9-4a6a-423b-9ebe-0b424e18046c-u1
marker_log=polling status=IN_QUEUE
marker_log=polling status=IN_PROGRESS
marker_log=polling status=FAILED
marker_log=failed status=FAILED error=CUDA error: no kernel image is available for execution on the device
CUDA kernel errors might be asynchronously reported at some other API call, so the stacktrace below might be incorrect.
For debugging consider passing CUDA_LAUNCH_BLOCKING=1
Compile with `TORCH_USE_CUDA_DSA` to enable device-side assertions.

marker_result_present=False
```

- W10-005 added bounded retry because this failure class can be a RunPod warm-up
  issue. Focused mocked-provider proof now includes the CUDA/no-kernel retry
  path:

```text
.............                                                            [100%]
13 passed, 2 warnings in 4.31s
```

- Direct live proof with retry still hit the same remote CUDA worker failure on
  every attempt. This proves ExAIS submits fresh retry jobs, but the configured
  endpoint did not complete conversion during this run:

```text
env_names_present=MARKER_RUNPOD_API_KEY,MARKER_RUNPOD_ENDPOINT_ID,MARKER_MODE
retry_names=MARKER_MAX_ATTEMPTS,MARKER_RETRY_BACKOFF_SEC
fixture_bytes=976
marker_log=attempt start attempt=1 max_attempts=4
marker_log=submitted job_id=6577f3ad-7cb2-4781-b440-19c3d18652c5-u2
marker_log=polling status=IN_QUEUE
marker_log=polling status=IN_PROGRESS
marker_log=polling status=FAILED
marker_log=failed status=FAILED error=CUDA error: no kernel image is available for execution on the device
CUDA kernel errors might be asynchronously reported at some other API call, so the stacktrace below might be incorrect.
For debugging consider passing CUDA_LAUNCH_BLOCKING=1
Compile with `TORCH_USE_CUDA_DSA` to enable device-side assertions.

marker_log=retrying attempt=2 max_attempts=4
marker_log=attempt start attempt=2 max_attempts=4
marker_log=submitted job_id=5322e58b-ccdc-4cc4-93ab-4eb6d988cfc0-u1
marker_log=polling status=IN_QUEUE
marker_log=polling status=IN_PROGRESS
marker_log=polling status=FAILED
marker_log=failed status=FAILED error=CUDA error: no kernel image is available for execution on the device
CUDA kernel errors might be asynchronously reported at some other API call, so the stacktrace below might be incorrect.
For debugging consider passing CUDA_LAUNCH_BLOCKING=1
Compile with `TORCH_USE_CUDA_DSA` to enable device-side assertions.

marker_log=retrying attempt=3 max_attempts=4
marker_log=attempt start attempt=3 max_attempts=4
marker_log=submitted job_id=f6615e5d-362f-4be5-b3dd-6990f3e621c0-u1
marker_log=polling status=IN_QUEUE
marker_log=polling status=IN_PROGRESS
marker_log=polling status=FAILED
marker_log=failed status=FAILED error=CUDA error: no kernel image is available for execution on the device
CUDA kernel errors might be asynchronously reported at some other API call, so the stacktrace below might be incorrect.
For debugging consider passing CUDA_LAUNCH_BLOCKING=1
Compile with `TORCH_USE_CUDA_DSA` to enable device-side assertions.

marker_log=retrying attempt=4 max_attempts=4
marker_log=attempt start attempt=4 max_attempts=4
marker_log=submitted job_id=510e17ca-b738-40f3-8b76-1dcb0963179b-u2
marker_log=polling status=IN_QUEUE
marker_log=polling status=IN_PROGRESS
marker_log=polling status=FAILED
marker_log=failed status=FAILED error=CUDA error: no kernel image is available for execution on the device
CUDA kernel errors might be asynchronously reported at some other API call, so the stacktrace below might be incorrect.
For debugging consider passing CUDA_LAUNCH_BLOCKING=1
Compile with `TORCH_USE_CUDA_DSA` to enable device-side assertions.

marker_result_present=False
```

- `scripts/release/marker-runpod-proof.py` now provides a repeatable,
  secret-safe proof command for this endpoint.
- The alternate RunPod endpoint supplied through the existing `RUNPOD_*`
  variables completed successfully when mapped into `MARKER_RUNPOD_*`. A tiny
  CSCAi PDF fixture completed but returned an empty `markdown` field:

```text
env_names_present=MARKER_RUNPOD_API_KEY,MARKER_RUNPOD_ENDPOINT_ID,MARKER_MODE
marker_log=attempt start attempt=1 max_attempts=1
marker_log=submitted job_id=0f73e2e6-acc4-4bab-964e-04027f413b19-u1
marker_log=polling status=IN_QUEUE
marker_log=polling status=IN_PROGRESS
marker_log=polling status=COMPLETED
marker_log=completed status=COMPLETED
result_present=True
output_top_keys=['filename', 'markdown', 'pages', 'processing_time_seconds']
output_field=filename type=str chars=11
output_field=markdown type=str chars=0
output_field=pages type=int
output_field=processing_time_seconds type=float
```

- A generated one-page text PDF proved the alternate endpoint returns Markdown:

```text
env_names_present=MARKER_RUNPOD_API_KEY,MARKER_RUNPOD_ENDPOINT_ID,MARKER_MODE
generated_pdf_bytes=593
marker_log=attempt start attempt=1 max_attempts=3
marker_log=submitted job_id=c41a776b-3d0a-46ef-a1f4-e9b58cd03891-u1
marker_log=polling status=IN_QUEUE
marker_log=polling status=IN_PROGRESS
marker_log=polling status=COMPLETED
marker_log=completed status=COMPLETED
marker_result_present=True
output_top_keys=['filename', 'markdown', 'pages', 'processing_time_seconds']
markdown_chars=21
markdown_preview=## Hello Marker Proof
```

- Current canonical direct proof runs inside the registry-pulled API image with
  the mounted workspace and local `.env`. It prints env variable names only:

```text
docker run --rm -v "${PWD}:/work" -w /work --env-file .env -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python scripts/release/marker-runpod-proof.py --text-fixture "Hello Marker Proof" --attempts 4 --retry-backoff-seconds 30 --timeout-seconds 420
env_names_present=MARKER_RUNPOD_API_KEY,MARKER_RUNPOD_ENDPOINT_ID,MARKER_MODE
retry_names=MARKER_MAX_ATTEMPTS,MARKER_RETRY_BACKOFF_SEC
pdf_name=generated-marker-proof.pdf
pdf_bytes=593
pdf_sha256=05e80ced32839c43
marker_log=attempt start attempt=1 max_attempts=4
marker_log=submitted job_id=696f1530-a61e-4449-9a65-959111969a0f-u1
marker_log=polling status=IN_QUEUE
marker_log=polling status=IN_PROGRESS
marker_log=polling status=COMPLETED
marker_log=completed status=COMPLETED
marker_result_present=True
markdown_chars=21
markdown_sha256=ebed9352b5be7e45
output_keys=['filename', 'markdown', 'pages', 'processing_time_seconds']
```

- The API image was rebuilt and pushed to the local registry with the repo
  `VERSION` tag after the PDF upload and page-marker changes:

```text
python scripts\release\build-images.py --registry-prefix localhost:5000/expertaiservices --service api
VERSION=0.9.8-production-candidate
Successfully built 56d3978b550e
Successfully tagged localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate
localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate	sha256:56d3978b550e97cfe0bd204cc02835df783972f50edfb2a5afad0a72f51ed2ca	142311666

python scripts\release\publish-images.py --registry-prefix localhost:5000/expertaiservices --service api
0.9.8-production-candidate: digest: sha256:56d3978b550e97cfe0bd204cc02835df783972f50edfb2a5afad0a72f51ed2ca size: 2942
docker run --rm --network container:exais-local-registry curlimages/curl:8.10.1 -fsS -H "Accept: application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json, application/vnd.docker.distribution.manifest.list.v2+json" http://127.0.0.1:5000/v2/expertaiservices/exai-vector-store-api/manifests/0.9.8-production-candidate
"schemaVersion": 2
```

- The local cell was refreshed from registry images and every service is
  healthy:

```text
python scripts\release\cell-up.py --cell local --worker-scale 4 --timeout-seconds 300
exais-vector-store-local-api-1             localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate             "uvicorn svs_api.mai…"   api             9 seconds ago       Up 6 seconds (healthy)       0.0.0.0:18080->8080/tcp, [::]:18080->8080/tcp
exais-vector-store-local-worker-1          localhost:5000/expertaiservices/exai-vector-store-worker:0.9.8-production-candidate          "python -m svs_worke…"   worker          2 minutes ago       Up 2 minutes (healthy)       8082/tcp
exais-vector-store-local-worker-2          localhost:5000/expertaiservices/exai-vector-store-worker:0.9.8-production-candidate          "python -m svs_worke…"   worker          2 minutes ago       Up 2 minutes (healthy)       8082/tcp
exais-vector-store-local-worker-3          localhost:5000/expertaiservices/exai-vector-store-worker:0.9.8-production-candidate          "python -m svs_worke…"   worker          2 minutes ago       Up 2 minutes (healthy)       8082/tcp
exais-vector-store-local-worker-4          localhost:5000/expertaiservices/exai-vector-store-worker:0.9.8-production-candidate          "python -m svs_worke…"   worker          2 minutes ago       Up 2 minutes (healthy)       8082/tcp
```

- The refreshed API container contains the Marker module and upload helper, and
  `/readyz` returns `200` from inside the API container:

```text
docker exec exais-vector-store-local-api-1 python -c "import importlib.util; print('marker_module_present=' + str(importlib.util.find_spec('svs_common.marker_client') is not None))"
marker_module_present=True
docker exec exais-vector-store-local-api-1 python -c "import svs_api.main as m; print('marker_upload_helper_present=' + str(hasattr(m, 'marker_pdf_upload_request')))"
marker_upload_helper_present=True
docker exec exais-vector-store-local-api-1 curl -fsS -w "`n%{http_code}`n" http://127.0.0.1:8080/readyz
{"ready":true,"db":true,"qdrant":true}
200
```

- Strict live PDF upload/search proof passed through the rebuilt local cell.
  Host loopback still fails on this Windows host, so the script uses the Docker
  cell-network fallback for API calls:

```text
python scripts\release\pdf-upload-search-proof.py --cell local --require-page-start --timeout-seconds 900
pdf_fixture=C:\Users\mfrie\Ai_Projects\exais_vector_store\.release\cells\local\marker-proof\generated-marker-upload-proof.pdf
pdf_bytes=628
POST http://localhost:18080/v1/vector_stores -> host request failed: <urlopen error [Errno 11003] getaddrinfo failed>
POST http://api:8080/v1/vector_stores -> 200
VECTOR_STORE_ID=vs_020dd87c25ca4bd5bc6463f7
curl: (7) Failed to connect to localhost port 18080 after 2 ms: Could not connect to server
upload_cell_network_status=200
upload_status=completed
document_id=doc_3c93ae698256423082e66dc1
vector_store_file_id=vsf_db56722f5a154bd188258d55
POST http://api:8080/api/v1/retrieval/search -> 200
search_results=2
first_chunk_id=chk_1df83298a8b042239b677d05
first_page_start=1
first_page_end=1
first_source=hybrid_rrf
```
