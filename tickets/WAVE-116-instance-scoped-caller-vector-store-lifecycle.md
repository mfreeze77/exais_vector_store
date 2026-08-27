# WAVE-116 Instance-Scoped Caller Vector-Store Lifecycle

## Goal

Make the customer-instance caller lifecycle explicit and repeatable: an
ingestion-capable API key can create vector stores, upload files, attach files
or batches, and then hand narrower search-only keys to agents that search only
the vector-store IDs exposed in their tool configuration.

## Product Decision

Do not add per-api-key vector-store grants in this wave. API keys are scoped to
the customer instance through tenant/business, scopes, max security level, and
document/chunk ACL. Vector-store access inside that instance is controlled by
which `vector_store_id` values the caller is given and by the API scopes on the
key.

This matches the intended customer deployment model: one isolated VPS/Docker
Compose cell per customer, with multiple vector stores inside the cell for
logical separation such as `KS Law`, `Kansas Supreme Court and Appeals`, or
future customer-specific corpora.

## Background

The backend already exposes the required OpenAI-compatible lifecycle routes:

- `POST /v1/vector_stores`
- `GET /v1/vector_stores`
- `POST /v1/files`
- `POST /v1/vector_stores/{vector_store_id}/files`
- `POST /v1/vector_stores/{vector_store_id}/file_batches`
- `POST /v1/vector_stores/{vector_store_id}/search`
- `POST /v1/responses` with `file_search`

The missing piece is not a new permission model. The missing piece is durable
operator/caller proof, bootstrap scripting clarity, and handoff documentation
that shows exactly how a customer instance creates and uses multiple stores.

## Scope

- Preserve the current instance-scoped API-key model; do not add per-store
  grant tables or per-key vector-store allowlists.
- Document that hidden store IDs are a caller/tool-configuration boundary, not
  a hard auth boundary.
- Add a repeatable proof script or runbook section that uses an ingestion key to:
  create two vector stores, upload files, attach or batch those files, search
  each store, and verify citations.
- Add a proof path that uses a narrower search-only key to search the exposed
  store IDs.
- Clarify the first-admin-key bootstrap path for a fresh production VPS cell.
- Confirm OpenAI-compatible `POST /v1/responses` can search multiple store IDs
  in one file-search tool call and returns native citation `vector_store_ids`
  when duplicated evidence appears across stores.
- Keep caller-agent docs aligned with this product boundary.

## Out Of Scope

- Per-api-key vector-store grant tables.
- Shared multi-customer vector-store backends.
- Public graph query APIs.
- Changing retrieval, graph expansion, citation formatting, or chunking
  behavior.
- Exposing hidden vector-store IDs as a security guarantee.

## Acceptance Criteria

- [x] A fresh customer instance has a documented first-admin-key bootstrap step
  that does not store raw secrets in the repo.
- [x] An ingestion-capable key with
  `retrieval:read,vector_stores:read,vector_stores:write,documents:write` can
  create at least two vector stores.
- [x] The same ingestion-capable key can upload at least one file with
  `POST /v1/files`.
- [x] The same ingestion-capable key can attach that file to a vector store with
  `POST /v1/vector_stores/{vector_store_id}/files`.
- [x] The same ingestion-capable key can create a file batch with
  `POST /v1/vector_stores/{vector_store_id}/file_batches`.
- [x] A search-only key with `retrieval:read,vector_stores:read` can search the
  exposed store IDs and receive OpenAI-style plus native citations.
- [x] `POST /v1/responses` with `file_search.vector_store_ids` can search
  multiple stores in the same customer instance.
- [x] Caller-agent docs include the instance-scoped store policy and lifecycle
  examples.

## Verification

Expected local or VPS-cell proof:

```powershell
curl.exe -sS -X POST "$EXAIS_API_BASE/v1/vector_stores" `
  -H "Authorization: Bearer $EXAIS_INGEST_KEY" `
  -H "Content-Type: application/json" `
  -d '{"name":"KS Law","metadata":{"corpus":"ks_law"}}'

curl.exe -sS -X POST "$EXAIS_API_BASE/v1/files" `
  -H "Authorization: Bearer $EXAIS_INGEST_KEY" `
  -F "purpose=assistants" `
  -F "file=@./source.pdf"

curl.exe -sS -X POST "$EXAIS_API_BASE/v1/vector_stores/$VS_ID/files" `
  -H "Authorization: Bearer $EXAIS_INGEST_KEY" `
  -H "Content-Type: application/json" `
  -d '{"file_id":"file-..."}'

curl.exe -sS -X POST "$EXAIS_API_BASE/v1/vector_stores/$VS_ID/search" `
  -H "Authorization: Bearer $EXAIS_SEARCH_KEY" `
  -H "Content-Type: application/json" `
  -d '{"query":"Find cited Kansas school finance authority","max_num_results":8,"rewrite_query":true}'
```

Expected focused tests if code changes are needed:

```powershell
python -m pytest -q -rs tests/test_openai_files.py tests/test_openai_compat_search.py tests/test_openai_responses_routes.py tests/test_auth_scopes.py
```

## Notes

If a future customer requires hidden vector stores to be a hard authorization
boundary, add a new ticket for per-key vector-store grants. That is intentionally
not part of this wave.

## Implementation Proof

Completed on 2026-08-27.

Changed source:

- `scripts/release/bootstrap-instance-admin-key.py`
- `scripts/release/instance-caller-lifecycle-proof.py`
- `tests/test_instance_caller_lifecycle_scripts.py`
- `docs/CALLER_AGENT_INTEGRATION.md`
- `runbooks/ks-state-civics-hetzner-vps-launch.md`
- `docs/TICKET_TRAIL.md`

Verification:

- `python scripts\release\bootstrap-instance-admin-key.py --help` passed on
  host Python.
- `python scripts\release\instance-caller-lifecycle-proof.py --help` passed on
  host Python.
- `python -m py_compile scripts\release\bootstrap-instance-admin-key.py scripts\release\instance-caller-lifecycle-proof.py`
  passed on host Python.
- Docker API-image focused script tests passed:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_instance_caller_lifecycle_scripts.py`
  -> `3 passed`.
- Docker API-image OpenAI-compatible regression set passed:
  `docker run --rm -v "${PWD}:/work" -w /work -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate python -m pytest -q -rs tests/test_instance_caller_lifecycle_scripts.py tests/test_openai_files.py tests/test_openai_compat_search.py tests/test_openai_responses_routes.py tests/test_auth_scopes.py`
  -> `201 passed`.
- `git diff --check` passed.

Runtime live-cell proof is implemented by
`scripts/release/instance-caller-lifecycle-proof.py` but was not executed against
a live VPS/API endpoint in this implementation turn because no production
endpoint and bearer credentials were supplied.
