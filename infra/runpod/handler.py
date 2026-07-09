"""RunPod serverless model handler fallback implementation."""
import hashlib, math

def vector(text: str, dimensions: int = 1024):
    digest = hashlib.sha256(text.encode()).digest()
    vals, i = [], 0
    while len(vals) < dimensions:
        block = hashlib.sha256(digest + i.to_bytes(4, "big")).digest()
        vals.extend([(b / 127.5) - 1 for b in block])
        i += 1
    vals = vals[:dimensions]
    norm = math.sqrt(sum(v*v for v in vals)) or 1
    return [v/norm for v in vals]

def handler(job):
    payload = job.get("input", {})
    operation = payload.get("operation", "embeddings")
    if operation == "rerank":
        query = payload.get("query") or ""
        documents = payload.get("documents") or payload.get("texts") or []
        options = payload.get("options") or {}
        top_n = options.get("topN") or payload.get("top_n")
        query_terms = set(str(query).lower().split())
        results = []
        for i, document in enumerate(documents):
            doc_terms = set(str(document).lower().split())
            score = len(query_terms.intersection(doc_terms)) / max(1, len(query_terms))
            results.append({"index": i, "relevance_score": score})
        results.sort(key=lambda item: item["relevance_score"], reverse=True)
        if top_n:
            results = results[: int(top_n)]
        return {"model": payload.get("model", "exai-vector-store-runpod-fallback-rerank"), "results": results}

    texts = payload.get("input") or payload.get("texts") or []
    if isinstance(texts, str):
        texts = [texts]
    options = payload.get("options") or {}
    dims = int(payload.get("dimensions") or options.get("dimensions") or 1024)
    return {
        "object": "list",
        "model": payload.get("model", "exai-vector-store-runpod-fallback"),
        "data": [{"object": "embedding", "index": i, "embedding": vector(t, dims)} for i, t in enumerate(texts)],
        "usage": {"items": len(texts), "estimatedTokens": sum(len(str(text).split()) for text in texts)},
    }
