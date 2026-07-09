from __future__ import annotations
from fastapi import FastAPI
from svs_common.config import get_settings
from svs_common.model_registry import estimate_embedding_cost, model_registry
from svs_common.providers import provider_for
from svs_common.schemas import EmbeddingRequest, EmbeddingResponse, RerankRequest, RerankResponse, RerankResult, TokenizeRequest, TokenizeResponse
from svs_common.chunking import estimate_tokens

settings = get_settings()
settings.validate_runtime_guards()
app = FastAPI(title="exai_vector_store Model Gateway", version=settings.svs_product_version)

@app.get("/healthz")
def healthz():
    return {"ok": True, "service": "svs-model-gateway", "version": settings.svs_product_version}

@app.get("/internal/models/registry")
def registry():
    return model_registry()

@app.post("/internal/models/embeddings", response_model=EmbeddingResponse)
async def embeddings(req: EmbeddingRequest):
    texts = req.input if isinstance(req.input, list) else [req.input]
    profiles = model_registry().get("models", {})
    profile = profiles.get(req.model_profile_id or "", {})
    provider_name = req.provider or profile.get("provider") or settings.default_embedding_provider
    model = req.model or profile.get("model") or settings.openai_embedding_model
    dimensions = req.dimensions or int(profile.get("dimensions", settings.openai_embedding_dimensions))
    return await provider_for(provider_name).embed(texts, model, dimensions, input_type=req.input_type)

@app.post("/internal/models/rerank", response_model=RerankResponse)
async def rerank(req: RerankRequest):
    # Local lexical fallback. Production rerankers can be routed through model endpoint/provider adapters.
    q = set(req.query.lower().split())
    results = []
    for i, doc in enumerate(req.documents):
        d = set(doc.lower().split())
        results.append(RerankResult(index=i, relevance_score=len(q.intersection(d)) / max(1, len(q))))
    results.sort(key=lambda r: r.relevance_score, reverse=True)
    if req.top_n:
        results = results[: req.top_n]
    return RerankResponse(results=results, model="lexical-overlap-fallback", provider="local")

@app.post("/internal/models/tokenize", response_model=TokenizeResponse)
def tokenize(req: TokenizeRequest):
    return TokenizeResponse(tokens=estimate_tokens(req.text), model=req.model, method="fallback_word_estimate")

@app.post("/internal/models/estimate-cost")
def estimate_cost(req: EmbeddingRequest):
    texts = req.input if isinstance(req.input, list) else [req.input]
    tokens = sum(estimate_tokens(t) for t in texts)
    return estimate_embedding_cost(
        req.model_profile_id,
        tokens,
        provider=req.provider,
        model=req.model,
        dimensions=req.dimensions,
    )
