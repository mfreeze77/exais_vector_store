# Architecture

`exai_vector_store` is the Expert AI Services retrieval operating system. Vectors are one index, not the source of truth.

```text
Frontend / SDK
  -> exai-vector-store-api
  -> identity + tenant + security resolver
  -> vectorization router
  -> exai-vector-store-worker ingestion
  -> exai-vector-store-model-gateway
  -> Postgres truth/control plane
  -> Qdrant dense vector index
  -> OpenSearch sparse/BM25/code/phrase index
  -> MinIO/S3 originals + snapshots
  -> retrieval gateway
  -> cited context pack
```

## Services

- `exai-vector-store-api`: native and OpenAI-compatible API, retrieval orchestration.
- `exai-vector-store-worker`: ingestion jobs, parsing, chunking, embedding, indexing.
- `exai-vector-store-model-gateway`: embeddings, reranking, token counting, provider routing.
- `exai-vector-store-instance-agent`: deploy, upgrade, backup, rollback micro-production instances.

## Retrieval hot path

```text
query
  -> principal + security scope
  -> pre-search filter
  -> query embedding
  -> Qdrant dense search
  -> OpenSearch sparse search
  -> RRF fusion
  -> Postgres hydration
  -> post-retrieval ACL check
  -> context pack with citations
  -> audit event
```
