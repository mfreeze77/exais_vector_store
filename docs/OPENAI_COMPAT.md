# OpenAI-Compatible API

SVS mimics OpenAI vector-store behavior at the API-contract level where useful.

Routes scaffolded:

- `POST /v1/vector_stores`
- `GET /v1/vector_stores`
- `GET /v1/vector_stores/{id}`
- `DELETE /v1/vector_stores/{id}`
- `POST /v1/vector_stores/{id}/files`
- `POST /v1/vector_stores/{id}/search`

## Vector-store search compatibility

`POST /v1/vector_stores/{vector_store_id}/search` accepts the OpenAI-shaped
search fields ExAIS can currently honor:

- `query`
- `max_num_results` bounded to 1..50 and mapped to internal `top_k`
- `top_k` as a deprecated ExAIS alias for existing local ops scripts
- `filters` for supported internal equality keys:
  `document_id`, `knowledge_base_id`, `classification`, `acl_bucket`
- `filters` for safe file attributes using OpenAI-style `eq` filter objects
- `ranking_options.ranker` as a request-shape compatibility field
- `ranking_options.score_threshold` using normalized 0..1 ExAIS scores
- `rewrite_query` using ExAIS deterministic query planning
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

File-attribute filtering is intentionally safe-only. ExAIS copies primitive
non-sensitive file attributes into Qdrant/OpenSearch payloads for new ingests,
then enforces the filter again during Postgres hydration under the existing
tenant/business/security scope.

`rewrite_query=true` uses deterministic local planning: request filler is
removed, compound questions are split into bounded subqueries, retrieval audit
metadata records the effective query and subqueries, and `search_query` returns
the effective query.

`ranking_options.ranker` accepts OpenAI-compatible values, but ExAIS currently
uses local dense+sparse RRF rather than an external reranker. Scores returned by
the compatibility API are normalized to 0..1 before applying
`score_threshold`.

ExAIS rejects unsupported OpenAI parity features with HTTP 422 instead of
silently pretending to support them:

- unknown request fields
- sensitive or structured file-attribute filters
- unsupported comparison operations
- `or` filters

SVS does not clone undocumented OpenAI internals. It owns source text, chunks, embeddings metadata, Qdrant/OpenSearch indexes, permissions, audit, and deployment.
