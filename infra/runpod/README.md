# RunPod Model Endpoint

RunPod is an optional private GPU backend for embeddings/reranking.

Recommended flow:

```text
exai_vector_store API/worker -> exai-vector-store-model-gateway -> RunPod serverless endpoint -> TEI/Infinity/custom handler
```

Use this when an instance disallows external embedding providers or needs specialized open models.
