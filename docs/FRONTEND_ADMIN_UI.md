# Frontend / Admin UI Scaffold

The frontend is intentionally thin. It is not the security authority; it selects modes, submits work, and decorates requests with the bearer credential that the API resolves into a principal.

## Current capabilities

- Lists vectorization modes from `/api/v1/vectorization/modes`.
- Verifies the admin session through `/api/v1/admin/session`.
- Reviews fleet version evidence through `/api/v1/admin/fleet/versions`.
- Selects a mode such as `markdown_docs_v1`, `pdf_markdown_external_v1`, `code_repo_v1`, or `auto_detect_v1`.
- Creates an OpenAI-compatible vector store through `/v1/vector_stores`.
- Ingests Markdown/text content through `/api/v1/documents/ingest`.
- Searches through `/api/v1/retrieval/search`.
- Sends `Authorization: Bearer <api key>` for protected production requests.

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
