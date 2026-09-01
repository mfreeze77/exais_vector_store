# API Surface

The API has two layers:

1. **Native SVS API** for ingestion, mode routing, retrieval, admin, model registry, and instance operations.
2. **OpenAI-compatible vector-store API** for clients that expect `/v1/vector_stores`-style behavior.

Generated `/openapi.json` currently contains 64 paths, 82 operations, and 157
schema components. All documented native and OpenAI-compatible operations have
named 2xx response components, and every JSON request body resolves directly to
a named component. Native responses are runtime-bound through FastAPI response
models. Named nullable request wrappers preserve explicit JSON `null` behavior
for vector-store create/update. Multipart document and OpenAI file uploads
retain named `multipart/form-data` components. Metrics and extracted OpenAI file
content use HTTP-proven `text/plain` responses with named string schemas.

`tests/test_openapi_contract.py` freezes all valid OpenAPI HTTP methods across
the exact 82-operation inventory, verifies
that every request and successful response body is a direct component reference,
and validates representative runtime payloads against the promoted contracts.
This is contract closure, not new OpenAI parity behavior.

The generated `/openapi.json` includes named OpenAI-compatible request and
response components for vector-store search and Responses
create/retrieve/cancel/delete/input-token/compact/input-items routes. The
Responses request components expose OpenAI field names such as `model`, `input`,
`tools`, `tool_choice`, `include`, `previous_response_id`, `conversation`,
`instructions`, `store`, `stream`, `stream_options`, and `background`; the
Responses and direct vector-store search response components expose the
`OpenAIFileCitationAnnotation` contract under their text annotations while
runtime compatibility validation remains in the route helpers. New
OpenAI-compatible `/v1/files` uploads emit public file IDs with OpenAI's current
`file-...` prefix; legacy stored `file_...` IDs remain resolvable for existing
local data.
The Responses `file_search.max_num_results` request component advertises the
same 20 default and 1..50 bounds enforced by runtime validation.

## Local auth

Local dev mode accepts headers:

```http
x-svs-tenant-id: ten_dev
x-svs-business-instance-id: biz_dev
x-svs-user-id: usr_dev
x-svs-groups: grp_admin,grp_eng
x-svs-roles: owner,admin
x-svs-max-security-level: 5
```

Production mode accepts `Authorization: Bearer svs_live_...` API keys stored as
salted/peppered hashes in the `api_keys` table. Key lookup fails closed unless
the key is `active` and unexpired, then resolves tenant, business instance,
user, groups, scopes, and max security level for RLS and endpoint scope checks.

API-key lifecycle routes:

```http
POST   /api/v1/admin/api-keys
GET    /api/v1/admin/api-keys
DELETE /api/v1/admin/api-keys/{api_key_id}
GET    /v1/organization/projects/{project_id}/api_keys
GET    /v1/organization/projects/{project_id}/api_keys/{api_key_id}
DELETE /v1/organization/projects/{project_id}/api_keys/{api_key_id}
```

Create returns the raw `api_key` exactly once. List and revoke responses return
metadata only: id, label, scopes, max security level, status, and timestamps.
They never return raw keys or key hashes.
`GET /api/v1/admin/api-keys` follows OpenAI project API-key list controls with
`limit` (1-100, default 20) and `after`; cursors use both `created_at` and key
ID, so pages remain stable when keys share the same creation timestamp.
The OpenAI-compatible project API-key aliases require `project_id` to match the
current ExAIS business instance ID, list/retrieve only active keys, return
OpenAI-shaped `organization.project.api_key` objects with `redacted_value`,
`name`, timestamps, id, and owner id, and delete returns
`organization.project.api_key.deleted` without native metadata.
Generated `/openapi.json` exposes these aliases through named
`OpenAIProjectApiKey`, `OpenAIProjectApiKeyListResponse`, and
`OpenAIProjectApiKeyDeletedResponse` components.
OpenAI-compatible organization admin API-key aliases are also exposed for the
OpenAI-compatible lifecycle:

```text
POST   /v1/organization/admin_api_keys
GET    /v1/organization/admin_api_keys
GET    /v1/organization/admin_api_keys/{key_id}
DELETE /v1/organization/admin_api_keys/{key_id}
```

These routes reuse the same tenant/business-scoped ExAIS API-key store and
`api_keys:*` scopes, list/retrieve only active keys, and return OpenAI-shaped
`organization.admin_api_key` objects with `id`, `name`, `redacted_value`,
timestamps, and owner metadata. `POST /v1/organization/admin_api_keys` accepts
OpenAI's `name` and optional `expires_in_seconds` fields and returns the raw
`value` exactly once. To avoid privilege escalation, this alias does not accept
scope or security-level fields; the created key inherits the caller's current
ExAIS scopes and max security level. `GET /v1/organization/admin_api_keys`
supports OpenAI's `limit`, `after`, and `order=asc|desc` controls. Delete
revokes the underlying ExAIS key and returns only
`organization.admin_api_key.deleted`. Raw key values are included only on the
create response; key hashes, scopes, and native security levels are never
included in OpenAI-shaped admin API-key responses.
Native `POST /api/v1/admin/api-keys` also accepts an optional future Unix
`expires_at` timestamp. Accepted values are stored in `api_keys.expires_at`,
returned in the one-time create response, and then enforced by bearer
resolution; past or current timestamps are rejected before insert.

Authenticated API-key/admin and OpenAI-compatible `/v1` routes consume the
existing per-principal Postgres rate-limit buckets before route work executes.
Default buckets use `SVS_DEFAULT_RATE_LIMIT_PER_MINUTE`; buckets whose name
starts with `admin` use `SVS_ADMIN_RATE_LIMIT_PER_MINUTE`. A rejected request
returns `429` before retrieval, ingestion, mutation, or stored-response lookup.
OpenAI-compatible file-addition routes also consume a shared per-vector-store
budget: `POST /v1/vector_stores/{id}/files` and
`POST /v1/vector_stores/{id}/file_batches` share
`SVS_VECTOR_STORE_FILE_ADD_RATE_LIMIT_PER_MINUTE`, defaulting to the OpenAI
documented 300 requests/minute per vector store ID.

## Discovery

```http
GET /healthz
GET /api/v1/vectorization/modes
GET /api/v1/models/registry
GET /api/v1/retrieval/profiles
GET /v1/experts
GET /v1/experts/{expert_id}
```

Expert discovery requires bearer authentication and `retrieval:read`. The list
returns only profiles whose complete vector-store binding is active and within
the request principal's tenant and business instance. Detail lookup returns
`404` for unknown, inactive, expired, or cross-scope bindings before retrieval
or model execution. Each profile carries its server-owned prompt, model policy,
tool limits, citation and caveat policies, authorized vector stores, and graph
lens capabilities composed from the existing search-lens registry. Profile
metadata contains no provider credentials or backend service URLs.

Each profile also declares routing metadata (WAVE-125): `jurisdiction_key`, a
caller-defined key such as `ks:city:topeka`, and `corpus`, one of `statutes`,
`court_decisions`, `municipal_code`, `administrative_regulations`,
`legislative_materials`, `meeting_records`, or `other`. Both are nullable for
experts that have not declared them. `GET /v1/experts` accepts
`?jurisdiction_key=...` and `?corpus=...` filters; an unknown `corpus` value is
`422`. Filters are applied only after the tenant, instance, principal, and
binding checks, so they narrow the visible set and never widen it. The registry
populates these fields from the expert definition (compiled WAVE-124 packages
supply them from `package.yaml`; hand-registered experts set them in
`expert_profiles.py`).

### Expert messages, sessions, feedback, and governed memory

```http
POST /v1/experts/{expert_id}/messages
POST /v1/experts/{expert_id}/sessions/{session_id}/fork
POST /v1/experts/{expert_id}/feedback
GET /v1/experts/{expert_id}/sessions/{session_id}/memory
POST /v1/experts/{expert_id}/sessions/{session_id}/memory/{memory_event_id}/promote
DELETE /v1/experts/{expert_id}/sessions/{session_id}/memory/{memory_event_id}
```

These routes require production bearer authentication and `retrieval:read`, use
the standard ExAIS request rate limit, and accept `Idempotency-Key`. A message
request supplies `message` plus optional `session_id`, `external_user_id`,
`conversation_id`, and `session_label`. When resuming by `session_id`, the
external-user and conversation values must exactly match the stored session;
omitting a stored value also fails closed. The path `expert_id` is authoritative.

Sessions, messages, tool calls, retrieval runs, feedback, and memory rows are
scoped by the principal's `api_key_id` and `user_id` in addition to the
caller-side `external_user_id` and `conversation_id`. A key bound to one user
(see [Admin](#admin)) therefore cannot list, fork, or read memory for a session
created under another user. When the bound user has an `external_id` and the
request carries `external_user_id`, the two must agree or the request is `403
external_user_id_mismatch`; cell keys without a bound external id keep
`external_user_id` as a free-form correlation id. Every completed message also
writes one `expert.message` usage event (token quantity, provider, model) and
one `expert`/`message` audit event carrying the principal's `user_id` and
`api_key_id`.

The typed message response contains `expert_id`, `session_id`, optional
`parent_session_id`, `answer`, `citations`, `retrieval_trace`,
`model_metadata`, `caveats`, and `follow_up_suggestions`. Model metadata includes
the policy/profile, provider, served model, latency, normalized usage, finish
reason, and truthful fallback record, but never provider credentials or model-
gateway URLs. Fork requests repeat the parent session's external-user and
conversation scope and return the child session ID, parent ID, and new caller
conversation ID.

Expert messages execute bounded profile-authorized retrieval before synthesis.
Only retrieved corpus/source-package results are citation authority; retrieval
runs persist the attempted lens, truthful graph status, result IDs, selected
context IDs, source URLs, graph metadata, and citations.

Feedback accepts a scoped `session_id`, optional in-session `message_id`, exact
`external_user_id` and `conversation_id`, a typed feedback category, optional
rating/comment, and up to three typed memory candidates. Candidate memory types
are `retrieval_strategy`, `answer_style`, and `preference`. Candidates are inert
until the separate promotion route receives `{"confirm": true}` and the stored
confidence satisfies policy. Listing and deletion require the same caller
scope. Deletion is a soft-delete audit tombstone that scrubs the stored
instruction. Feedback and memory text pass the existing PII/secret guard;
secret-bearing structured fields and citation markers in memory are rejected.

Promoted answer-style and preference memory may shape response presentation,
but it is sent as explicitly non-authoritative guidance, never added to
retrieved context, and never exposed as a citation source. Every feedback,
candidate, promotion, and deletion mutation emits an `expert_governance` audit
event containing scope and lifecycle metadata, not the feedback or memory text.

Caller frameworks should expose this surface through the thin MCP tool names
`list_exais_experts`, `ask_exais_expert`, and `submit_expert_feedback` documented
in [Caller Agent Integration](CALLER_AGENT_INTEGRATION.md). Those adapters map
typed inputs to the routes above and return typed bodies; they do not own
retrieval, graph, ACL, citation, provider, feedback, or memory behavior.

The repository-backed raw-search versus expert-session comparison is:

```powershell
python evals/expert-sessions/run_eval.py
```

That command is deterministic fixture proof only. Its result deliberately says
that neither the current live corpus nor an external provider was verified.

## Model gateway

Expert reasoning uses one internal, provider-neutral route:

```http
POST /internal/models/expert-chat
```

The request carries typed `system`, `user`, and `assistant` messages plus the
server-resolved `ExpertModelPolicy`; callers do not select a vendor directly.
The gateway resolves dedicated `chat_policies` and `chat_models`, applies the
request security level, and returns the selected model profile, provider,
served model, latency, normalized input/output/total token usage, finish reason,
and per-attempt fallback evidence. `fallback.occurred` is true only when a
later declared candidate actually succeeds. The deterministic fixture chat
profile is restricted to local/dev/test/CI and is never a production fallback.

The API service calls this route through
`svs_common.expert_llm.complete_expert_chat`; customer-facing handlers do not
call vendor SDKs or depend on personal Codex, Claude Code, OpenCode, browser,
desktop, or subscription sessions.

Internal model-gateway routes also include deterministic embedding cost estimates:

```http
POST /internal/models/estimate-cost
```

The request uses the embedding request shape (`input`, optional
`model_profile_id`, `provider`, `model`, and `dimensions`). The response
returns `estimated_tokens`, resolved `model_profile_id`, `provider`, `model`,
`dimensions`, `estimated_cost_usd`, `currency`, `unit`,
`input_per_1m_tokens_usd`, `cost_source`, and `reason`. Priced profiles return
a numeric estimate. Unknown or unpriced profiles return
`estimated_cost_usd: null` with a reason such as `unknown_model_profile` or
`cost_unavailable`; the route does not guess missing provider pricing.

## Evals

```http
POST /api/v1/bakeoffs
GET  /api/v1/bakeoffs
GET  /api/v1/bakeoffs/{run_id}
```

Bakeoff runs compare configured model profile candidates against golden query
fixtures. When a query includes `results_by_model_profile_id` or
`result_ids_by_model_profile_id`, ExAIS computes real golden metrics per
candidate: `recall_at_k`, `precision_at_k`, `mrr`, `ndcg_at_k`, leakage counts,
and per-query metric detail. Result rows may be strings or objects carrying
`id`, `chunk_id`, and/or `document_id`; expected and forbidden chunk/document
IDs are both honored. If no judged candidate results are supplied, the runner
keeps the existing deterministic proxy score so the API remains usable without
fixture or provider result rows.

Set `execution_mode` to `live` to fan the same query set through the internal
bakeoff retrieval runner for each candidate profile. Live runs capture per-query
result IDs, result counts, latency, error status, registry-derived cost metadata,
golden retrieval metrics, and selection/rejection policy output. The default
runner is deterministic fixture-backed for credential-free proof; real provider
proof still requires operator API credentials and an approved live command.

## Ingestion

```http
POST /api/v1/documents/ingest
POST /api/v1/documents/upload
```

Core body:

```json
{
  "vector_store_id": "vs_...",
  "knowledge_base_id": "kb_...",
  "title": "Document title",
  "filename": "converted.md",
  "mime_type": "text/markdown",
  "mode": "pdf_markdown_external_v1",
  "content": "# Markdown generated by your existing PDF process",
  "security_level": 1,
  "allowed_groups": ["finance"],
  "allowed_roles": ["admin"],
  "attributes": {
    "source_pdf_id": "pdf_..."
  }
}
```

`POST /api/v1/documents/upload` accepts raw PDFs only when the external RunPod
Marker parser is configured. PDF uploads with `mode=auto_detect_v1`,
`mode=raw_pdf_research_v1`, or `mode=pdf_markdown_external_v1` are submitted to
RunPod Marker and converted to a `pdf_markdown_external_v1` document before
chunking/indexing. ExAIS stores the original PDF as a source artifact and stores
only secret-safe parser metadata in document attributes.

## Retrieval

```http
POST /api/v1/retrieval/search
POST /api/v1/retrieval/context-pack
POST /api/v1/retrieval/answer
```

Core body:

```json
{
  "query": "What are the payment terms?",
  "vector_store_id": "vs_...",
  "mode": "pdf_markdown_external_v1",
  "retrieval_profile_id": "hybrid_rrf_secure_v2",
  "top_k": 10
}
```

The retrieval service performs dense search, sparse search, RRF fusion, Postgres
hydration, and post-retrieval ACL verification before returning results.
Native `/api/v1/retrieval/context-pack` also applies profile-driven context
expansion when the effective retrieval profile enables same-document neighbors
or parent heading sections. Expanded context preserves the same
tenant/business/security, vector-store or knowledge-base, safe file-attribute,
and post-ACL checks as direct search hits. Context-pack citations include the
OpenAI-core annotation object plus visible `【n†source】` markers in the
returned context string. Each annotation `index` points to the marker offset in
`context`, and native relation metadata such as `context_relation`,
`source_chunk_id`, `neighbor_offset`, and `parent_heading_path` remains outside
the strict OpenAI annotation object. Native context citations also carry
`message_annotation` with the same marker replacement span in OpenAI's message
annotation shape. Each context source also includes an
OpenAI-recommended `Citation Marker: \ue200cite\ue202turn0file0\ue201` line and
returns matching `model_source_id`/`model_marker` citation fields; when chunk
metadata contains line bounds, the marker carries a line locator such as
`\ue200cite\ue202turn0file0\ue202L8-L13\ue201`.

Native `/api/v1/retrieval/answer` uses the context-pack result as its citation
authority and returns an extractive cited answer. Answer text includes visible
`【n†source】` markers, and each citation annotation `index` points to the marker
offset in `answer`. The route applies the existing sensitive-output guard before
marker insertion, preserves the context-pack `model_source_id`/`model_marker`
and `message_annotation` fields for prompt/rendering pipelines, and rejects
malformed answer citation payloads before return.

## Admin

```http
GET  /api/v1/admin/session
GET  /api/v1/admin/fleet/versions
GET  /api/v1/admin/usage?limit=&user_id=&api_key_id=
GET  /api/v1/admin/usage/summary?group_by=user|api_key&from=&to=&limit=
GET  /api/v1/admin/audit-events
POST /api/v1/admin/tenants
POST /api/v1/admin/users
GET  /api/v1/admin/users?external_id=&status=&limit=&after=
POST /api/v1/admin/users/{user_id}/deactivate
POST /api/v1/admin/api-keys?label=&scopes=&max_security_level=&expires_at=&user_id=
GET  /api/v1/admin/api-keys?limit=&after=&user_id=
DELETE /api/v1/admin/api-keys/{api_key_id}
```

API key creation returns plaintext only once. Store it immediately.

### Caller-provisioned users (WAVE-125)

`POST /api/v1/admin/users` takes a JSON body `{"external_id": "...",
"email": null, "display_name": null}` and returns the ExAIS `user`
(`id`, `external_id`, `email`, `display_name`, `status`,
`business_instance_id`, `created_at`, `deactivated_at`). It is idempotent on
`(tenant_id, external_id)`: repeating the call returns the existing user. An
`external_id` already provisioned in another business instance, or an `email`
owned by another user, is `409`. `GET /api/v1/admin/users` lists users of the
principal's business instance newest-first with `after` cursor paging and
optional `external_id` / `status` (`active`|`deactivated`) filters.
`POST /api/v1/admin/users/{user_id}/deactivate` marks the user deactivated,
revokes every active key bound to it (returned as `revoked_api_key_ids`), emits
an `admin`/`user.deactivate` audit event, and preserves session, usage, and
audit history. Every user created through this route is instance-scoped and
carries an `external_id`; the schema enforces `CHECK (business_instance_id IS
NULL OR external_id IS NOT NULL)`, so a user-bound key is structurally one
whose user has an `external_id`. Subsequent calls with a revoked key are `401`; a key that
somehow remains active for a deactivated user also fails `401` at principal
resolution. These routes require `users:write` or `api_keys:write` (listing
also accepts `users:read` / `api_keys:read`) and use the admin rate limit.

### User-bound API keys (WAVE-125)

`POST /api/v1/admin/api-keys` accepts an optional `user_id`. When present:

- the user must exist in the principal's tenant and business instance and be
  `active` (`404` / `409` otherwise);
- `scopes` defaults to `retrieval:read`; every requested scope must be on the
  user-bound allow-list (`403 scope_not_delegable_to_user_bound_key`) and
  already held by the creating principal (`403 insufficient_scope` lists the
  denied scopes);
- `max_security_level` defaults to the creator's level and may not exceed it
  (`422`);
- the response includes `user_id` and, exactly once, the raw `api_key`.

Without `user_id` the route behaves as before (creator-inherited user, default
`retrieval:read,documents:write,vector_stores:write,vector_stores:read`).
`GET /api/v1/admin/api-keys?user_id=...` filters by bound user and every key
row now reports `user_id`. `DELETE /api/v1/admin/api-keys/{id}` revokes. A
user-bound key holding only `retrieval:read` receives `403` on every admin and
organization route except `GET /api/v1/admin/session`, the admin-UI identity
echo that answers any `ADMIN_UI_SESSION_SCOPES` holder with the caller's own
principal and nothing else; it cannot widen its own scopes and cannot see
expert sessions or memory created under a different user.

Delegation rules apply to **every** key creation, with or without `user_id`:
requested scopes must already be held by the creating principal (`*` and
`system` can only be minted by a principal that holds them) and
`max_security_level` defaults to and may not exceed the creator's. A key bound
to a user may additionally carry only exact scopes from the allow-list
`retrieval:read`, `documents:read`, `documents:write`, `vector_stores:read`,
`vector_stores:write`, regardless of what the creator holds; anything else
(`api_keys:*`, `users:*`, `admin:*`, `usage:*`, `audit:*`, `fleet:*`, `role:*`,
namespace wildcards, `*`, `system`, and any future namespace) is
`403 scope_not_delegable_to_user_bound_key` by construction. Principal resolution
fails `401` when a key's bound user cannot be found in the key's tenant or is
not `active`; a bound key never degrades into an unbound cell key.

### Usage attribution (WAVE-125)

Usage events carry `user_id` and `api_key_id` from the request principal (as
audit events already did); rate-limit buckets record them as well.
`GET /api/v1/admin/usage` returns `id`, `user_id`, and `api_key_id` per row and
accepts `user_id` / `api_key_id` filters. When the caller is a user-bound key
(bound to a caller-provisioned user with an `external_id`) that somehow holds
`usage:read` or `admin:read`, both usage routes are forced to that user's own
`user_id`: the filter is applied server-side, the summary is restricted to the
caller's rows, and an explicit different `user_id` is `403
user_bound_usage_scope`. `GET /api/v1/admin/usage/summary`
groups by `user` (default) or `api_key` over an optional `[from, to)` Unix-
timestamp window and returns `{"object": "usage.summary", "group_by", "from",
"to", "data": [{"group_id", "external_id", "event_count", "quantity",
"cost_estimate_usd"}]}`; `external_id` is populated for `group_by=user`.
Both require `admin:read` or `usage:read`.

## OpenAI-compatible vector store routes

```http
POST   /v1/vector_stores
GET    /v1/vector_stores
GET    /v1/vector_stores/{vector_store_id}
POST   /v1/vector_stores/{vector_store_id}
PATCH  /v1/vector_stores/{vector_store_id}
DELETE /v1/vector_stores/{vector_store_id}
POST   /v1/files
GET    /v1/files
GET    /v1/files/{file_id}
GET    /v1/files/{file_id}/content
DELETE /v1/files/{file_id}
POST   /v1/vector_stores/{vector_store_id}/files
GET    /v1/vector_stores/{vector_store_id}/files
GET    /v1/vector_stores/{vector_store_id}/files/{file_id}
POST   /v1/vector_stores/{vector_store_id}/files/{file_id}
PATCH  /v1/vector_stores/{vector_store_id}/files/{file_id}
DELETE /v1/vector_stores/{vector_store_id}/files/{file_id}
GET    /v1/vector_stores/{vector_store_id}/files/{file_id}/content
POST   /v1/vector_stores/{vector_store_id}/file_batches
GET    /v1/vector_stores/{vector_store_id}/file_batches/{batch_id}
POST   /v1/vector_stores/{vector_store_id}/file_batches/{batch_id}/cancel
GET    /v1/vector_stores/{vector_store_id}/file_batches/{batch_id}/files
GET    /v1/vector_stores/{vector_store_id}/search_lenses
POST   /v1/vector_stores/{vector_store_id}/graph
POST   /v1/vector_stores/{vector_store_id}/search
POST   /v1/responses
POST   /v1/responses/compact
POST   /v1/responses/input_tokens
GET    /v1/responses/{response_id}
POST   /v1/responses/{response_id}/cancel
DELETE /v1/responses/{response_id}
GET    /v1/responses/{response_id}/input_items
```

The API contract intentionally mimics OpenAI vector-store behavior where useful,
but the source of truth remains SVS Postgres + Qdrant + OpenSearch + object
storage.

OpenAI-compatible retry-sensitive mutating routes accept `Idempotency-Key`.
This covers vector-store/file/Responses create, update, delete, response-cancel,
and file-batch cancel operations under `/v1`. Matching retries return the cached
response.
Reusing the same key with a different body, path, or upload content returns
`409`.

OpenAI-compatible vector-store create/update:

```json
{
  "name": "Support FAQ",
  "description": "Customer support corpus",
  "metadata": {"region": "us"},
  "expires_after": {"anchor": "last_active_at", "days": 7},
  "chunking_strategy": {"type": "auto"}
}
```

Create also accepts an empty body and `file_ids` for attaching existing ExAIS
document IDs. When `file_ids` and `chunking_strategy` are supplied together,
the request-level chunking strategy is stored on each created vector-store file
attachment; vector-store `metadata` remains store-level metadata and is not
copied into file attributes. Responses include OpenAI fields such as `bytes`,
`file_counts`, `metadata`, and `description`; `usage_bytes` and `attributes`
remain for native ExAIS clients.
Generated `/openapi.json` exposes vector-store CRUD routes through
`VectorStoreResponse`, `VectorStoreListResponse`, and
`VectorStoreDeletedResponse` components.

OpenAI-compatible vector-store search accepts either a single `query` string or
OpenAI's multi-query array form:

```json
{
  "query": ["RunPod Marker warmup", "Voyage embeddings"],
  "max_num_results": 10,
  "rewrite_query": true
}
```

String requests preserve the existing `search_query` string response. Array
requests execute each normalized query through the same retrieval/planning path
and return the effective query list in `search_query`; results still use the
same OpenAI-style citation annotations and visible `【n†source】` markers.
Search filters support safe file-attribute `eq`, `ne`, `in`, `nin`, `gt`,
`gte`, `lt`, and `lte` comparisons. Negation filters require the attribute key
to exist, then exclude matching values during authoritative Postgres hydration.

`expires_after` accepts the OpenAI expiration-policy shape
`{"anchor": "last_active_at", "days": N}` and requires positive integer `days`.
Malformed or inert policies fail request validation instead of being stored
silently.
When `expires_after.anchor` is `last_active_at`, vector-store attach, ingestion,
search, context-pack, and Responses file-search refresh `last_active_at` and
slide `expires_at`. Expired vector stores fail with `404` before retrieval can
return stale cited content. The maintenance sweeper marks expired rows, queues
stale-vector cleanup, and records an audit event.

OpenAI-compatible file upload:

```bash
curl http://localhost:8080/v1/files \
  -H "Authorization: Bearer svs_live_..." \
  -F purpose="assistants" \
  -F file="@policy.md"
```

The returned OpenAI-style `file-...` ID can be attached directly. Existing
stored `file_...` IDs remain accepted for legacy local data:

```json
{"file_id": "file-..."}
```

OpenAI-compatible text uploads accept UTF-8, UTF-16, and ASCII encodings. PDF
uploads route through the configured Marker conversion path when available;
other binary uploads fail with `415`. Uploads also accept OpenAI's multipart
expiration fields `expires_after[anchor]=created_at` and
`expires_after[seconds]=...`; when supplied, the returned file object includes
`expires_at`.

`GET /v1/files` supports OpenAI file-list controls: `purpose`, `limit`,
`order`, and `after`. Its `after` cursor uses both `created_at` and the public
file ID, so pages remain stable when multiple files share the same creation
timestamp.
Generated `/openapi.json` exposes `/v1/files` upload, list, retrieve, and delete
JSON responses through `OpenAIFile`, `OpenAIFileListResponse`, and
`OpenAIFileDeletedResponse` components. `GET /v1/files/{file_id}/content`
advertises `text/plain` because the route returns decoded or extracted text,
even when the stored source MIME is non-text.

Vector-store, vector-store file, and file-batch file lists support OpenAI
pagination controls: `limit`, `order`, `after`, and `before`; vector-store file
lists also support the status `filter`. Cursors can use the public IDs returned
by ExAIS. List pagination is stable across rows that share the same creation
timestamp by using both `created_at` and public ID as the cursor ordering key.
Generated `/openapi.json` exposes standalone vector-store file routes through
`OpenAIVectorStoreFile`, `OpenAIVectorStoreFileListResponse`,
`OpenAIVectorStoreFileDeletedResponse`, and
`OpenAIVectorStoreFileContentResponse` components.

Vector-store file attributes can be updated with the OpenAI-compatible `POST`
method:

```json
{"attributes": {"region": "us"}}
```

OpenAI-compatible vector-store `metadata` and vector-store-file `attributes`
are validated before storage. Public metadata/attribute maps are capped at 16
entries with non-empty keys up to 64 characters and string values up to 512
characters. Vector-store metadata values are strings. Vector-store-file
attributes accept string, finite number, and boolean values, reject nested
values, sensitive searchable keys, and ExAIS reserved internal attribute names.

File batches accept either `file_ids` or OpenAI-shaped file references in
`files`; the two fields are mutually exclusive and the request is capped at the
current OpenAI reference limit of 2000 files. Request-level
`attributes`/`metadata` and `chunking_strategy` apply to every item when
`file_ids` is used. Per-file `files` entries can carry their own attributes and
chunking strategy:

```json
{
  "files": [
    {
      "file_id": "file-...",
      "attributes": {"region": "us"},
      "chunking_strategy": {
        "type": "static",
        "max_chunk_size_tokens": 1200,
        "chunk_overlap_tokens": 200
      }
    }
  ]
}
```

OpenAI-compatible file attach and file-batch routes validate
`chunking_strategy` before storage. `auto` accepts only `{ "type": "auto" }`.
`static` accepts `max_chunk_size_tokens` from 100 through 4096 and a
non-negative `chunk_overlap_tokens` value that does not exceed half the max
chunk size. When either static field is omitted, ExAIS preserves the submitted
shape while using OpenAI's documented 800/400 defaults as the validation
baseline.

Batch create, retrieve, and cancel return `vector_store.file_batch` objects with
`created_at`, `status`, and complete `file_counts`. Cancelled batches move any
remaining `in_progress` files into `cancelled`.
Generated `/openapi.json` exposes these file-batch responses through
`OpenAIVectorStoreFileBatch`; batch file-list responses use
`OpenAIVectorStoreFileBatchFilesPage` with nested `OpenAIVectorStoreFile`
objects.
File attach and file-batch create share the per-vector-store add-file request
budget configured by `SVS_VECTOR_STORE_FILE_ADD_RATE_LIMIT_PER_MINUTE`.

`DELETE /v1/files/{file_id}` removes the uploaded file from associated vector
stores by cancelling file rows, deactivating chunks, and queueing stale-vector
cleanup.

OpenAI-compatible Responses file-search request:

```json
{
  "model": "gpt-5.4-mini",
  "input": [
    {
      "role": "user",
      "content": [
        {"type": "input_text", "text": "What does the source say?"}
      ]
    }
  ],
  "tools": [
    {
      "type": "file_search",
      "vector_store_ids": ["vs_..."]
    }
  ]
}
```

The response is an OpenAI-shaped completed `response` object with citation
annotations on the assistant `output_text` content:

```json
{
  "type": "output_text",
  "text": "Relevant vector store content:\n\nSource excerpt... 【1†source】",
  "annotations": [
    {
      "type": "file_citation",
      "index": 50,
      "file_id": "file-...",
      "filename": "source.md"
    }
  ]
}
```

The annotation `index` is the character offset of the visible citation marker
in the returned text, matching the OpenAI pattern clients use to replace or
render inline source markers.
The shared `openai_response_citation_references` helper exposes the same
client-renderable mapping internally: output/content/annotation indexes,
exact `start_index`/`end_index` replacement spans, the visible marker text, and
the strict OpenAI `file_citation` object. Native `citations[]` entries also
expose an Assistants-style `message_annotation` object with `start_index`,
`end_index`, `text`, and nested `file_citation.file_id`, so renderer clients can
use the older OpenAI message-annotation replacement shape without adding extra
fields to `output_text.annotations`. Native citations also expose the same spans
plus `model_source_id` and `model_marker` in OpenAI's recommended model-facing
citation syntax, for example
`\ue200cite\ue202turn0file0\ue201`. Use these native fields when building
grounded prompts or custom renderers; the OpenAI-facing annotation object stays
limited to `type`, `index`, `file_id`, and `filename`.
Multiple OpenAI-facing `file_citation` annotations may point at the same marker
offset when several retrieved sources support one visible answer location;
streaming preserves one annotation-added event per annotation in order.
The generated OpenAPI contract exposes this same citation object as
`OpenAIFileCitationAnnotation` under `OpenAIResponseOutputTextContent`, with
required `type`, `index`, `file_id`, and `filename` fields and no extra
OpenAI-facing annotation properties. The native replacement-span object is
advertised separately as `OpenAIMessageFileCitationAnnotation`. The shared
contract rejects negative annotation indexes and blank `file_id`/`filename`
values before a citation can be stored, returned, streamed, or advertised in
`/openapi.json`.
The `text/event-stream` contract for `POST /v1/responses` and
`GET /v1/responses/{response_id}?stream=true` is also typed in `/openapi.json`
as `OpenAIResponseStreamEvent`; its
`OpenAIResponseOutputTextAnnotationAddedEvent.annotation` field references the
same strict `OpenAIFileCitationAnnotation` component used by completed
Responses JSON.
Before deterministic Responses text is returned, ExAIS applies
`pii_secret_citation_guard_v1` to redact obvious PII and secret patterns from
retrieved snippets. The guard runs before citation marker insertion, so
annotation indexes continue to point at the visible `【n†source】` marker.
Newly created Responses payloads pass a citation-integrity guard before storage,
return, or streaming. The guard verifies strict OpenAI `file_citation` fields,
confirms annotation indexes point at visible `【n†source】` markers, rejects
orphan visible markers without matching OpenAI annotations, and checks that
native `citations[].annotation` mirrors the OpenAI-facing annotations.
Stored Responses payloads run the same guard before `GET /v1/responses/{id}`
returns or streams a replay, so persisted JSON cannot emit stale or malformed
OpenAI citation annotations.
The strict annotation and marker-span checks are shared with native retrieval
answer citation integrity, keeping OpenAI-facing citation behavior consistent
across the Responses and native answer surfaces.
`previous_response_id` is supported for stored Responses file-search chains.
The previous response is resolved under the same tenant/business scope as
retrieve/delete. ExAIS uses bounded previous input and assistant output text as
context for the next retrieval query, strips old visible citation markers and
OpenAI recommended `\ue200cite...\ue201` model citation markers before search,
and returns the requested `previous_response_id` on the new response. Missing,
deleted, or cross-scope previous responses fail with `404` before retrieval
runs. Prior top-level `instructions` are not carried over automatically; send
stable instructions on each new request. Supplying both `previous_response_id`
and `conversation` returns `422`.

The route uses deterministic query planning plus the existing retrieval stack
under `retrieval:read` scope. It removes simple request filler and splits
compound questions into bounded subqueries before executing vector-store
searches. When a `file_search` tool omits `max_num_results`, ExAIS uses
OpenAI's default of 20. It does not generate model prose; it returns a
deterministic retrieval summary with OpenAI-style citations. `stream=true`
returns OpenAI-style typed
SSE events such as `response.created`, `response.file_search_call.searching`,
`response.output_text.delta`, `response.output_text.annotation.added`,
`response.output_text.done`, `response.content_part.done`, and
`response.completed`; citation annotations are emitted before output-text done,
then preserved on content-part-done and completed events. The generated stream
schema advertises these citation-bearing events instead of leaving the SSE body
opaque. Delta events include
OpenAI-style `obfuscation` strings by default; set
`stream_options.include_obfuscation=false` on create-stream requests or
`include_obfuscation=false` on stored response streams to omit them.
File-search streams emit an in-progress `response.output_item.added`
item with empty `queries` and null `results`/`search_results`; final queries
and included results arrive on `response.output_item.done` and the completed
snapshot. Stored response streaming also accepts `starting_after=N` on
`GET /v1/responses/{response_id}?stream=true` and resumes with events whose
`sequence_number` is greater than `N`, so clients can reconnect before missed
citation annotation events.
Unsupported tools return 422. `tool_choice` is also fail-closed for this
file-search citation facade: omitted, `auto`, `required`, forced
`{"type": "file_search"}`, and `allowed_tools` choices that include
`file_search` are accepted; `none`, malformed choices, or choices that force or
allow only non-file-search tools return 422 before retrieval executes.
Responses are stored unless `store=false`; stored responses can be retrieved,
cancelled when created with `background: true`, deleted, and queried for input
items through the OpenAI-compatible lifecycle routes. Response cancel updates
the stored response payload and row status to `cancelled`; it does not add
background execution or interrupt an active HTTP stream. Returned
`file_search_call` items include the planned and executed
`queries` and default `results: null` plus `search_results: null` so clients
can distinguish "not included" from an empty result body through either current
API-reference or guide-style field names.
`POST /v1/responses/input_tokens` returns OpenAI-shaped
`{object: "response.input_tokens", input_tokens: N}` counts for request
preflight. ExAIS counts common text-bearing fields deterministically for SDK
compatibility; this is not a provider-tokenizer billing claim.
`POST /v1/responses/compact` returns an OpenAI-shaped
`response.compaction` object for long-session handoff compatibility. The route
requires a `model`, preserves user input messages as `input_text` items, and
adds a `type: "compaction"` item with opaque `encrypted_content` that can be
passed into a later Responses request. The local opaque value is deterministic
compatibility state, not OpenAI-hosted ZDR encryption or model-generated
summarization.
`include` accepts both `file_search_call.results` and
`output[*].file_search_call.search_results`; when requested, ExAIS returns both
`results` and `search_results` on the `file_search_call` item for current and
cookbook-style client compatibility. Included result entries stay
OpenAI-shaped with `file_id`, `filename`, `score`, `text`, and `attributes`;
chunk/page citation proof and output-guard metadata remain outside those result
objects under native `citations` and `output_guard` fields. If the same chunk is
retrieved from multiple requested vector stores, Responses file-search output
emits it once and records every contributing store in native
`citations[].vector_store_ids`. Each native citation also includes
`annotation`, an exact copy of the strict OpenAI `file_citation` object emitted
under `output_text.annotations`, and `message_annotation`, the OpenAI
message-annotation replacement shape with `start_index`, `end_index`, `text`,
and nested `file_citation.file_id`.
The OpenAI-facing citation contract is locked by regression tests across JSON
Responses, included file-search result bodies, streaming annotation events, and
stored response replay. Native ExAIS fields such as chunk IDs, page ranges,
vector-store IDs, and output-guard details stay outside `output_text.annotations`
and outside included `file_search_call.results` rows.

OpenAI-compatible search request:

```json
{
  "query": "What did the Marker RunPod warmup ticket decide?",
  "max_num_results": 10,
  "filters": {"type": "eq", "key": "classification", "value": "tenant_private"},
  "ranking_options": {
    "ranker": "auto",
    "hybrid_search": {"embedding_weight": 0.65, "text_weight": 0.35}
  },
  "next_page": "vs_search_page_...",
  "include_content": true,
  "include_metadata": true
}
```

OpenAI-compatible search responses include OpenAI-shaped file citation
annotations on returned text content. When content is included, ExAIS appends a
visible source marker and sets `index` to that marker offset:

```json
{
  "type": "file_citation",
  "index": 42,
  "file_id": "file-...",
  "filename": "source.md"
}
```

The same annotation is available at result level under `annotations`. ExAIS also
adds `citation`/`citations` objects with `chunk_id`, `document_id`, page range,
heading path, score, title, public URL, and `start_index`/`end_index` marker
replacement spans when visible content is returned. These citation fields remain
present when `include_content=false`; `citation.annotation` mirrors the strict
OpenAI-facing annotation without the native metadata, and
`citation.message_annotation` mirrors OpenAI's message-annotation replacement
object for the same marker span.
The native citation object also carries a stable `model_source_id` such as
`turn0file0` and a `model_marker` such as
`\ue200cite\ue202turn0file0\ue201` for model-facing citation prompts that
follow OpenAI's recommended Citation Formatting guide.
The generated OpenAPI contract exposes the direct search response as
`OpenAIVectorStoreSearchResultsPage`, with nested
`OpenAIVectorStoreSearchResult`, `OpenAIVectorStoreSearchContent`, and
`OpenAIVectorStoreSearchCitation` components. Result-level and content-level
`annotations` both reference the strict `OpenAIFileCitationAnnotation`
component, while native citation proof references
`OpenAIMessageFileCitationAnnotation` for the replacement-span shape.
Returned text content is passed through `pii_secret_citation_guard_v1` before it
is exposed on the OpenAI-compatible API and before the visible marker is
inserted. Guard metadata, when present, is
reported outside the OpenAI-core annotation object.
Direct search also accepts the opaque `next_page` token returned by a prior
`vector_store.search_results.page`. ExAIS applies the cursor after query
planning, hybrid retrieval, normalization, score-threshold filtering, and
reranking, then returns the next ranked slice. Invalid or out-of-window cursor
tokens return `422`.

Direct search accepts ExAIS-native `lens` and `inputs` fields for per-store
specialized search modes. `GET /v1/vector_stores/{vector_store_id}/search_lenses`
returns the lenses supported by that store, their input schema, graph
relationship types, graph coverage counts, and warnings. Graph lenses fail
closed when they are unsupported, disabled, empty, or declared only for a future
handler.

`POST /v1/vector_stores/{vector_store_id}/graph` loads graph artifacts into the
selected vector store. The route requires `vector_stores:write`, uses the same
tenant/business-instance principal as the rest of the OpenAI-compatible API,
accepts `nodes`, `edges`, `replace`, and `dry_run`, and rejects dangling edges
with `422`. Source-package loaders should use this API route instead of direct
Postgres writes.

Retrieval uses dense embedding search plus sparse text search with reciprocal
rank fusion. Sparse text search is phrase-aware on both local backends:
Postgres FTS uses `websearch_to_tsquery`, and OpenSearch combines boosted
`match_phrase`, all-term match, and broad match clauses under the existing
tenant/security/file filters. The default `hybrid_rrf_secure_v2` profile now
hydrates and post-ACL-filters fused candidates, applies a deterministic local
reranker, then uses lexical MMR diversity so the final `top_k` favors distinct
evidence instead of near-duplicate chunks when relevance scores are close.
Reranked chunks expose updated `score` and `source: hybrid_rrf_rerank`; native
citations and retrieval audit metadata record rerank/diversity proof, while
OpenAI-shaped annotations remain limited to the core citation fields.
Production cells can opt into
`hybrid_rrf_model_gateway_rerank_v1` to route reranking through the internal
model-gateway `/internal/models/rerank` contract; retrieval audit and richer
citations record the gateway provider/model while the API service keeps the same
ACL and citation behavior.
The default local reranker is candidate-aware: it uses query-token IDF across
the retrieved candidate set, exact phrase, ordered-pair, and proximity signals
before blending with fused dense/sparse scores. This promotes chunks that cover
discriminating query terms without requiring external reranker credentials.
The `hybrid_code_symbol_rrf_v2` profile also applies profile-driven exact symbol
boosting after hydration/post-ACL and before final result selection, promoting
chunks that contain identifier, route-path, environment-variable, or config-key
terms from the query. Boost proof is recorded in retrieval audit metadata and
richer native citation metadata; strict OpenAI annotation objects remain
unchanged.

Current compatibility guardrails:

- `max_num_results` maps to internal `top_k` and must be 1..50.
- `top_k` is accepted as a deprecated ExAIS alias on this route for existing
  local ops scripts.
- `next_page` accepts only ExAIS-shaped direct-search cursor tokens and resumes
  after the previous ranked slice.
- Supported filter keys are `document_id`, `knowledge_base_id`,
  `classification`, `acl_bucket`, and safe file attributes. Safe
  file-attribute filters support OpenAI-style `eq`, `ne`, `in`, `nin`, `gt`,
  `gte`, `lt`, `lte`, `and`, and simple positive `or` combinations. String
  range filters are intended for lexicographically sortable values such as ISO
  dates or timestamps. Negation filters require the attribute key to exist.
- `rewrite_query=true` enables deterministic ExAIS query planning and returns
  the effective query in `search_query`.
- `ranking_options.score_threshold` filters normalized 0..1 compatibility
  scores.
- `ranking_options.ranker` accepts OpenAI-compatible values. `auto` and
  `default-2024-11-15` keep retrieval-profile ranker selection, while `none`
  disables request-scoped reranking and diversity before audit/response
  construction.
- `ranking_options.hybrid_search.embedding_weight` and `text_weight` override
  the dense/sparse RRF weights for the request. The aliases
  `rrf_embedding_weight` and `rrf_text_weight` are also accepted.
- Unknown request fields, sensitive file-attribute filters, boolean range
  filters, and `or` filters over internal ExAIS fields, range filters, or
  negation filters return 422.

Run the ticket-fixture parity harness against a live cell:

```bash
python scripts/release/openai-file-search-parity-eval.py --cell local
```

## Examples

See `contracts/examples.http`.
