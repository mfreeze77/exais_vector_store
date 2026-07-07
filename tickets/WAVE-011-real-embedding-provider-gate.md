# WAVE-011 Real Embedding Provider Gate

## Summary

Fix the release-blocking embedding-provider bug where a real embedding profile
could silently produce `hash_mock` vectors when its provider configuration was
missing from the running cell.

The immediate failure found during ticket-corpus vectorization:

- `markdown_docs_v1` selected `openai_text_embedding_3_small_1536`.
- The local Docker cell had `OPENAI_API_KEY` empty in `.release/cells/local/.env.cell`.
- Provider code silently fell back to `HashEmbeddingProvider`.
- Stored rows showed `embedding_profile_id=openai_text_embedding_3_small_1536`
  but `model_provider=hash_mock`.

## Tickets

| Ticket | Status | Specialist | Scope |
| --- | --- | --- | --- |
| W11-001 | Complete | Registry Contract | Make provider selection fail closed; hash mock is returned only for the explicit `hash_mock` provider. |
| W11-002 | Complete | Implementation | Make ingestion, retrieval, and repair reject unknown/misconfigured embedding profiles instead of falling back. |
| W11-003 | Complete | Implementation | Let generated local cell envs import operator-approved secret values from `.env` while printing variable names only. |
| W11-004 | Complete | Test/Proof | Add tests and local proof commands that prevent OpenAI-profile rows from being backed by `hash_mock`. |

## Out Of Scope

- Docker Hub push or VPS deployment.
- Changing tenant isolation, ACL checks, or API-key authorization.
- Replacing the configured OpenAI model.
- Implementing direct Jina/Cohere/Voyage/RunPod model endpoints beyond the
  existing adapters.
- Printing or committing secret values.

## Acceptance Criteria

- [x] `provider_for("openai")` fails when `OPENAI_API_KEY` is missing instead
  of returning `HashEmbeddingProvider`.
- [x] Unknown provider names fail instead of falling back to hash mock.
- [x] `hash_mock` remains available only when selected explicitly.
- [x] Ingestion rejects an unknown embedding profile instead of substituting
  OpenAI or hash mock.
- [x] Ingestion rejects any real embedding profile that returns a `hash_mock`
  provider response.
- [x] Ingestion preview exposes provider configuration state using secret-safe
  env variable names only.
- [x] Local generated cell envs can import configured provider secrets from the
  operator `.env` without printing values.
- [x] Tests prove a local cell with an OpenAI key selects the OpenAI profile and
  a local cell without provider keys selects the explicit `hash_mock_1536`
  fallback.
- [x] Live local-cell proof captures raw command output showing no current
  `openai_text_embedding_3_small_1536|hash_mock` rows remain after the fix.

## Verification

```bash
PYTHONPATH=packages/svs_common:apps/api:apps/worker:apps/model_gateway:apps/instance_agent python -m compileall -f -q packages apps tests scripts
PYTHONPATH=packages/svs_common:apps/api:apps/worker:apps/model_gateway:apps/instance_agent python -m pytest -q -rs tests/test_embedding_providers.py tests/test_vectorization_plan.py tests/test_generate_cell_env.py
python scripts/release/generate-cell-env.py --cell local --registry-prefix localhost:5000/expertaiservices --source-env .env
docker exec exais-vector-store-local-api-1 python -c "<secret-safe env presence proof>"
docker exec exais-vector-store-local-postgres-1 psql -U svs_owner -d svs -c "<embedding provider mismatch audit SQL>"
```

## Proof Notes

- Added provider fail-closed checks before any network call or mock fallback can
  happen for real providers.
- Added router candidate configuration fields with env names only.
- Added generated-cell env import from `.env` for embedding, RunPod, Marker, and
  other provider secret variables. The script output still lists only variable
  names.
- Existing hash-backed ticket-corpus rows were deleted from Postgres/Qdrant by
  removing the contaminated vector store during proof; future reingestion must
  use the rebuilt image.
- `VOYAGE_API_KEY` was later added to the operator `.env`; generated cell env
  import showed the variable name only and did not print the value.
- The old `voyage-context-3` model is not accepted by the Voyage
  `/v1/embeddings` endpoint used by this product path. The PDF Markdown mode now
  uses `voyage_4_docs_1024` (`model=voyage-4`) and sends provider input type
  `document`; retrieval sends input type `query`.
- Mounted-workspace Docker proof now reads the workspace `configs/` directory
  instead of stale `/app/configs` when tests mount the repo into an existing
  image.

## Current Real-Provider Proof

Generated cell env imports provider secret names without printing values:

```text
python scripts/release/generate-cell-env.py --cell local --registry-prefix localhost:5000/expertaiservices --source-env .env
Variable names imported from source env:
- DEFAULT_EMBEDDING_PROVIDER
- MARKER_MODE
- MARKER_RUNPOD_API_KEY
- MARKER_RUNPOD_ENDPOINT_ID
- OPENAI_API_KEY
- OPENAI_EMBEDDING_DIMENSIONS
- OPENAI_EMBEDDING_MODEL
- RUNPOD_API_KEY
- RUNPOD_ENDPOINT_ID
- VOYAGE_API_KEY
No values printed.
```

Focused Docker-mounted tests pass:

```text
docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_embedding_providers.py tests/test_vectorization_plan.py tests/test_generate_cell_env.py tests/test_vector_store_delete.py
..................                                                       [100%]
18 passed in 1.84s
```

The live cell sees provider env names as present and nonempty without printing
values:

```text
OPENAI_API_KEY_present=True nonempty=True
VOYAGE_API_KEY_present=True nonempty=True
DEFAULT_EMBEDDING_PROVIDER_present=True nonempty=True
```

Live PDF Markdown preview chooses the supported Voyage profile:

```text
status=200
mode=pdf_markdown_external_v1
embedding_profile_id=voyage_4_docs_1024
candidate=voyage_4_docs_1024 provider=voyage model=voyage-4 configured=True allowed=True required_env=VOYAGE_API_KEY
warnings=0
```

Live Voyage adapter proof:

```text
provider=voyage
model=voyage-4
dimensions=1024
vectors=1
first_vector_len=1024
usage_keys=total_tokens
```

Raw PDF upload through Marker and real Voyage embeddings now passes:

```text
python scripts/release/pdf-upload-search-proof.py --cell local --require-page-start --timeout-seconds 900
VECTOR_STORE_ID=vs_fa8dbe64b4a344d5b00a44c2
upload_cell_network_status=200
upload_status=completed
document_id=doc_49a803220ca84b87b3dfe61b
vector_store_file_id=vsf_27910fdc44e044dd9e2be5fe
search_results=2
first_chunk_id=chk_356dd2399e5b4ddeaf6e764b
first_page_start=1
first_page_end=1
first_source=hybrid_rrf
```

SQL and Qdrant prove the PDF vector store is Voyage-backed:

```text
embedding_profile_id | model_provider | model_name | dimensions | count
----------------------+----------------+------------+------------+-------
voyage_4_docs_1024   | voyage         | voyage-4   |       1024 |     1

active_real_profile_hash_rows
-------------------------------
                             0

{"result":{"count":1},"status":"ok","time":0.003117624}
```

SQL proof for the active ticket corpus is OpenAI-backed, not hash-backed:

```text
embedding_profile_id                 | model_provider | model_name             | dimensions | count
-------------------------------------+----------------+------------------------+------------+-------
openai_text_embedding_3_small_1536   | openai         | text-embedding-3-small |       1536 |   150

active_real_profile_hash_rows
-------------------------------
                             0
```
