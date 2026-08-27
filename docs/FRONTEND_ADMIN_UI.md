# Frontend / Admin UI Operator Console

The frontend is intentionally not the security authority; it selects modes,
submits work, and decorates requests with the bearer credential that the API
resolves into a principal. The WAVE-110 UI promotes the old scaffold into an
Expert AI Services operator console for one private VPS / Docker Compose cell
per onboarded customer.

## Current capabilities

- Lists vectorization modes from `/api/v1/vectorization/modes`.
- Verifies the admin session through `/api/v1/admin/session`.
- Reviews fleet version evidence through `/api/v1/admin/fleet/versions`.
- Selects a mode such as `markdown_docs_v1`, `pdf_markdown_external_v1`, `code_repo_v1`, or `auto_detect_v1`.
- Creates an OpenAI-compatible vector store through `/v1/vector_stores`.
- Ingests pasted Markdown/text content through `/v1/vector_stores/{id}/files`.
- Uploads OpenAI-compatible files through `/v1/files` and attaches them through
  `/v1/vector_stores/{id}/files`.
- Searches through `/v1/vector_stores/{id}/search` and runs
  `/v1/responses` file-search requests.
- Creates and revokes scoped API keys through `/api/v1/admin/api-keys`.
- Shows backup readiness from current `/metrics` counters when available.
- Sends `Authorization: Bearer <api key>` for protected production requests.

## Private customer cell workflow

The intended commercial deployment is one isolated customer stack:

```text
Customer agent
  -> https://customer-api.expertaiservices.com/v1/responses
  -> ExAIS API container
  -> customer-private Postgres, Qdrant, MinIO/object store, Redis, worker
```

The operator console is used by Expert AI Services during onboarding and
support. The customer agent consumes the API directly. The normal handoff is:

1. Record customer name, slug, API hostname, admin hostname, and deployment
   notes for the private VPS cell.
2. Create or select the customer vector store.
3. Upload or paste source documents and verify attached-file/ingestion status.
4. Create a read-only agent key with retrieval/file-search scopes. The raw key
   appears only on the create response and must be stored in the customer's
   agent secret store.
5. Hand off redacted endpoint examples for:

```http
POST /v1/responses
POST /v1/vector_stores/{vector_store_id}/search
```

The UI surfaces backup counters and release/fleet evidence that already exist.
It does not claim external offsite restore proof unless a backend endpoint or
operator artifact records that proof.

## Production UI contract

The production UI must fail closed without a bearer credential. The admin API key is entered by the operator and stored in browser session storage under `svs_admin_api_key`; requests are centralized through `apps/admin_ui/src/auth.ts`, which adds:

```http
Authorization: Bearer svs_live_...
```

The API resolves that key through `get_request_principal` and `resolve_api_key_principal`, rejects inactive or expired keys, and applies route scopes through `ensure_scope`. Browser-selected tenant, business, user, role, group, or security-level values are not authoritative and are not sent by production UI requests.

Fleet/version requests follow the same production contract. `/api/v1/admin/fleet/versions` requires a resolved principal plus `admin:read` or `fleet:read`, uses `db_for_principal`, and returns only business instances and deployment rows visible under the active tenant/business RLS policies. The UI can select among visible business instances, but the backend remains the authority for tenant scope and deployment-record visibility.

The UI should call the API with workload payloads such as:

```json
{
  "mode": "pdf_markdown_external_v1",
  "vector_store_id": "vs_...",
  "knowledge_base_id": "kb_...",
  "security_level": 2,
  "attributes": {
    "source_pdf_id": "pdf_...",
    "parser": "user_external_pdf_md_pipeline"
  }
}
```

The backend then resolves:

```text
mode -> parser -> chunker -> tokenizer/counter -> embedding profile -> sparse profile -> reranker -> retrieval profile -> security policy
```

## Local dev headers

The backend may still accept `x-svs-*` identity headers only when `SVS_DEV_MODE=true`. The admin UI only emits those headers while Vite is running in dev mode and an explicit flag such as `VITE_SVS_DEV_MODE=true` is set. Production builds without a bearer API key fail before issuing protected requests.

## Production hardening tickets

- Add OIDC/session exchange if a browser login provider is introduced.
- Expand the fleet selector into a full instance/business/user vault switcher if user-vault administration moves into the browser.
- Add upload progress and resumable ingest jobs.
- Add source-system connection screens.
- Add retrieval eval dashboard and golden query set authoring.
- Add live instance-agent polling when operator-approved host credentials and network access exist; the current dashboard shows recorded control-plane deployment evidence and marks missing live/digest evidence as stale or unverifiable.
