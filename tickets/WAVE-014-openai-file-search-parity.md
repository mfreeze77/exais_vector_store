# WAVE-014 OpenAI File Search Parity

## Summary

Turn OpenAI File Search parity from a loose aspiration into an auditable
contract for agent-facing vector-store search. The public surface should feel
like OpenAI: create a vector store, attach files or batches, wait for processing,
then search the vector store with OpenAI-shaped request and response semantics.
ExAIS may own different internals, but drift must be explicit and tested.

## Background

OpenAI documents File Search as a hosted tool over vector stores: files are
parsed, chunked, embedded, and stored for semantic plus keyword search. Current
ExAIS local proof owns those same stages locally, but the compatibility surface
had gaps: `max_num_results`, OpenAI-style filters, `ranking_options`,
`rewrite_query`, and file-level search-result metadata were not pinned as an
auditable contract.

Official OpenAI references checked on 2026-07-07:

- https://developers.openai.com/api/docs/assistants/tools/file-search
- https://developers.openai.com/api/docs/guides/tools-file-search
- https://developers.openai.com/api/reference/resources/vector_stores/methods/search/

## Tickets

| Ticket | Status | Type | Outcome |
|---|---|---|---|
| W14-001 | Complete | Implementation/Test | Make `/v1/vector_stores/{id}/search` consume OpenAI-shaped search fields, return file-level metadata, and reject unsupported parity features instead of silently ignoring them. |
| W14-002 | Complete | Implementation/Test | Add file-attribute filter support by indexing safe file attributes into Postgres/Qdrant search payloads without weakening tenant or ACL checks. |
| W14-003 | Complete | Implementation/Test | Add query rewrite/decomposition as an explicit optional stage with audit-visible rewritten query text and fallback behavior. |
| W14-004 | Complete | Implementation/Test | Add normalized ranking/reranking semantics so `ranking_options.score_threshold` and ranker selection match the OpenAI contract closely enough for agents. |
| W14-005 | Complete | Test/Proof | Build an OpenAI File Search parity eval harness using ticket-folder fixtures and golden expected chunks. |

## W14-001 Acceptance Criteria

- [x] OpenAI-compatible vector-store search accepts `max_num_results` and maps it
  to internal retrieval `top_k`.
- [x] Existing ExAIS ops scripts that still send `top_k` to the compatibility
  route keep their intended result count while `max_num_results` becomes the
  preferred OpenAI-shaped field.
- [x] `max_num_results` is bounded to OpenAI's 1..50 result range.
- [x] Search response includes `object`, `search_query`, `data`, `has_more`, and
  `next_page`.
- [x] Search result rows use vector-store file IDs, filenames, and file-level
  attributes when available.
- [x] Unsupported OpenAI parity fields are explicit 422 errors, not silent
  no-ops: unknown request fields, `rewrite_query=true`, non-zero
  `ranking_options.score_threshold`, unsupported filter keys, unsupported
  filter operations, and `or` filters.
- [x] Tests cover request mapping, unsupported drift guards, and result page
  formatting.

## W14-001 Verification

```powershell
$env:PYTHONPATH="packages/svs_common;apps/api;apps/worker;apps/model_gateway;apps/instance_agent"; python -m pytest -q -rs tests/test_openai_compat_search.py
```

Containerized proof on the registry-pulled API image with the working tree
mounted:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_retrieval_profile_resolution.py
.............                                                            [100%]
13 passed in 1.67s
```

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests
[exit 0]
```

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
........................................................................ [ 82%]
...............                                                          [100%]
=============================== warnings summary ===============================
apps/api/svs_api/main.py:73
  /work/apps/api/svs_api/main.py:73: DeprecationWarning:
          on_event is deprecated, use lifespan event handlers instead.

          Read more in the FastAPI docs for Lifespan Events.

    @app.on_event('startup')

../usr/local/lib/python3.12/site-packages/fastapi/applications.py:4495
  /usr/local/lib/python3.12/site-packages/fastapi/applications.py:4495: DeprecationWarning:
          on_event is deprecated, use lifespan event handlers instead.

          Read more in the FastAPI docs for Lifespan Events.

    return self.router.on_event(event_type)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
87 passed, 2 warnings in 5.50s
```

```text
git diff --check
[exit 0]
```

## W14 Rebuild And Live Cell Proof

After W14-002..005, all app images were rebuilt, pushed to the local registry,
and the local cell was restarted with four workers from the rebuilt tags.

```text
python scripts\release\build-images.py
...
[build-images] Building api -> localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate
...
localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate -> sha256:ed03ad5d1dbffe9d822d36c8142a00011a32c4b0c926573ef83258478f8f7e20
localhost:5000/expertaiservices/exai-vector-store-worker:0.9.8-production-candidate -> sha256:2cd00e58b6371fa93ce251464ee3363bd316e0dd36aaab2b6d59446d946d752c
localhost:5000/expertaiservices/exai-vector-store-model-gateway:0.9.8-production-candidate -> sha256:8209e2b50fe7e74c688285864eb7fd024a4465a8f3e47fa769740fc7243afe33
localhost:5000/expertaiservices/exai-vector-store-admin-ui:0.9.8-production-candidate -> sha256:111673b5a668e19c968d96f406d6ae2cb2b8bc30575a04223519b2cfd0c240af
localhost:5000/expertaiservices/exai-vector-store-instance-agent:0.9.8-production-candidate -> sha256:6bc0d5c9b713cd365a63441122fb28acdbd52a8b5d7c4d6d2518a10e94f1f801
```

```text
python scripts\release\publish-images.py
...
[publish-images] Registry manifest probe ok for localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate
[publish-images] Registry manifest probe ok for localhost:5000/expertaiservices/exai-vector-store-worker:0.9.8-production-candidate
[publish-images] Registry manifest probe ok for localhost:5000/expertaiservices/exai-vector-store-model-gateway:0.9.8-production-candidate
[publish-images] Registry manifest probe ok for localhost:5000/expertaiservices/exai-vector-store-admin-ui:0.9.8-production-candidate
[publish-images] Registry manifest probe ok for localhost:5000/expertaiservices/exai-vector-store-instance-agent:0.9.8-production-candidate
```

```text
python scripts\release\cell-up.py --cell local --worker-scale 4 --timeout-seconds 420
...
exais-vector-store-local-api-1             Up ... (healthy)
exais-vector-store-local-worker-1          Up ... (healthy)
exais-vector-store-local-worker-2          Up ... (healthy)
exais-vector-store-local-worker-3          Up ... (healthy)
exais-vector-store-local-worker-4          Up ... (healthy)
exais-vector-store-local-model-gateway-1   Up ... (healthy)
exais-vector-store-local-admin-ui-1        Up ... (healthy)
```

```text
docker run --rm --network exais-vector-store-local_default curlimages/curl:8.10.1 -fsS http://api:8080/readyz
{"ready":true,"db":true,"qdrant":true}

docker run --rm --network exais-vector-store-local_default curlimages/curl:8.10.1 -fsS http://model-gateway:8081/healthz
{"ok":true,"service":"svs-model-gateway","version":"0.9.8-production-candidate"}
```

Live OpenAI File Search parity eval against the rebuilt local cell:

```text
docker run --rm -v "${PWD}:/work" -w /work --network exais-vector-store-local_default -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python scripts/release/openai-file-search-parity-eval.py --api http://api:8080
vector_store_id=vs_3902a1a794464b249900cb40
attached case=runpod_marker_warmup_ticket file_id=vsf_926f89b66e9b448d8a929015
attached case=real_embedding_provider_ticket file_id=vsf_bdb00ee5c11f401fbac0c0a1
query case=runpod_marker_warmup_ticket passed=True results=5 search_query=RunPod Marker warmup retry and PDF ingestion proof missing=[]
query case=real_embedding_provider_ticket passed=True results=5 search_query=What ticket proved real embeddings instead of hash mock fallback missing=[]
summary passed=2 total=2
```

Scoped cleanup after the rebuild removed no unrelated containers and left only
the normal local cell running:

```text
docker ps -a --format "{{.Names}}|{{.Status}}|{{.Image}}" | Select-String "exais-vector-store-parity|openai-file-search|exais-vector-store-test|exais-vector-store-temp"
[no output]

docker image prune -f --filter "label=com.exais.service"
Total reclaimed space: 0B
```

Broad non-integration regression proof:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests --ignore=tests/integration
........................................................................ [ 71%]
.............................                                            [100%]
=============================== warnings summary ===============================
apps/api/svs_api/main.py:76
  /work/apps/api/svs_api/main.py:76: DeprecationWarning:
          on_event is deprecated, use lifespan event handlers instead.

../usr/local/lib/python3.12/site-packages/fastapi/applications.py:4495
  /usr/local/lib/python3.12/site-packages/fastapi/applications.py:4495: DeprecationWarning:
          on_event is deprecated, use lifespan event handlers instead.

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
101 passed, 2 warnings in 5.21s
```

Live integration proof against the local cell network. The four local worker
containers were stopped for the test run to avoid racing the test-owned worker,
then started again after the run:

```text
docker stop exais-vector-store-local-worker-4 exais-vector-store-local-worker-3 exais-vector-store-local-worker-2 exais-vector-store-local-worker-1
exais-vector-store-local-worker-4
exais-vector-store-local-worker-3
exais-vector-store-local-worker-2
exais-vector-store-local-worker-1

docker run --rm -v "${PWD}:/work" -w /work --network exais-vector-store-local_default -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent -e SVS_RUN_INTEGRATION=1 -e DATABASE_URL_MIGRATIONS -e SVS_TEST_APP_DSN -e DATABASE_URL -e SVS_TEST_QDRANT_URL -e SVS_TEST_QDRANT_OUTAGE_URL -e SVS_DEV_MODE=false -e DEFAULT_EMBEDDING_PROVIDER=hash_mock localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/integration
.....                                                                    [100%]
=============================== warnings summary ===============================
tests/integration/test_postgres_rls_and_worker.py::test_worker_completes_real_document_against_live_postgres
tests/integration/test_postgres_rls_and_worker.py::test_worker_completes_real_document_against_live_postgres
tests/integration/test_postgres_rls_and_worker.py::test_qdrant_outage_retries_to_terminal_failure_without_ghost_documents
tests/integration/test_postgres_rls_and_worker.py::test_qdrant_outage_retries_to_terminal_failure_without_ghost_documents
tests/integration/test_postgres_rls_and_worker.py::test_qdrant_outage_retries_to_terminal_failure_without_ghost_documents
tests/integration/test_postgres_rls_and_worker.py::test_qdrant_outage_retries_to_terminal_failure_without_ghost_documents
tests/integration/test_postgres_rls_and_worker.py::test_qdrant_outage_retries_to_terminal_failure_without_ghost_documents
tests/integration/test_postgres_rls_and_worker.py::test_qdrant_outage_retries_to_terminal_failure_without_ghost_documents
  /usr/local/lib/python3.12/site-packages/botocore/auth.py:424: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version.

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
5 passed, 8 warnings in 4.84s

docker start exais-vector-store-local-worker-4 exais-vector-store-local-worker-3 exais-vector-store-local-worker-2 exais-vector-store-local-worker-1
exais-vector-store-local-worker-4
exais-vector-store-local-worker-3
exais-vector-store-local-worker-2
exais-vector-store-local-worker-1
```

## Out Of Scope For W14-001

- Full OpenAI file-attribute filtering.
- Query rewriting or multi-query decomposition.
- External reranker integration.
- Normalizing ExAIS RRF scores to OpenAI-style 0..1 scores.
- Docker rebuild or live cell proof.

## W14-002 Acceptance Criteria

- [x] OpenAI-style `eq` filters on file attributes are accepted and mapped to
  internal `file_attribute_filters`.
- [x] Safe primitive file attributes are copied into Qdrant/OpenSearch payloads
  for new ingests.
- [x] OpenSearch maps `file_attr_*` fields as keyword values for exact filters.
- [x] Sensitive or structured attributes are not copied into retrieval payloads.
- [x] Postgres search and hydration enforce file-attribute filters under the
  existing tenant/business/security scope.
- [x] Qdrant/OpenSearch filters use the same sanitized payload keys as ingestion.

## W14-003 Acceptance Criteria

- [x] `rewrite_query=true` is accepted on the OpenAI-compatible search route.
- [x] Query planning strips request filler and creates bounded subqueries for
  compound searches.
- [x] Retrieval audit metadata records the effective query, subqueries, rewrite
  flag, ranker, and score threshold.
- [x] The response `search_query` reports the effective query used for search.

## W14-004 Acceptance Criteria

- [x] `ranking_options.score_threshold` is supported.
- [x] Compatibility search scores are normalized into a 0..1 range before
  threshold filtering.
- [x] `ranking_options.ranker` accepts OpenAI values while ExAIS keeps the
  current local RRF/ranking implementation.
- [x] Result count still honors `max_num_results` or the deprecated `top_k`
  alias.

## W14-005 Acceptance Criteria

- [x] `evals/openai-file-search-parity/ticket_golden.json` defines ticket-folder
  fixtures and expected text.
- [x] `scripts/release/openai-file-search-parity-eval.py` creates a vector store,
  attaches ticket fixtures, runs OpenAI-shaped searches, and scores expected
  result text.
- [x] Unit proof covers fixture validity and scoring behavior.

## W14-002..005 Verification

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_openai_compat_search.py tests/test_query_planner.py tests/test_retrieval_profile_resolution.py tests/test_openai_file_search_parity_eval.py tests/test_opensearch_adapter.py
...........................                                              [100%]
27 passed in 2.05s
```

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m compileall -f -q packages apps tests scripts
[exit 0]
```

```text
git diff --check
[exit 0]
```
