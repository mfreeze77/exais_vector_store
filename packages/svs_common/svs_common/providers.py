from __future__ import annotations
import hashlib, math
from dataclasses import dataclass
from typing import Any
from typing import Protocol
import httpx
from .config import get_settings
from .provider_probe import health_allows_routing, normalize_health_status
from .schemas import EmbeddingData, EmbeddingResponse, RerankResponse, RerankResult

class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str], model: str, dimensions: int, input_type: str | None = None) -> EmbeddingResponse: ...

class RerankProvider(Protocol):
    async def rerank(self, query: str, documents: list[str], model: str, top_n: int | None = None) -> RerankResponse: ...

class ProviderConfigurationError(RuntimeError):
    """Raised when a selected provider is not configured for runtime use."""

@dataclass(frozen=True)
class ProviderConfigStatus:
    provider: str
    configured: bool
    required_env: tuple[str, ...] = ()
    reason: str | None = None
    health_status: str = "unknown"
    p95_latency_ms: int | None = None
    max_security_level: int | None = None
    region: str | None = None
    model_revision: str | None = None
    auth_secret_ref: str | None = None
    routing_state: str = "unknown"


def _setting(settings: Any, name: str) -> str | None:
    value = getattr(settings, name, None)
    if value is None:
        return None
    return str(value).strip()


def _status(
    provider: str,
    env_names: tuple[str, ...],
    configured: bool,
    reason: str | None = None,
    **metadata: Any,
) -> ProviderConfigStatus:
    if configured:
        return ProviderConfigStatus(provider=provider, configured=True, required_env=env_names, **metadata)
    missing = ", ".join(env_names) if env_names else "provider configuration"
    return ProviderConfigStatus(
        provider=provider,
        configured=False,
        required_env=env_names,
        reason=reason or f"{provider} embedding provider requires {missing}",
        **metadata,
    )


def provider_config_status(provider_name: str, settings: Any | None = None) -> ProviderConfigStatus:
    provider = (provider_name or "").strip().lower()
    s = settings or get_settings()
    if provider == "hash_mock":
        return ProviderConfigStatus(provider=provider, configured=True)
    if provider == "openai":
        return _status(provider, ("OPENAI_API_KEY",), bool(_setting(s, "openai_api_key")))
    if provider == "voyage":
        return _status(provider, ("VOYAGE_API_KEY",), bool(_setting(s, "voyage_api_key")))
    if provider == "cohere":
        return _status(provider, ("COHERE_API_KEY",), bool(_setting(s, "cohere_api_key")))
    if provider in {"jina", "tei", "huggingface_tei"}:
        return _status(provider, ("TEI_ENDPOINT_URL",), bool(_setting(s, "tei_endpoint_url")))
    if provider in RUNPOD_PROVIDERS:
        return _status(
            provider,
            ("RUNPOD_EMBEDDING_ENDPOINT_URL",),
            bool(_setting(s, "runpod_embedding_endpoint_url")),
            auth_secret_ref="envref://RUNPOD_API_KEY" if _setting(s, "runpod_api_key") else None,
        )
    if provider == "infinity":
        return _status(provider, ("INFINITY_ENDPOINT_URL",), bool(_setting(s, "infinity_endpoint_url")))
    if provider in {"self_hosted", "openai_compatible_private"}:
        return _status(
            provider,
            ("SELF_HOSTED_MODEL_ENDPOINT_URL",),
            bool(_setting(s, "self_hosted_model_endpoint_url")),
            auth_secret_ref="envref://SELF_HOSTED_MODEL_API_KEY" if _setting(s, "self_hosted_model_api_key") else None,
        )
    return ProviderConfigStatus(
        provider=provider or "unknown",
        configured=False,
        reason=f"unknown embedding provider: {provider_name}",
    )


class HashEmbeddingProvider:
    provider = 'hash_mock'
    async def embed(self, texts: list[str], model: str = 'deterministic-dev-hash', dimensions: int = 1536, input_type: str | None = None) -> EmbeddingResponse:
        data = [EmbeddingData(embedding=self._vector(t, dimensions), index=i) for i, t in enumerate(texts)]
        return EmbeddingResponse(data=data, model=model, provider=self.provider, dimensions=dimensions, usage={'prompt_tokens': sum(len(t.split()) for t in texts), 'total_tokens': sum(len(t.split()) for t in texts)})

    def _vector(self, text: str, dimensions: int) -> list[float]:
        digest = hashlib.sha256(text.encode()).digest()
        vals, i = [], 0
        while len(vals) < dimensions:
            block = hashlib.sha256(digest + i.to_bytes(4, 'big')).digest()
            vals.extend([(b / 127.5) - 1.0 for b in block])
            i += 1
        vals = vals[:dimensions]
        norm = math.sqrt(sum(v * v for v in vals)) or 1.0
        return [v / norm for v in vals]

class OpenAIEmbeddingProvider:
    provider = 'openai'
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    async def embed(self, texts: list[str], model: str, dimensions: int, input_type: str | None = None) -> EmbeddingResponse:
        api_key = self.api_key or get_settings().openai_api_key
        if not api_key:
            raise ProviderConfigurationError("openai embedding provider requires OPENAI_API_KEY")
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                'https://api.openai.com/v1/embeddings',
                headers={'Authorization': f'Bearer {api_key}'},
                json={'model': model, 'input': texts, 'dimensions': dimensions},
            )
            resp.raise_for_status()
            body = resp.json()
        data = [EmbeddingData(embedding=item['embedding'], index=item['index']) for item in body.get('data', [])]
        return EmbeddingResponse(data=data, model=body.get('model', model), provider=self.provider, dimensions=dimensions, usage=body.get('usage', {}))

class VoyageEmbeddingProvider:
    provider = 'voyage'
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    async def embed(self, texts: list[str], model: str, dimensions: int, input_type: str | None = None) -> EmbeddingResponse:
        api_key = self.api_key or get_settings().voyage_api_key
        if not api_key:
            raise ProviderConfigurationError("voyage embedding provider requires VOYAGE_API_KEY")
        payload = {'model': model, 'input': texts, 'output_dimension': dimensions}
        if input_type:
            payload['input_type'] = input_type
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                'https://api.voyageai.com/v1/embeddings',
                headers={'Authorization': f'Bearer {api_key}'},
                json=payload,
            )
            resp.raise_for_status()
            body = resp.json()
        data = [EmbeddingData(embedding=item['embedding'], index=i) for i, item in enumerate(body.get('data', []))]
        return EmbeddingResponse(data=data, model=model, provider=self.provider, dimensions=dimensions, usage=body.get('usage', {}))

class CohereEmbeddingProvider:
    provider = 'cohere'
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    async def embed(self, texts: list[str], model: str, dimensions: int, input_type: str | None = None) -> EmbeddingResponse:
        api_key = self.api_key or get_settings().cohere_api_key
        if not api_key:
            raise ProviderConfigurationError("cohere embedding provider requires COHERE_API_KEY")
        cohere_input_type = 'search_query' if input_type == 'query' else 'search_document'
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                'https://api.cohere.com/v2/embed',
                headers={'Authorization': f'Bearer {api_key}'},
                json={'model': model, 'texts': texts, 'input_type': cohere_input_type, 'embedding_types': ['float']},
            )
            resp.raise_for_status()
            body = resp.json()
        vectors = body.get('embeddings', {}).get('float') or body.get('embeddings') or []
        data = [EmbeddingData(embedding=v[:dimensions], index=i) for i, v in enumerate(vectors)]
        return EmbeddingResponse(data=data, model=model, provider=self.provider, dimensions=dimensions, usage=body.get('meta', {}).get('billed_units', {}))

RUNPOD_PROVIDERS = {"runpod", "runpod_serverless", "runpod_serverless_or_local"}
OPENAI_COMPATIBLE_PROVIDERS = {"tei", "huggingface_tei", "infinity", "jina", "self_hosted", "openai_compatible_private"}


def _headers(api_key: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _endpoint_url(base_url: str, path: str | None) -> str:
    base = base_url.rstrip("/")
    if not path:
        return base
    normalized_path = path.strip("/")
    if base.endswith(f"/{normalized_path}"):
        return base
    return f"{base}/{normalized_path}"


def _unwrap_endpoint_body(body: Any) -> Any:
    if isinstance(body, dict) and isinstance(body.get("output"), (dict, list)):
        return body["output"]
    return body


def _embedding_payload(provider: str, texts: list[str], model: str, dimensions: int, input_type: str | None) -> dict[str, Any]:
    options: dict[str, Any] = {"dimensions": dimensions}
    if input_type:
        options["inputType"] = input_type
    if provider in RUNPOD_PROVIDERS:
        return {
            "input": {
                "operation": "embeddings",
                "model": model,
                "input": texts,
                "options": options,
            }
        }
    payload: dict[str, Any] = {"model": model, "input": texts, "dimensions": dimensions}
    if input_type:
        payload["input_type"] = input_type
    return payload


def _normalize_embedding_data(body: Any, *, dimensions: int) -> list[EmbeddingData]:
    body = _unwrap_endpoint_body(body)
    if isinstance(body, list):
        return [EmbeddingData(embedding=list(vector)[:dimensions], index=i) for i, vector in enumerate(body)]
    if not isinstance(body, dict):
        raise ProviderConfigurationError("private embedding endpoint returned an unsupported response")
    if "data" in body:
        data: list[EmbeddingData] = []
        for i, item in enumerate(body.get("data") or []):
            if isinstance(item, dict):
                data.append(EmbeddingData(embedding=list(item["embedding"])[:dimensions], index=int(item.get("index", i))))
            else:
                data.append(EmbeddingData(embedding=list(item)[:dimensions], index=i))
        return data
    vectors = body.get("embeddings") or body.get("vectors") or []
    return [EmbeddingData(embedding=list(vector)[:dimensions], index=i) for i, vector in enumerate(vectors)]


def _rerank_payload(provider: str, query: str, documents: list[str], model: str, top_n: int | None) -> dict[str, Any]:
    if provider in RUNPOD_PROVIDERS:
        return {
            "input": {
                "operation": "rerank",
                "model": model,
                "query": query,
                "documents": documents,
                "options": {"topN": top_n},
            }
        }
    payload: dict[str, Any] = {"model": model, "query": query, "documents": documents}
    if top_n is not None:
        payload["top_n"] = top_n
    return payload


def _normalize_rerank_results(body: Any, *, documents_count: int, top_n: int | None) -> list[RerankResult]:
    body = _unwrap_endpoint_body(body)
    raw_results: Any
    if isinstance(body, list):
        raw_results = body
    elif isinstance(body, dict):
        raw_results = body.get("results") or body.get("data") or body.get("rerank") or body.get("scores") or []
    else:
        raise ProviderConfigurationError("private rerank endpoint returned an unsupported response")

    results: list[RerankResult] = []
    for i, item in enumerate(raw_results):
        if isinstance(item, dict):
            index = int(item.get("index", item.get("document_index", i)))
            score = float(item.get("relevance_score", item.get("score", item.get("similarity", 0.0))))
        else:
            index = i
            score = float(item)
        if 0 <= index < documents_count:
            results.append(RerankResult(index=index, relevance_score=score))
    results.sort(key=lambda result: result.relevance_score, reverse=True)
    if top_n:
        results = results[:top_n]
    return results


class GenericEndpointEmbeddingProvider:
    def __init__(
        self,
        provider: str,
        endpoint_url: str,
        api_key: str | None = None,
        *,
        health_status: str = "unknown",
        embedding_path: str | None = None,
    ):
        if not endpoint_url:
            raise ProviderConfigurationError(f"{provider} embedding provider requires an endpoint URL")
        self.provider = provider.strip().lower()
        self.endpoint_url = endpoint_url.rstrip("/")
        self.api_key = api_key
        self.health_status = normalize_health_status(health_status)
        self.embedding_path = embedding_path

    async def embed(self, texts: list[str], model: str, dimensions: int, input_type: str | None = None) -> EmbeddingResponse:
        if not health_allows_routing(self.health_status):
            raise ProviderConfigurationError(f"{self.provider} embedding endpoint health is {self.health_status}; routing disabled")
        path = None if self.provider in RUNPOD_PROVIDERS else (self.embedding_path or "embeddings")
        payload = _embedding_payload(self.provider, texts, model, dimensions, input_type)
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(_endpoint_url(self.endpoint_url, path), headers=_headers(self.api_key), json=payload)
            resp.raise_for_status()
            body = _unwrap_endpoint_body(resp.json())
        data = _normalize_embedding_data(body, dimensions=dimensions)
        response_model = body.get("model", model) if isinstance(body, dict) else model
        usage = body.get("usage", {}) if isinstance(body, dict) else {}
        return EmbeddingResponse(data=data, model=response_model, provider=self.provider, dimensions=dimensions, usage=usage)


class GenericEndpointRerankProvider:
    def __init__(
        self,
        provider: str,
        endpoint_url: str,
        api_key: str | None = None,
        *,
        health_status: str = "unknown",
        rerank_path: str | None = None,
    ):
        if not endpoint_url:
            raise ProviderConfigurationError(f"{provider} rerank provider requires an endpoint URL")
        self.provider = provider.strip().lower()
        self.endpoint_url = endpoint_url.rstrip("/")
        self.api_key = api_key
        self.health_status = normalize_health_status(health_status)
        self.rerank_path = rerank_path

    async def rerank(self, query: str, documents: list[str], model: str, top_n: int | None = None) -> RerankResponse:
        if not health_allows_routing(self.health_status):
            raise ProviderConfigurationError(f"{self.provider} rerank endpoint health is {self.health_status}; routing disabled")
        path = None if self.provider in RUNPOD_PROVIDERS else (self.rerank_path or "rerank")
        payload = _rerank_payload(self.provider, query, documents, model, top_n)
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(_endpoint_url(self.endpoint_url, path), headers=_headers(self.api_key), json=payload)
            resp.raise_for_status()
            body = _unwrap_endpoint_body(resp.json())
        results = _normalize_rerank_results(body, documents_count=len(documents), top_n=top_n)
        response_model = body.get("model", model) if isinstance(body, dict) else model
        return RerankResponse(results=results, model=response_model, provider=self.provider)

def provider_for(provider_name: str, settings: Any | None = None) -> EmbeddingProvider:
    s = settings or get_settings()
    provider = (provider_name or "").strip().lower()
    status = provider_config_status(provider, s)
    if provider == 'hash_mock':
        return HashEmbeddingProvider()
    if not status.configured:
        raise ProviderConfigurationError(status.reason or f"{provider} embedding provider is not configured")
    if provider == 'openai':
        return OpenAIEmbeddingProvider(_setting(s, 'openai_api_key'))
    if provider == 'voyage':
        return VoyageEmbeddingProvider(_setting(s, 'voyage_api_key'))
    if provider == 'cohere':
        return CohereEmbeddingProvider(_setting(s, 'cohere_api_key'))
    if provider in {'jina', 'tei', 'huggingface_tei'}:
        return GenericEndpointEmbeddingProvider(provider, _setting(s, 'tei_endpoint_url') or '')
    if provider in RUNPOD_PROVIDERS:
        return GenericEndpointEmbeddingProvider('runpod', _setting(s, 'runpod_embedding_endpoint_url') or '', _setting(s, 'runpod_api_key'))
    if provider == 'infinity':
        return GenericEndpointEmbeddingProvider('infinity', _setting(s, 'infinity_endpoint_url') or '')
    if provider in {"self_hosted", "openai_compatible_private"}:
        return GenericEndpointEmbeddingProvider(provider, _setting(s, "self_hosted_model_endpoint_url") or '', _setting(s, "self_hosted_model_api_key"))
    raise ProviderConfigurationError(f"unknown embedding provider: {provider_name}")


def provider_for_rerank(provider_name: str, settings: Any | None = None) -> RerankProvider:
    s = settings or get_settings()
    provider = (provider_name or "").strip().lower()
    status = provider_config_status(provider, s)
    if not status.configured:
        raise ProviderConfigurationError(status.reason or f"{provider} rerank provider is not configured")
    if provider in {'jina', 'tei', 'huggingface_tei'}:
        return GenericEndpointRerankProvider(provider, _setting(s, 'tei_endpoint_url') or '')
    if provider in RUNPOD_PROVIDERS:
        return GenericEndpointRerankProvider('runpod', _setting(s, 'runpod_embedding_endpoint_url') or '', _setting(s, 'runpod_api_key'))
    if provider == 'infinity':
        return GenericEndpointRerankProvider('infinity', _setting(s, 'infinity_endpoint_url') or '')
    if provider in {"self_hosted", "openai_compatible_private"}:
        return GenericEndpointRerankProvider(provider, _setting(s, "self_hosted_model_endpoint_url") or '', _setting(s, "self_hosted_model_api_key"))
    raise ProviderConfigurationError(f"unknown rerank provider: {provider_name}")
