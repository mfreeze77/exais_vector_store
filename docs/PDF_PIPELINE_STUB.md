# PDF Pipeline Stub

Your existing large PDF -> Markdown process is treated as production-ready external parsing.
ExAIS does not run Marker locally. When a raw PDF is uploaded through
`/api/v1/documents/upload`, the API calls the configured RunPod Marker endpoint,
stores the original PDF as a source artifact, and ingests the returned Markdown
through `pdf_markdown_external_v1`.

## Mode

`pdf_markdown_external_v1`

Expected input:

- Markdown content
- optional original PDF ID/path
- optional page markers
- optional section/page map

Raw PDF upload path:

- `MARKER_RUNPOD_API_KEY`
- `MARKER_RUNPOD_ENDPOINT_ID`
- `MARKER_MODE=remote`
- optional `MARKER_TIMEOUT_SEC`
- optional `MARKER_POLL_INTERVAL_SEC`
- optional `MARKER_MAX_ATTEMPTS`
- optional `MARKER_RETRY_BACKOFF_SEC`

`MARKER_*` variables are preferred. For local proof compatibility, if
`MARKER_RUNPOD_API_KEY` or `MARKER_RUNPOD_ENDPOINT_ID` is omitted, the client can
fall back to `RUNPOD_API_KEY` and `RUNPOD_ENDPOINT_ID`. Existing StateCivics
environments may supply the Marker-specific `RUNPOD_MARKER_ENDPOINT_ID` alias;
it takes precedence over the generic endpoint but not over
`MARKER_RUNPOD_ENDPOINT_ID`.

RunPod serverless protocol:

- `POST https://api.runpod.ai/v2/{endpoint_id}/run`
- `GET https://api.runpod.ai/v2/{endpoint_id}/status/{job_id}`

The submit payload is `{ "input": { "pdf_base64": "...", "filename": "source.pdf" } }`.
On `COMPLETED`, ExAIS reads Markdown from `output.text`, `output.markdown`, or
`output.markdown.content`.

RunPod cold-start/warm-up failures can surface as a terminal `FAILED` status.
ExAIS retries a fresh RunPod job for bounded transient classes such as transport
timeouts, HTTP 5xx/429, and known CUDA warm-up messages including `CUDA error`
or `no kernel image`. Retries are logged as attempts and stop at
`MARKER_MAX_ATTEMPTS`.

Secret-safe direct endpoint proof:

```powershell
$env:PYTHONPATH='packages/svs_common;apps/api;apps/worker;apps/model_gateway;apps/instance_agent'
python scripts/release/marker-runpod-proof.py --text-fixture "Hello Marker Proof" --attempts 4 --retry-backoff-seconds 30 --timeout-seconds 420
```

Cell-real upload/search proof after rebuilding the API image and restarting the
local cell:

```powershell
python scripts/release/pdf-upload-search-proof.py --cell local --require-page-start
```

Use `--pdf <path>` with a representative PDF if the generated proof fixture
does not preserve page markers in the Marker output.

Supported page markers in the scaffold chunker:

```markdown
<!-- page: 12 -->
# Section
...
```

or:

```markdown
Page 12
```

SVS owns chunking, embeddings, sparse indexing, citations, retrieval evals,
security, source PDF artifact storage, and audit. The external RunPod Marker
pipeline owns PDF parsing/OCR/table extraction upstream.
