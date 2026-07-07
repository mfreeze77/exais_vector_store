"""RunPod serverless embedding handler fallback implementation."""
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
    texts = payload.get("input") or payload.get("texts") or []
    if isinstance(texts, str):
        texts = [texts]
    dims = int(payload.get("dimensions", 1024))
    return {"object": "list", "model": payload.get("model", "exai-vector-store-runpod-fallback"), "data": [{"object": "embedding", "index": i, "embedding": vector(t, dims)} for i, t in enumerate(texts)]}
