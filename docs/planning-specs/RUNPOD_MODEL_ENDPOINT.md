# RunPod Model Endpoint Supplement

Use RunPod as an optional private GPU model backend behind `exai-vector-store-model-gateway`.

## Endpoint roles

- Embedding endpoint: Qwen3 Embedding, BGE-M3, Jina v4, Nomic, or other Hugging Face models.
- Reranker endpoint: Qwen3 Reranker, BGE reranker, Jina reranker, or other cross-encoder.
- Research endpoint: multimodal/document models that need GPU acceleration.

## Runtime choices

1. Hugging Face Text Embeddings Inference for high-throughput embedding serving.
2. Infinity for embeddings, reranking, CLIP, CLAP, and ColPali-like models.
3. Custom Python handler for unusual pooling, task adapters, late-interaction outputs, or multimodal packaging.

## exai_vector_store request contract

```json
{
  "operation": "embeddings",
  "model": "Qwen/Qwen3-Embedding-4B",
  "input": ["chunk one", "chunk two"],
  "options": {
    "normalize": true,
    "inputType": "document"
  }
}
```

## exai_vector_store response contract

```json
{
  "model": "Qwen/Qwen3-Embedding-4B",
  "data": [
    {"index": 0, "embedding": [0.01, -0.02]},
    {"index": 1, "embedding": [0.03, 0.04]}
  ],
  "usage": {
    "items": 2,
    "estimatedTokens": 412
  }
}
```

## Production rules

- Model endpoints are registered in `model_endpoints`.
- Every endpoint has health checks, p95 latency, max security level, region, and auth secret reference.
- Do not route high-security data to external providers if the instance policy requires local/private models.
- Use model-cache volumes for startup speed, but do not use the model-cache volume as an application database.
- Pin model revisions and container image digests.
