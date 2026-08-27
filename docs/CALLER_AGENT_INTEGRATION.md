# Caller Agent Integration

This is the caller-side contract for agents that use an ExAIS vector-store cell.
The platform intentionally mirrors useful OpenAI vector-store and Responses
file-search shapes, then adds ExAIS-native proof fields for citations, tenant
scope, security, hybrid retrieval, and optional graph expansion.

## Current integration boundary

ExAIS currently exposes the caller contract over HTTP. This repo does not yet
ship a standalone MCP server package. If an agent framework expects MCP tools,
the MCP server should be a thin adapter around the HTTP endpoints below; it
should not implement retrieval, graph logic, citation formatting, or ACL logic
itself.

For each customer instance, give the caller only these values:

```text
EXAIS_API_BASE=https://api.<customer-domain>
EXAIS_VECTOR_STORE_ID=vs_...
EXAIS_BEARER_KEY=<one-time-created caller key>
```

For the KS State Civics instance, graph expansion is enabled by the instance
profile when these runtime settings are present:

```text
SVS_QUERY_PLANNER_PROFILE_ID=ks_civics_legal_v1
SVS_KSCOURTS_GRAPHRAG_ENABLED=true
SVS_KSCOURTS_GRAPHRAG_MAX_EXPANSIONS=3
```

## API-key creation

Production callers use bearer authentication:

```http
Authorization: Bearer <EXAIS_BEARER_KEY>
```

Create caller keys with an existing admin/operator key that has
`api_keys:write`. The native route is the safest way to create a least-privilege
caller key because it accepts explicit scopes.

```bash
curl -sS -X POST \
  "$EXAIS_API_BASE/api/v1/admin/api-keys?label=ks-agent-readonly&scopes=retrieval%3Aread%2Cvector_stores%3Aread&max_security_level=5" \
  -H "Authorization: Bearer $EXAIS_ADMIN_KEY"
```

The create response returns the plaintext key once as `api_key`. Store it in the
calling app's secret store immediately. List, retrieve, and delete responses only
return metadata and redacted values.

Recommended scopes:

- Search-only fixed vector store: `retrieval:read`
- Search plus vector-store discovery/read checks:
  `retrieval:read,vector_stores:read`
- Caller-managed ingestion:
  `retrieval:read,vector_stores:read,vector_stores:write,documents:write`
- Key creation or operator automation: keep separate from agents; requires
  `api_keys:write`

Do not give a normal user-facing agent `api_keys:write`, `admin:*`, or ingestion
scopes unless that agent is explicitly responsible for lifecycle operations.

API keys are scoped to the customer instance, not to individual vector stores.
Within the same tenant/business instance, the caller's scopes and security level
control what it can do, and the caller-supplied `vector_store_id` controls which
store it searches or mutates. If an agent should only use one or two stores, do
not expose other store IDs in that agent's tool configuration.

OpenAI-compatible admin API-key aliases also exist:

```http
POST   /v1/organization/admin_api_keys
GET    /v1/organization/admin_api_keys
GET    /v1/organization/admin_api_keys/{key_id}
DELETE /v1/organization/admin_api_keys/{key_id}
```

`POST /v1/organization/admin_api_keys` returns the plaintext key once as
`value`, but it inherits the current caller's scopes and max security level. Use
the native create route when you need a purpose-built read-only agent key.

## First admin bootstrap

A fresh production cell needs one bootstrap admin key before callers can use the
API-key lifecycle routes. Use owner/migration database credentials once, and
write the raw key outside the repository. The process environment must include
the resolved `DATABASE_URL` and `SVS_API_KEY_PEPPER` values for the target cell:

```bash
python scripts/release/bootstrap-instance-admin-key.py \
  --database-url "$DATABASE_URL" \
  --tenant-id ten_ks_state_civics \
  --tenant-name "KS State Civics" \
  --tenant-slug ks-state-civics \
  --business-instance-id biz_ks_state_civics \
  --business-name "KS State Civics" \
  --business-slug ks-state-civics \
  --user-id usr_ks_state_civics_admin \
  --user-email "operator@example.com" \
  --user-display-name "KS State Civics Admin" \
  --group-id grp_ks_state_civics_admins \
  --knowledge-base-id kb_ks_state_civics \
  --knowledge-base-name "KS State Civics KB" \
  --knowledge-base-slug ks-state-civics \
  --secret-output "$HOME/exais-secrets/ks-state-civics-admin-key.json"
```

The script creates the minimum tenant, business, operator user, admin group,
membership, knowledge base, and admin API-key row under the correct RLS context.
It refuses to write the raw key under the repo path. Use `--print-secret` only
for an interactive one-time console handoff.

## Vector-store and file lifecycle

An API-key caller can create vector stores and upload files when the key has the
right instance scopes:

- `vector_stores:write` to create or update vector stores.
- `documents:write` to upload files, attach files, and create file batches.
- `retrieval:read` to search after ingestion.

Create a vector store:

```bash
curl -sS -X POST "$EXAIS_API_BASE/v1/vector_stores" \
  -H "Authorization: Bearer $EXAIS_INGEST_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "KS Law",
    "metadata": {
      "corpus": "ks_law"
    }
  }'
```

Upload a file in OpenAI-compatible form:

```bash
curl -sS -X POST "$EXAIS_API_BASE/v1/files" \
  -H "Authorization: Bearer $EXAIS_INGEST_KEY" \
  -F "purpose=assistants" \
  -F "file=@./source.pdf"
```

Attach an uploaded file to a vector store:

```bash
curl -sS -X POST "$EXAIS_API_BASE/v1/vector_stores/$EXAIS_VECTOR_STORE_ID/files" \
  -H "Authorization: Bearer $EXAIS_INGEST_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "file_id": "file-..."
  }'
```

Create a vector store and attach existing files in one request:

```bash
curl -sS -X POST "$EXAIS_API_BASE/v1/vector_stores" \
  -H "Authorization: Bearer $EXAIS_INGEST_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Kansas Supreme Court and Appeals",
    "file_ids": ["file-..."],
    "metadata": {
      "corpus": "ks_courts"
    }
  }'
```

Attach many files with a batch:

```bash
curl -sS -X POST "$EXAIS_API_BASE/v1/vector_stores/$EXAIS_VECTOR_STORE_ID/file_batches" \
  -H "Authorization: Bearer $EXAIS_INGEST_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "file_ids": ["file-...", "file-..."]
  }'
```

The same uploaded file can be attached to more than one vector store inside the
same instance. For example, a public Kansas law store and a court-opinion store
can share source files when the caller intentionally attaches them to both.

Run the repeatable lifecycle proof against a live cell after creating the
bootstrap admin key:

```bash
python scripts/release/instance-caller-lifecycle-proof.py \
  --api-base "$EXAIS_API_BASE" \
  --admin-key "$EXAIS_ADMIN_KEY" \
  --output .release/cells/ks-state-civics/caller-lifecycle-proof.json
```

When `--admin-key` is supplied, the proof script creates temporary ingestion and
search-only API keys, creates two vector stores, uploads a fixture file, attaches
it directly to one store, attaches it by file batch to another store, searches
both stores with the search-only key, verifies citations, verifies
multi-store `/v1/responses` file search, and revokes the temporary keys unless
`--keep-created-keys` is passed. The output proof contains redacted key metadata
only.

## Recommended MCP tools

Expose three tools to the calling agent. The first two both call direct
vector-store search; the graph tool is a caller-facing specialization that tells
the model when graph expansion was applied. The third tool uses the
OpenAI-compatible Responses file-search facade when the caller wants a
Responses-shaped retrieval summary.

### `exais_vector_search`

Use this for normal semantic, keyword, and hybrid retrieval.

HTTP route:

```http
POST /v1/vector_stores/{vector_store_id}/search
```

Minimum HTTP body:

```json
{
  "query": "What did the court say about ...?",
  "max_num_results": 8,
  "rewrite_query": true,
  "include_content": true,
  "include_metadata": true
}
```

MCP tool schema:

```json
{
  "name": "exais_vector_search",
  "description": "Search an ExAIS vector store using hybrid semantic and keyword retrieval. Returns source text plus OpenAI-style and ExAIS-native citations.",
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "query": {
        "type": "string",
        "description": "Natural-language search query."
      },
      "vector_store_id": {
        "type": "string",
        "description": "Defaults to the customer instance vector store."
      },
      "max_num_results": {
        "type": "integer",
        "minimum": 1,
        "maximum": 50,
        "default": 8
      },
      "filters": {
        "type": "object",
        "description": "Optional OpenAI-style safe filters."
      },
      "score_threshold": {
        "type": "number",
        "minimum": 0,
        "maximum": 1
      },
      "include_content": {
        "type": "boolean",
        "default": true
      }
    },
    "required": ["query"]
  }
}
```

Adapter behavior:

- Send `Authorization: Bearer <EXAIS_BEARER_KEY>`.
- Default `vector_store_id` from instance config when omitted.
- Map `score_threshold` to
  `ranking_options.score_threshold`.
- Return the API response body directly; do not strip citations.

### `exais_legal_graph_search`

Use this for graph-shaped legal questions such as cited-by, cited authority,
same docket, related party, precedent, and citation-network questions.

HTTP route:

```http
POST /v1/vector_stores/{vector_store_id}/search
```

Minimum HTTP body:

```json
{
  "query": "Find cases cited by State v. Clapp and related authority.",
  "max_num_results": 10,
  "rewrite_query": true,
  "include_content": true,
  "include_metadata": true
}
```

MCP tool schema:

```json
{
  "name": "exais_legal_graph_search",
  "description": "Search the KS civics legal vector store and surface graph-expanded relationships such as cited_by, cited_authority, same_docket, and related_party when available.",
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "query": {
        "type": "string",
        "description": "Question with legal graph intent, for example cited by, cites, citation, related, same docket, same party, authority, precedent."
      },
      "vector_store_id": {
        "type": "string",
        "description": "Defaults to the KS State Civics vector store."
      },
      "max_num_results": {
        "type": "integer",
        "minimum": 1,
        "maximum": 50,
        "default": 10
      },
      "require_graph": {
        "type": "boolean",
        "default": false,
        "description": "Adapter-level flag. If true, report when graph_expansion is missing or not applied."
      }
    },
    "required": ["query"]
  }
}
```

Adapter behavior:

- Call the same `/v1/vector_stores/{vector_store_id}/search` route.
- Inspect top-level `graph_expansion`.
- If `require_graph=true` and `graph_expansion.applied` is not true, return a
  tool-level warning but keep the semantic results.
- Preserve `citation.graph_expansion` on each result. That object identifies the
  graph profile, relation type, edge id, source document, target document,
  attributes, and provenance.

Graph expansion is additive. It does not replace semantic retrieval. The API
first finds seed results with normal retrieval, then adds graph-neighbor chunks
when the KS civics graph profile is enabled and the query has graph intent.

### `exais_responses_file_search`

Use this when the caller wants the closest OpenAI Responses file-search shape.
This endpoint returns a deterministic retrieval summary with citations; it is
not an LLM answer generator.

HTTP route:

```http
POST /v1/responses
```

Minimum HTTP body:

```json
{
  "model": "exais-retrieval",
  "input": "Summarize the key holdings with citations.",
  "tools": [
    {
      "type": "file_search",
      "vector_store_ids": ["vs_..."],
      "max_num_results": 10
    }
  ],
  "include": ["file_search_call.results"],
  "store": false
}
```

MCP tool schema:

```json
{
  "name": "exais_responses_file_search",
  "description": "Run the OpenAI-compatible Responses file_search facade over an ExAIS vector store and return output_text annotations plus native citation proof.",
  "inputSchema": {
    "type": "object",
    "additionalProperties": false,
    "properties": {
      "input": {
        "type": "string",
        "description": "Question or retrieval instruction."
      },
      "vector_store_ids": {
        "type": "array",
        "items": {"type": "string"},
        "minItems": 1
      },
      "max_num_results": {
        "type": "integer",
        "minimum": 1,
        "maximum": 50,
        "default": 20
      },
      "include_results": {
        "type": "boolean",
        "default": true
      },
      "store": {
        "type": "boolean",
        "default": false
      }
    },
    "required": ["input"]
  }
}
```

Adapter behavior:

- Default `vector_store_ids` to the customer instance vector store.
- Use `include: ["file_search_call.results"]` when the agent needs snippets, not
  only final `output_text`.
- Return both OpenAI-facing `output_text.annotations` and native top-level
  `citations`.

## Response and citation fields

Direct vector-store search returns:

```json
{
  "object": "vector_store.search_results.page",
  "search_query": "effective query",
  "data": [
    {
      "file_id": "file-...",
      "filename": "source.pdf",
      "score": 0.91,
      "attributes": {},
      "content": [
        {
          "type": "text",
          "text": "Retrieved excerpt ... [source marker]",
          "annotations": [
            {
              "type": "file_citation",
              "index": 123,
              "file_id": "file-...",
              "filename": "source.pdf"
            }
          ]
        }
      ],
      "citation": {
        "chunk_id": "chk_...",
        "document_id": "doc_...",
        "page_start": 4,
        "page_end": 5,
        "title": "Case title",
        "url": "https://...",
        "model_source_id": "turn0file0",
        "model_marker": "<model-facing citation marker>",
        "graph_expansion": {
          "profile": "kscourts_postgres_graph_v1",
          "relation_type": "cited_by",
          "edge_id": "edge_...",
          "source_document_id": "doc_seed",
          "target_document_id": "doc_related",
          "attributes": {},
          "provenance": {}
        }
      },
      "citations": []
    }
  ],
  "citations": [],
  "has_more": false,
  "next_page": null,
  "graph_expansion": {
    "enabled": true,
    "applied": true,
    "candidate_count": 3,
    "inserted_chunk_count": 2,
    "relation_types": ["cited_by", "cited_authority"],
    "annotated_result_count": 2
  }
}
```

The OpenAI-facing citation surface is intentionally strict:

```json
{
  "type": "file_citation",
  "index": 42,
  "file_id": "file-...",
  "filename": "source.pdf"
}
```

Use native `citation` and `citations` for richer audit and renderer behavior:
chunk id, document id, page range, title, URL, heading path, score, marker spans,
`model_source_id`, `model_marker`, and graph relation metadata.

## Caller answer policy

The calling agent should follow these rules:

- Search before answering customer-domain questions.
- Answer only from returned `content[].text`, `file_search_call.results`, and
  citation metadata.
- Preserve source identity in the final answer by including the returned
  filename/title and citation marker data.
- If no result supports the answer, say that the vector store did not return
  support.
- Treat graph-expanded hits as relation evidence. For legal material, label
  whether the relation is `cited_by`, `cited_authority`, `same_docket`, or
  `related_party` instead of presenting all graph hits as direct holdings.
- Do not expose raw API keys, admin routes, internal document IDs, or graph edge
  IDs to an end user unless the UI is explicitly an operator/debug surface.

## Minimal TypeScript adapter

```ts
type ExaisSearchArgs = {
  query: string;
  vector_store_id?: string;
  max_num_results?: number;
  filters?: Record<string, unknown>;
  score_threshold?: number;
  include_content?: boolean;
};

export async function exaisVectorSearch(args: ExaisSearchArgs) {
  const base = process.env.EXAIS_API_BASE;
  const key = process.env.EXAIS_BEARER_KEY;
  const vectorStoreId = args.vector_store_id ?? process.env.EXAIS_VECTOR_STORE_ID;

  if (!base || !key || !vectorStoreId) {
    throw new Error("Missing ExAIS API base, bearer key, or vector store id");
  }

  const body = {
    query: args.query,
    max_num_results: args.max_num_results ?? 8,
    filters: args.filters,
    rewrite_query: true,
    include_content: args.include_content ?? true,
    include_metadata: true,
    ranking_options: args.score_threshold === undefined
      ? undefined
      : {score_threshold: args.score_threshold}
  };

  const response = await fetch(`${base}/v1/vector_stores/${vectorStoreId}/search`, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${key}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify(body)
  });

  if (!response.ok) {
    throw new Error(`ExAIS search failed: ${response.status} ${await response.text()}`);
  }

  return response.json();
}
```

For an MCP server, bind this function to `exais_vector_search`. Bind
`exais_legal_graph_search` to the same function and add adapter-side validation
of `graph_expansion`. Bind `exais_responses_file_search` to `POST /v1/responses`.

## Instance handoff checklist

Before handing a customer instance to a caller agent, record:

- Public API base URL.
- Vector store ID.
- Read-only bearer key creation time, key id, scopes, max security level, and
  expiration policy.
- Whether the caller may ingest or only search.
- Whether graph expansion is enabled for the instance.
- A smoke search with at least one returned citation.
- A graph-intent smoke search for legal instances, including the
  `graph_expansion` object when available.
