# OpenAI-Compatible API

SVS mimics OpenAI vector-store behavior at the API-contract level where useful.

Routes scaffolded:

- `POST /v1/vector_stores`
- `GET /v1/vector_stores`
- `GET /v1/vector_stores/{id}`
- `DELETE /v1/vector_stores/{id}`
- `POST /v1/vector_stores/{id}/files`
- `POST /v1/vector_stores/{id}/search`

SVS does not clone undocumented OpenAI internals. It owns source text, chunks, embeddings metadata, Qdrant/OpenSearch indexes, permissions, audit, and deployment.
