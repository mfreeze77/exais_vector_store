# OpenAI-Compatible API

SVS mimics OpenAI vector-store behavior at the API-contract level where useful.

Local admin API-key lifecycle routes mirror the relevant OpenAI project API-key
list contract where it fits ExAIS tenancy: `GET /api/v1/admin/api-keys`
returns a list object with `first_id`, `last_id`, `has_more`, a default `limit`
of 20, and an OpenAI-style `after` object-ID cursor. Returned key metadata never
includes the raw key or hash.
OpenAI-compatible project API-key aliases are also exposed:
`GET /v1/organization/projects/{project_id}/api_keys`,
`GET /v1/organization/projects/{project_id}/api_keys/{api_key_id}`, and
`DELETE /v1/organization/projects/{project_id}/api_keys/{api_key_id}`. The
`project_id` must match the current ExAIS business instance ID. List/retrieve
return active keys in the OpenAI `organization.project.api_key` shape with
`redacted_value`, `name`, timestamps, id, and owner id; delete returns
`organization.project.api_key.deleted` with only `id` and `deleted`. These
aliases reuse ExAIS `api_keys:read`/`api_keys:write` scopes and never expose raw
keys, hashes, scopes, or native security metadata in the OpenAI-shaped payload.
Generated `/openapi.json` exposes named `OpenAIProjectApiKey`,
`OpenAIProjectApiKeyListResponse`, and `OpenAIProjectApiKeyDeletedResponse`
components for these aliases.
OpenAI-compatible organization admin API-key aliases are exposed for
OpenAI-compatible operations:
`POST /v1/organization/admin_api_keys`,
`GET /v1/organization/admin_api_keys`,
`GET /v1/organization/admin_api_keys/{key_id}`, and
`DELETE /v1/organization/admin_api_keys/{key_id}`. List accepts OpenAI's
`limit`, `after`, and `order=asc|desc` controls and returns active keys in the
`organization.admin_api_key` shape with `id`, `name`, `redacted_value`,
timestamps, and owner metadata. Create accepts `name` and optional
`expires_in_seconds`, returns the raw `value` exactly once, and inherits the
caller's current ExAIS scopes/max security level instead of accepting privilege
fields. Delete returns
`organization.admin_api_key.deleted` with only `id` and `deleted`. These aliases
reuse ExAIS `api_keys:read`/`api_keys:write` scopes and intentionally do not
expose hashes, scopes, or max security levels through the OpenAI-shaped
payloads; raw key material appears only as create-time `value`.

Routes scaffolded:

- `POST /v1/organization/admin_api_keys`
- `GET /v1/organization/admin_api_keys`
- `GET /v1/organization/admin_api_keys/{key_id}`
- `DELETE /v1/organization/admin_api_keys/{key_id}`
- `GET /v1/organization/projects/{project_id}/api_keys`
- `GET /v1/organization/projects/{project_id}/api_keys/{api_key_id}`
- `DELETE /v1/organization/projects/{project_id}/api_keys/{api_key_id}`
- `POST /v1/responses`
- `POST /v1/responses/compact`
- `POST /v1/responses/input_tokens`
- `GET /v1/responses/{response_id}`
- `POST /v1/responses/{response_id}/cancel`
- `DELETE /v1/responses/{response_id}`
- `GET /v1/responses/{response_id}/input_items`
- `previous_response_id` on `POST /v1/responses`
- `POST /v1/vector_stores`
- `GET /v1/vector_stores`
- `GET /v1/vector_stores/{id}`
- `POST /v1/vector_stores/{id}`
- `PATCH /v1/vector_stores/{id}`
- `DELETE /v1/vector_stores/{id}`
- `POST /v1/files`
- `GET /v1/files`
- `GET /v1/files/{id}`
- `GET /v1/files/{id}/content`
- `DELETE /v1/files/{id}`
- `POST /v1/vector_stores/{id}/files`
- `GET /v1/vector_stores/{id}/files`
- `GET /v1/vector_stores/{id}/files/{file_id}`
- `POST /v1/vector_stores/{id}/files/{file_id}`
- `PATCH /v1/vector_stores/{id}/files/{file_id}`
- `DELETE /v1/vector_stores/{id}/files/{file_id}`
- `GET /v1/vector_stores/{id}/files/{file_id}/content`
- `POST /v1/vector_stores/{id}/file_batches`
- `GET /v1/vector_stores/{id}/file_batches/{batch_id}`
- `POST /v1/vector_stores/{id}/file_batches/{batch_id}/cancel`
- `GET /v1/vector_stores/{id}/file_batches/{batch_id}/files`
- `POST /v1/vector_stores/{id}/search`

The generated `/openapi.json` uses named request and response components for
the supported Responses file-search subset and direct vector-store search.
`POST /v1/responses` references `OpenAIResponseRequest`, and the utility routes reference
`OpenAIResponseInputTokensRequest` and `OpenAIResponseCompactRequest`.
Responses JSON routes reference named response components, and
`OpenAIResponseOutputTextContent.annotations` references the strict
`OpenAIFileCitationAnnotation` component with required `type`, `index`,
`file_id`, and `filename` fields. `POST /v1/vector_stores/{id}/search`
references `OpenAIVectorStoreSearchResultsPage`; nested direct search result,
content, and citation components reuse the same strict annotation component.
The `OpenAIResponseFileSearchTool.max_num_results` request component advertises
the same 20 default and 1..50 bounds used by runtime validation.
`POST /v1/responses` and
`GET /v1/responses/{response_id}` also advertise both `application/json` and
`text/event-stream` 200 response media types. The stream media type references
`OpenAIResponseStreamEvent`, including the citation-bearing
`response.output_text.annotation.added` event. Request schemas remain
permissive where OpenAI has a broader request surface; ExAIS still performs its
fail-closed file-search compatibility validation in route helpers.

## Idempotency

OpenAI-compatible mutating routes accept the `Idempotency-Key` header on
retry-sensitive mutations:

- `POST /v1/files`
- `DELETE /v1/files/{file_id}`
- `POST /v1/vector_stores`
- `POST /v1/vector_stores/{vector_store_id}`
- `PATCH /v1/vector_stores/{vector_store_id}`
- `DELETE /v1/vector_stores/{vector_store_id}`
- `POST /v1/vector_stores/{vector_store_id}/files`
- `POST /v1/vector_stores/{vector_store_id}/files/{file_id}`
- `PATCH /v1/vector_stores/{vector_store_id}/files/{file_id}`
- `DELETE /v1/vector_stores/{vector_store_id}/files/{file_id}`
- `POST /v1/vector_stores/{vector_store_id}/file_batches`
- `POST /v1/vector_stores/{vector_store_id}/file_batches/{batch_id}/cancel`
- `POST /v1/responses`
- `POST /v1/responses/{response_id}/cancel`
- `DELETE /v1/responses/{response_id}`

ExAIS stores the successful response under a stable fingerprint containing the
route, path identifiers, request body, and uploaded file content hash where
applicable. Matching retries return the cached response without replaying the
mutation. Reusing the same key with a different request returns `409`. Streaming
Responses retries replay SSE events from the cached response payload.

## Rate limits

OpenAI-compatible `/v1` routes and the API-key lifecycle admin routes use the
same per-principal `rate_limit_counters` control plane as native retrieval and
ingestion routes. Requests are counted by tenant, business instance, API key or
user subject, route bucket, and minute. Buckets use
`SVS_DEFAULT_RATE_LIMIT_PER_MINUTE` unless the bucket starts with `admin`, which
uses `SVS_ADMIN_RATE_LIMIT_PER_MINUTE`.

Covered buckets include:

- `files.*`
- `vector_stores.*`
- `vector_store_files.*`
- `file_batches.*`
- `responses.*`
- `admin.api_keys.*`

The limiter runs after scope checks and before idempotency lookup, retrieval,
ingestion, mutation, or stored-response lookup. Requests above the configured
limit fail with `429`.
API-key creation also accepts an optional future Unix `expires_at` timestamp;
expired or current timestamps fail before insert, and bearer resolution already
rejects keys whose stored expiration has passed.
File addition routes also mimic OpenAI's per-vector-store add-file request
budget: `POST /v1/vector_stores/{vector_store_id}/files` and
`POST /v1/vector_stores/{vector_store_id}/file_batches` share
`SVS_VECTOR_STORE_FILE_ADD_RATE_LIMIT_PER_MINUTE`, defaulting to 300
requests/minute per vector store ID. This shared resource bucket is enforced
after the route bucket and before idempotency lookup, attachment, batch row
creation, inline enqueue, or commit.

## Files compatibility

`POST /v1/files` accepts OpenAI-shaped multipart uploads with `file` and
`purpose`. ExAIS stores uploaded files as documents with an OpenAI file identity
in document-version metadata, then returns OpenAI file objects. New uploads use
OpenAI's current `file-...` public file ID prefix; legacy stored `file_...`
IDs remain resolvable for existing local data:

- `object: file`
- `id`
- `bytes`
- `created_at`
- `filename`
- `purpose`
- `expires_at` when present

`GET /v1/files` supports `purpose`, `limit`, `order`, and `after`. Its `after`
cursor compares both `created_at` and the public file ID, so same-timestamp
uploaded files page deterministically. Retrieve, content, and delete routes
support both OpenAI file IDs and legacy ExAIS document IDs.
Generated `/openapi.json` exposes `/v1/files` upload, list, retrieve, and delete
JSON responses through `OpenAIFile`, `OpenAIFileListResponse`, and
`OpenAIFileDeletedResponse` components. `GET /v1/files/{file_id}/content`
advertises `text/plain` because the route returns the file contents directly.

Uploaded `file_id` values can be passed directly to
`POST /v1/vector_stores/{vector_store_id}/files` and
`POST /v1/vector_stores/{vector_store_id}/file_batches`. Vector-store file
responses prefer the OpenAI file ID while preserving the internal
`vector_store_file_id` for ExAIS-native callers.

Vector-store file and file-batch file list routes support OpenAI list controls:
`limit`, `order`, `after`, `before`, and status `filter`. Cursor values can be
the public file IDs returned in the list response. File attributes can be
updated with OpenAI's `POST /v1/vector_stores/{vector_store_id}/files/{file_id}`
method; `PATCH` remains accepted for existing ExAIS callers.
Generated `/openapi.json` exposes standalone vector-store file routes through
`OpenAIVectorStoreFile`, `OpenAIVectorStoreFileListResponse`,
`OpenAIVectorStoreFileDeletedResponse`, and
`OpenAIVectorStoreFileContentResponse` components.

File batches accept either OpenAI-style `file_ids` or `files` entries containing
`file_id`, optional `attributes`, and optional `chunking_strategy`. The two
fields are mutually exclusive and batches are capped at the current OpenAI
reference limit of 2000 files. Request-level `attributes`/`metadata` and
`chunking_strategy` apply to every item when `file_ids` is used; `files` entries
carry per-file settings. ExAIS stores chunking strategy as internal attachment
metadata, returns it separately on vector-store file objects, and keeps it out
of public `attributes`. The OpenAI chunking strategy contract is validated
before storage: `auto` is type-only, while `static` only accepts
`max_chunk_size_tokens` between 100 and 4096 and non-negative
`chunk_overlap_tokens` no greater than half the max chunk size.
OpenAI-compatible vector-store metadata and vector-store-file attributes are
validated before storage: public maps are capped at 16 entries, keys must be
non-empty strings of at most 64 characters, and string values are capped at 512
characters. Vector-store metadata values are strings. Vector-store-file
attributes accept string, finite number, and boolean values; nested values,
sensitive searchable keys, and ExAIS reserved internal keys fail with 422.

File-batch create, retrieve, and cancel routes return a normalized
`vector_store.file_batch` object with `created_at`, `status`, and complete
`file_counts`. Cancel targets queued jobs for the batch and moves remaining
`in_progress` counts into `cancelled`.
Generated `/openapi.json` exposes these file-batch responses through
`OpenAIVectorStoreFileBatch`; batch file-list responses use
`OpenAIVectorStoreFileBatchFilesPage` with nested `OpenAIVectorStoreFile`
objects.

`DELETE /v1/files/{file_id}` marks the source document deleted, cancels
associated vector-store file rows, deactivates chunks for attached copies, and
queues stale-vector cleanup. This mirrors OpenAI's delete-file behavior of
removing the file from vector stores while preserving ExAIS audit rows.

Current upload support covers UTF-8, UTF-16, and ASCII text. PDF uploads route
through the configured Marker PDF conversion path when available; otherwise
binary files are rejected with `415` instead of being silently indexed as
unreadable text. Uploads accept OpenAI's created-at anchored expiration policy
via multipart `expires_after[anchor]=created_at` and
`expires_after[seconds]=...`; ExAIS persists that policy on the uploaded
document and returns `expires_at` on the file object.

## Vector-store object compatibility

`POST /v1/vector_stores` accepts OpenAI-shaped create bodies, including an empty
body, `name`, `description`, `file_ids`, `metadata`, `expires_after`, and
`chunking_strategy`. Unknown fields are rejected so SDK/API drift is visible.
When create requests include both `file_ids` and `chunking_strategy`, ExAIS
applies the normalized chunking strategy to the created vector-store file
attachments. Store-level `metadata` stays on the vector-store object and is not
copied into file attributes.

`POST /v1/vector_stores/{vector_store_id}` is the OpenAI-compatible update
method. `PATCH` remains as an ExAIS alias for existing local callers.

Vector-store responses expose OpenAI object fields:

- `object: vector_store`
- `created_at`
- `name`
- `description`
- `bytes`
- `file_counts`
- `metadata`
- `expires_after`
- `expires_at`
- `last_active_at`

The legacy ExAIS fields `usage_bytes` and `attributes` remain in responses for
native clients. They mirror `bytes` and `metadata` respectively.
Generated `/openapi.json` exposes vector-store CRUD routes through
`VectorStoreResponse`, `VectorStoreListResponse`, and
`VectorStoreDeletedResponse` components.

Vector-store list pagination supports `limit`, `order`, `after`, and `before`.
The cursor comparison and ordering use both `created_at` and vector-store ID, so
OpenAI-style cursor pages remain stable even when multiple stores have the same
creation timestamp.

OpenAI `file_id` attachment accepts uploaded `/v1/files` IDs. Legacy ExAIS
document IDs remain accepted for local migration scripts and older fixtures.

Expiration policies are honored for active retrieval use. When
`expires_after.anchor` is `last_active_at`, ExAIS refreshes `last_active_at` and
slides `expires_at` on file attach, ingestion, native retrieval search,
context-pack, OpenAI vector-store search, and Responses file-search. Compatible
create/update requests accept only the OpenAI-shaped policy
`{"anchor": "last_active_at", "days": N}` with positive integer `days`; invalid
anchors, missing days, non-integer days, and legacy nested aliases are rejected.
Expired vector stores return `404` before retrieval runs, even before the
maintenance sweeper marks chunks inactive. The sweeper marks expired
vector-store rows, deactivates chunks for cleanup, queues `purge_stale_vectors`,
and records an audit event.

## Responses file-search compatibility

`POST /v1/responses` supports the OpenAI Responses shape for file-search
retrieval over ExAIS vector stores:

```json
{
  "model": "gpt-5.4-mini",
  "input": "What changed in the Marker RunPod warmup ticket?",
  "tools": [
    {
      "type": "file_search",
      "vector_store_ids": ["vs_..."],
      "ranking_options": {
        "ranker": "auto",
        "score_threshold": 0.0,
        "hybrid_search": {"embedding_weight": 0.65, "text_weight": 0.35}
      }
    }
  ]
}
```

The route extracts query text from string input and common message/content-array
input shapes, runs deterministic query planning by default, and then runs the
existing vector-store search path under `retrieval:read`. Simple request filler
is removed and compound questions are split into bounded subqueries, matching
OpenAI file-search behavior at the contract level without invoking an LLM
rewriter. If a `file_search` tool omits `max_num_results`, ExAIS uses OpenAI's
default of 20. The route returns a completed OpenAI-shaped `response` object
with a `file_search_call` item and a completed assistant message with an
`output_text` content part. By default, the `file_search_call` item includes
the planned and executed `queries`, `results: null`, and
`search_results: null`; result bodies are exposed only when requested through
`include`.

Responses API file citations are exposed where OpenAI clients expect them:

```json
{
  "output": [
    {
      "type": "message",
      "content": [
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
      ]
    }
  ]
}
```

The annotation `index` is the character offset of the visible OpenAI-style
citation marker in the returned output text. Richer ExAIS proof remains
available in the top-level `citations` array with marker, replacement spans,
chunk, document, page, heading, and score fields.
Internally, `openai_response_citation_references` validates and returns the
client-renderable citation mapping: output/content/annotation indexes, exact
`start_index`/`end_index` spans, the visible marker text, and the strict OpenAI
annotation object. It also exports an OpenAI message-annotation shape with
`start_index`, `end_index`, `text`, and nested `file_citation.file_id` for
renderer clients that expect Assistants-style replacement annotations. This
keeps replacement/rendering semantics locked without adding non-OpenAI fields
such as chunk IDs, quotes, spans, or marker text to `output_text.annotations`.
When callers pass either
`include: ["file_search_call.results"]` or
`include: ["output[*].file_search_call.search_results"]`, the file-search call
also includes retrieved search results for debugging and parity inspection.
Multiple `file_citation` annotations may share the same `index` when more than
one retrieved source supports the same visible marker; streaming emits a
separate `response.output_text.annotation.added` event for each annotation while
keeping each OpenAI-facing annotation limited to `type`, `index`, `file_id`,
and `filename`; `index` is constrained to a non-negative marker offset, while
`file_id` and `filename` must be non-empty strings in both runtime validation
and generated OpenAPI schema.
ExAIS returns both the current `results` field and the older cookbook-style
`search_results` alias. Both fields are `null` by default and both contain the
same guarded result array when this include is requested.
ExAIS applies `pii_secret_citation_guard_v1` to retrieved snippets before
building deterministic Responses text. The guard redacts obvious PII and secret
patterns before `【n†source】` markers are inserted, so OpenAI-core annotation
indexes still point at the visible marker. Included `file_search_call.results`
also return guarded text in the OpenAI result shape: `file_id`, `filename`,
`score`, `text`, and `attributes`. ExAIS-only fields such as chunk/page
citation proof, `vector_store_id`, and output-guard metadata stay outside
`file_search_call.results`; use the top-level `citations` and `output_guard`
fields for native audit detail. Each native citation includes an `annotation`
field that exactly mirrors the strict OpenAI `file_citation` object emitted in
`output_text.annotations`, plus a `message_annotation` object using OpenAI's
replacement-span message annotation shape.
Native citation proof also includes `model_source_id` values such as
`turn0file0` plus a `model_marker` such as
`\ue200cite\ue202turn0file0\ue201`, matching OpenAI's recommended
model-facing citation format from the Citation Formatting guide. These fields
are for prompt/rendering pipelines and native audit use; they are intentionally
kept out of OpenAI-facing `output_text.annotations`.
Native citation proof also carries `start_index` and `end_index` values for the
visible marker span so custom renderers can replace exactly the same substring
the OpenAI annotation index points at. The same span is present under
`message_annotation` as
`{type, start_index, end_index, text, file_citation: {file_id}}`.
This citation shape is treated as a compatibility contract: the
`file_search_call` item exposes only OpenAI result fields plus the documented
`search_results` alias, the assistant content part stays
`{type, text, annotations}`, and streamed
`response.output_text.annotation.added` events carry the same strict annotation
object without ExAIS-native citation metadata.
The generated `/openapi.json` also exposes a typed
`OpenAIResponseStreamEvent` union for Responses SSE. Its
`OpenAIResponseOutputTextAnnotationAddedEvent.annotation` field reuses the same
strict `OpenAIFileCitationAnnotation` component as completed
`output_text.annotations`, so generated clients see the citation shape on both
JSON and stream surfaces.
Newly generated Responses payloads are checked before they can be stored,
returned, or streamed. The integrity guard rejects internal formatter output
where a strict OpenAI annotation has extra fields, an annotation index does not
point at a visible `【n†source】` marker, a visible marker has no matching
OpenAI `file_citation` annotation, or native citation proof no longer mirrors
the OpenAI-facing annotation and marker.
Stored Responses payloads are checked again before `GET /v1/responses/{id}`
returns or streams replay events, so corrupted persisted citation JSON fails
closed instead of emitting invalid OpenAI-facing annotations.
The same strict annotation validator and visible-marker span check are reused by
native `/api/v1/retrieval/answer`, so OpenAI-style answer citations cannot drift
from the Responses citation contract.
`previous_response_id` resolves a stored prior response with the same
tenant/business-scoped lookup used by retrieve/delete. When present, ExAIS adds
bounded prior input and assistant output text to the deterministic retrieval
query for the new turn, strips visible citation markers and OpenAI recommended
`\ue200cite...\ue201` model citation markers from prior output before search,
stores chained input items for replay, and returns the requested
`previous_response_id` on the new response. Missing, deleted, or cross-scope
previous responses return 404 before retrieval executes. Prior top-level
`instructions` are not carried over automatically; resend stable instructions on
the new request. Requests that provide both `previous_response_id` and
`conversation` fail with 422 instead of silently mixing conversation-state
strategies.
Stored background Responses can be cancelled through
`POST /v1/responses/{response_id}/cancel`. The route mirrors OpenAI's
background-only cancel contract by rejecting non-background responses, updates
the stored response payload and row status to `cancelled`, and keeps citation
integrity checks in front of the stored/returned payload. It does not add
background model execution or interrupt active HTTP streams.
When the same retrieved chunk appears through more than one requested vector
store, Responses output emits it once, using the highest-scored duplicate for
the excerpt and OpenAI-shaped result row. Native citation proof records all
contributing vector stores under `vector_store_ids`.

This compatibility route does not perform model generation; it deterministically
returns a source-backed retrieval summary. `stream=true` returns
`text/event-stream` server-sent events with OpenAI-style typed lifecycle events,
including `response.created`, `response.file_search_call.searching`,
`response.output_text.delta`, `response.output_text.annotation.added`,
`response.output_text.done`, `response.content_part.done`,
`response.output_item.done`, and `response.completed`. Strict
`file_citation` annotations are emitted before output-text done, then remain
available on content-part-done and completed events. The stream OpenAPI
contract names the annotation-added, content-part-done, and completed event
models so citation-bearing SSE payloads are not advertised as opaque objects.
Delta events carry
OpenAI-style `obfuscation` strings by default; callers can pass
`stream_options: {"include_obfuscation": false}` on create-stream requests or
`include_obfuscation=false` on stored response streams to omit those fields.
For `file_search_call`, the initial `response.output_item.added` event uses an
in-progress item with empty `queries` and null `results`/`search_results`; final
planned queries and included search results are emitted on `response.output_item.done`
and the completed response snapshot.
Stored response stream retrieval supports `starting_after=N` and returns only
events with `sequence_number > N`, allowing clients to reconnect and recover
later citation annotation events. Non-`file_search` tools still return HTTP 422.
The route validates `tool_choice` before search so citation output cannot be
emitted against caller intent: omitted, `auto`, `required`, forced
`{"type": "file_search"}`, and `allowed_tools` choices including `file_search`
are supported, while `none`, malformed choices, and non-file-search choices
return HTTP 422.

When `store` is omitted or `true`, ExAIS persists the full response in a
tenant/business scoped `openai_responses` table with forced RLS. Responses
utility and lifecycle routes include:

- `POST /v1/responses/compact` to return an OpenAI-shaped
  `response.compaction` object. It preserves user input messages, compacts the
  rest of the request into a `type: "compaction"` output item, and exposes an
  opaque `encrypted_content` value for future request handoff. The local value
  is deterministic compatibility state, not OpenAI-hosted ZDR encryption or
  model-generated summarization.
- `POST /v1/responses/input_tokens` to preflight deterministic input-token
  counts for common text-bearing Responses fields. It returns
  `{object: "response.input_tokens", input_tokens: N}` and does not run
  retrieval or store a response. Counts are compatibility estimates rather than
  provider-tokenizer billing truth.
- `GET /v1/responses/{response_id}` to retrieve the completed response.
- `DELETE /v1/responses/{response_id}` to mark it deleted and return
  `{id, object: "response", deleted: true}`.
- `GET /v1/responses/{response_id}/input_items` to list the stored user input
  message items with `limit`, `order`, and `after`.

`store=false` returns a response without persisting it. Deleted or missing
responses return 404 on retrieve and input-items.

## Vector-store search compatibility

`POST /v1/vector_stores/{vector_store_id}/search` accepts the OpenAI-shaped
search fields ExAIS can currently honor:

- `query` as a string or non-empty array of strings
- `max_num_results` bounded to 1..50 and mapped to internal `top_k`
- `top_k` as a deprecated ExAIS alias for existing local ops scripts
- `filters` for supported internal equality keys:
  `document_id`, `knowledge_base_id`, `classification`, `acl_bucket`
- `filters` for safe file attributes using OpenAI-style `eq`, `ne`, `in`,
  `nin`, `gt`, `gte`, `lt`, `lte`, `and`, and simple positive `or` filter
  objects
- `ranking_options.ranker` as a request-shape compatibility field
- `ranking_options.score_threshold` using normalized 0..1 ExAIS scores
- `ranking_options.hybrid_search.embedding_weight` for dense semantic RRF weight
- `ranking_options.hybrid_search.text_weight` for sparse keyword RRF weight
- `rewrite_query` using ExAIS deterministic query planning
- `next_page` using the opaque token returned by the previous direct search page
- `include_content`
- `include_metadata`

The response uses the OpenAI search-results page shape:

- `object: vector_store.search_results.page`
- `search_query`
- `data[]`
- `has_more`
- `next_page`

Each result uses vector-store file metadata when available: `file_id`,
`filename`, file-level `attributes`, `score`, and text `content`.
When more ranked candidates are available than the requested page size, ExAIS
over-fetches one candidate, returns `has_more: true`, and emits an opaque
`next_page` token. Supplying that token on the next search request resumes after
the previous ranked slice while preserving the same query, filter, ranking, and
guard behavior. Invalid or out-of-window tokens fail closed with `422`.

The native retrieval pipeline first performs dense embedding search and sparse
text search, combines those lists with reciprocal rank fusion, hydrates and
post-ACL-filters the candidate chunks, then applies profile-driven reranking
and lexical MMR diversity before final `top_k` selection. The default
`hybrid_rrf_secure_v2` profile uses the deterministic
`local_lexical_overlap_v1` reranker plus `lexical_mmr_v1` diversity, so no
external reranker credentials are required for local cells. Sparse keyword
retrieval is phrase-aware on both supported local backends: Postgres FTS uses
`websearch_to_tsquery`, and OpenSearch boosts phrase matches before all-term
and broad text matches while preserving the same tenant/security/file filters.
The local reranker is candidate-aware: it scores query coverage with IDF-style
weights across the returned candidate set, then adds exact-phrase, ordered-pair,
and token-proximity signals before blending with fused dense/sparse scores.
Rerank/diversity proof is recorded in retrieval audit metadata and richer native
citation metadata while strict OpenAI annotations stay limited to
`type`, `index`, `file_id`, and `filename`. Production cells can select
`hybrid_rrf_model_gateway_rerank_v1` to route reranking through the internal
model-gateway `/internal/models/rerank` contract; audit and richer citation
metadata then include the gateway provider and model.
The code-oriented `hybrid_code_symbol_rrf_v2` profile adds exact symbol boosting
for identifier, route-path, environment-variable, and config-key query terms.
The boost is recorded outside the strict OpenAI annotation object in retrieval
audit and richer native citation metadata.

When content is returned, each text content item includes an OpenAI-shaped
`annotations` array. ExAIS appends a visible source marker to each returned
search-result text item and sets `index` to that marker offset. File citations
use the Responses API citation core:

```json
{
  "type": "file_citation",
  "index": 42,
  "file_id": "file-...",
  "filename": "source.md"
}
```

The same annotation is also exposed at result level under `annotations`, and a
richer ExAIS citation is exposed under `citation`/`citations` plus the page-level
`citations` list. The richer citation keeps the OpenAI core fields and adds
local retrieval proof fields such as `chunk_id`, `document_id`, `page_start`,
`page_end`, `heading_path`, `score`, `title`, and public `url` when the source
URI is user-openable. Citations remain present when `include_content=false` so
clients can request metadata-only search results without losing source handles.
The native citation object also includes `annotation`, an exact copy of the
strict OpenAI-facing citation object, and `message_annotation`, an
Assistants-style replacement annotation for the same marker span.
OpenAI-compatible returned text content is guarded by
`pii_secret_citation_guard_v1` before marker insertion; guard metadata is
reported outside the OpenAI-core `{type, index, file_id, filename}` annotation
object.
The generated OpenAPI response component for this route is
`OpenAIVectorStoreSearchResultsPage`, whose result, content, and native citation
subcomponents all reference the same strict `OpenAIFileCitationAnnotation`
shape for OpenAI-facing annotations. Native citation components also reference
`OpenAIMessageFileCitationAnnotation` for replacement-span citation renderers.

Native `/api/v1/retrieval/context-pack` citations also carry the same
OpenAI-shaped `annotation` object beside ExAIS chunk/page metadata. Context packs
append visible `【n†source】` markers to the returned `context` string and set
each annotation `index` to that marker offset. They can expand same-document
neighbors and parent heading sections under retrieval-profile control, then
expose native relation fields (`context_relation`, `source_chunk_id`,
`neighbor_offset`, and `parent_heading_path`) outside the OpenAI annotation
object. Native context citations also include `message_annotation` with the
same marker replacement span in OpenAI's message annotation shape. Each source
also includes a `Citation Marker:` line using OpenAI's
recommended model-facing marker syntax, and the matching citation object returns
`model_source_id`, `model_marker`, and optional line `model_locator` fields. This
lets native context packs be passed to downstream model prompts while preserving
the strict OpenAI-facing `file_citation` annotation surface. This is intentionally
limited to native context-pack construction; OpenAI-compatible vector-store
search and Responses file-search keep their requested result-count semantics.

File-attribute filtering is intentionally safe-only. ExAIS copies primitive
non-sensitive file attributes into Qdrant/OpenSearch payloads for new ingests,
then enforces the filter again during Postgres hydration under the existing
tenant/business/security scope. Supported OpenAI-compatible file-attribute
filters are exact `eq`, negated exact `ne`, list membership `in`, negated list
membership `nin`, range comparisons (`gt`, `gte`, `lt`, `lte`) over string/date
or numeric values, compound `and`, and simple compound `or` over safe
positive exact/list file-attribute comparisons. Negation requires the attribute
key to exist before excluding matching values, so missing attributes do not
satisfy `ne`/`nin`. String range comparisons are intended for
lexicographically sortable values such as ISO dates or timestamps. Postgres
hydration is the authoritative enforcement point after dense/sparse candidate
retrieval.

`rewrite_query=true` uses deterministic local planning: request filler is
removed, compound questions are split into bounded subqueries, retrieval audit
metadata records the effective query and subqueries, and `search_query` returns
the effective query. Direct search also accepts OpenAI's query-array request
shape. Array entries are trimmed, must be non-empty strings, and are planned
individually when `rewrite_query=true`; ExAIS executes the combined subquery
list, merges the results, and returns the effective query list in
`search_query`.

`ranking_options.ranker` accepts OpenAI-compatible values. The default `auto`
and `default-2024-11-15` values keep ExAIS profile-driven ranker selection:
the default profile uses local dense+sparse RRF plus deterministic post-fusion
reranking and lexical MMR diversity. `ranker: "none"` disables rerank and
diversity for that request only, preserving the fused dense+sparse order and
recording the override in retrieval audit metadata. Scores returned by the
compatibility API are normalized to 0..1 before applying `score_threshold`.
`ranking_options.hybrid_search` overrides dense/sparse RRF weights per request;
ExAIS also accepts OpenAI's `rrf_embedding_weight` and `rrf_text_weight` aliases
and rejects missing, negative, or all-zero hybrid weights.

ExAIS rejects unsupported OpenAI parity features with HTTP 422 instead of
silently pretending to support them:

- unsupported tools on `/v1/responses`
- unknown request fields
- sensitive or structured file-attribute filters
- boolean range filters
- `or` filters that target ExAIS internal filters instead of safe file
  attributes, or that contain range/negation comparisons

SVS does not clone undocumented OpenAI internals. It owns source text, chunks, embeddings metadata, Qdrant/OpenSearch indexes, permissions, audit, and deployment.
