from __future__ import annotations
from time import perf_counter

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import PlainTextResponse
import httpx
from svs_common.config import get_settings
from svs_common.model_registry import (
    ModelRegistryConfigurationError,
    estimate_embedding_cost,
    model_registry,
    resolve_expert_chat_profiles,
)
from svs_common.providers import (
    ProviderConfigurationError,
    chat_provider_config_status,
    chat_provider_for,
    provider_config_status,
    provider_for,
    provider_for_rerank,
)
from svs_common.schemas import (
    EmbeddingRequest,
    EmbeddingResponse,
    ExpertChatAttempt,
    ExpertChatCompletionRequest,
    ExpertChatCompletionResponse,
    ExpertChatFallback,
    ExpertChatUsage,
    RerankRequest,
    RerankResponse,
    RerankResult,
    TokenizeRequest,
    TokenizeResponse,
)
from svs_common.chunking import estimate_tokens

settings = get_settings()
settings.validate_runtime_guards()
app = FastAPI(title="exai_vector_store Model Gateway", version=settings.svs_product_version)

@app.get("/healthz")
def healthz():
    return {"ok": True, "service": "svs-model-gateway", "version": settings.svs_product_version}

def _metric_value(value) -> str:
    try:
        numeric = float(value or 0)
    except (TypeError, ValueError):
        numeric = 0.0
    if numeric.is_integer():
        return str(int(numeric))
    return f"{numeric:.10g}"

def _label_value(value) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')

def _metric_line(name: str, value, labels: dict[str, str] | None = None) -> str:
    if labels:
        label_text = ",".join(f'{key}="{_label_value(labels[key])}"' for key in sorted(labels))
        return f"{name}{{{label_text}}} {_metric_value(value)}"
    return f"{name} {_metric_value(value)}"

@app.get("/metrics", response_class=PlainTextResponse)
def metrics():
    registry_data = model_registry()
    models = registry_data.get("models", {})
    embedding_profiles = {
        profile_id: profile
        for profile_id, profile in models.items()
        if isinstance(profile, dict) and profile.get("kind") == "embedding"
    }
    priced_profiles = {
        profile_id: profile
        for profile_id, profile in embedding_profiles.items()
        if (profile.get("cost") or {}).get("input_per_1m_tokens_usd") is not None
    }
    provider_counts: dict[str, int] = {}
    for profile in embedding_profiles.values():
        provider = str(profile.get("provider") or "unknown")
        provider_counts[provider] = provider_counts.get(provider, 0) + 1

    lines = [
        _metric_line("svs_model_gateway_build_info", 1, {"version": settings.svs_product_version}),
        _metric_line("svs_model_gateway_embedding_profiles", len(embedding_profiles)),
        _metric_line("svs_model_gateway_priced_embedding_profiles", len(priced_profiles)),
        _metric_line("svs_model_gateway_unpriced_embedding_profiles", len(embedding_profiles) - len(priced_profiles)),
    ]
    for provider, count in sorted(provider_counts.items()):
        lines.append(_metric_line("svs_model_gateway_embedding_profiles_by_provider", count, {"provider": provider}))
    return "\n".join(lines) + "\n"

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


def _chat_candidate_unavailable_code(req: ExpertChatCompletionRequest, profile: dict) -> str | None:
    max_security_level = int(profile.get("max_security_level", 0))
    if req.security_level > max_security_level:
        return "security_policy_denied"
    if profile.get("local_only") and not settings.is_local_env:
        return "local_only_provider_denied"
    status_value = chat_provider_config_status(str(profile.get("provider") or ""), settings)
    if not status_value.configured:
        return "provider_unconfigured"
    return None


def _fallback_reason(attempts: list[ExpertChatAttempt]) -> str | None:
    if not attempts or attempts[0].status == "succeeded":
        return None
    if attempts[0].status == "unavailable":
        return "preferred_provider_unavailable"
    return "preferred_provider_failed"


@app.post("/internal/models/expert-chat", response_model=ExpertChatCompletionResponse)
async def expert_chat(req: ExpertChatCompletionRequest):
    try:
        candidates = resolve_expert_chat_profiles(req.model_policy)
    except ModelRegistryConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_expert_chat_policy", "message": str(exc)},
        ) from exc

    attempts: list[ExpertChatAttempt] = []
    requested_profile_id = candidates[0][0]
    for profile_id, profile in candidates:
        provider_name = str(profile["provider"])
        model = str(profile["model"])
        unavailable_code = _chat_candidate_unavailable_code(req, profile)
        if unavailable_code:
            attempts.append(
                ExpertChatAttempt(
                    model_profile_id=profile_id,
                    provider=provider_name,
                    model=model,
                    status="unavailable",
                    error_code=unavailable_code,
                )
            )
            continue

        try:
            provider = chat_provider_for(provider_name, settings)
        except ProviderConfigurationError:
            attempts.append(
                ExpertChatAttempt(
                    model_profile_id=profile_id,
                    provider=provider_name,
                    model=model,
                    status="unavailable",
                    error_code="provider_unconfigured",
                )
            )
            continue

        started = perf_counter()
        try:
            completion = await provider.complete(
                req.messages,
                model,
                max_output_tokens=req.max_output_tokens,
                temperature=req.temperature,
            )
        except (ProviderConfigurationError, httpx.HTTPError, TimeoutError, OSError) as exc:
            latency_ms = max(0, round((perf_counter() - started) * 1000))
            attempts.append(
                ExpertChatAttempt(
                    model_profile_id=profile_id,
                    provider=provider_name,
                    model=model,
                    status="failed",
                    latency_ms=latency_ms,
                    error_code=type(exc).__name__,
                )
            )
            continue

        latency_ms = max(0, round((perf_counter() - started) * 1000))
        attempts.append(
            ExpertChatAttempt(
                model_profile_id=profile_id,
                provider=provider_name,
                model=completion.model,
                status="succeeded",
                latency_ms=latency_ms,
            )
        )
        fallback_occurred = profile_id != requested_profile_id
        return ExpertChatCompletionResponse(
            content=completion.content,
            policy_id=req.model_policy.policy_id,
            requested_model_profile_id=requested_profile_id,
            model_profile_id=profile_id,
            provider=provider_name,
            model=completion.model,
            latency_ms=latency_ms,
            usage=ExpertChatUsage(**completion.usage),
            finish_reason=completion.finish_reason,
            fallback=ExpertChatFallback(
                occurred=fallback_occurred,
                from_model_profile_id=requested_profile_id if fallback_occurred else None,
                reason=_fallback_reason(attempts) if fallback_occurred else None,
                attempts=attempts,
            ),
        )

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={
            "code": "expert_chat_provider_unavailable",
            "policy_id": req.model_policy.policy_id,
            "attempts": [attempt.model_dump(mode="json") for attempt in attempts],
        },
    )

def _lexical_rerank(req: RerankRequest) -> RerankResponse:
    q = set(req.query.lower().split())
    results = []
    for i, doc in enumerate(req.documents):
        d = set(doc.lower().split())
        results.append(RerankResult(index=i, relevance_score=len(q.intersection(d)) / max(1, len(q))))
    results.sort(key=lambda r: r.relevance_score, reverse=True)
    if req.top_n:
        results = results[: req.top_n]
    return RerankResponse(results=results, model="lexical-overlap-fallback", provider="local")


def _configured_reranker(req: RerankRequest) -> tuple[str | None, str | None]:
    rerankers = model_registry().get("rerankers", {})
    profile = rerankers.get(req.model_profile_id or "", {})
    if req.provider:
        return req.provider, req.model or profile.get("model") or req.model_profile_id
    provider = profile.get("provider")
    if provider and provider != "disabled":
        return provider, req.model or profile.get("model") or req.model_profile_id
    for candidate_id in profile.get("candidates") or []:
        candidate = rerankers.get(candidate_id, {})
        candidate_provider = candidate.get("provider")
        if not candidate_provider or candidate_provider == "disabled":
            continue
        if provider_config_status(candidate_provider).configured:
            return candidate_provider, candidate.get("model") or candidate_id
    return None, None


@app.post("/internal/models/rerank", response_model=RerankResponse)
async def rerank(req: RerankRequest):
    provider_name, model = _configured_reranker(req)
    if provider_name and model:
        try:
            return await provider_for_rerank(provider_name).rerank(req.query, req.documents, model, top_n=req.top_n)
        except (ProviderConfigurationError, httpx.HTTPError, TimeoutError, OSError):
            return _lexical_rerank(req)
    return _lexical_rerank(req)

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
