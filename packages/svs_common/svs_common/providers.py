from __future__ import annotations
import hashlib, math
from dataclasses import dataclass
from typing import Any
from typing import Protocol
import httpx
from .config import get_settings
from .schemas import EmbeddingData, EmbeddingResponse

class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str], model: str, dimensions: int, input_type: str | None = None) -> EmbeddingResponse: ...

class ProviderConfigurationError(RuntimeError):
    """Raised when a selected provider is not configured for runtime use."""

@dataclass(frozen=True)
class ProviderConfigStatus:
    provider: str
    configured: bool
    required_env: tuple[str, ...] = ()
    reason: str | None = None


def _setting(settings: Any, name: str) -> str | None:
    value = getattr(settings, name, None)
    if value is None:
        return None
    return str(value).strip()


def _status(provider: str, env_names: tuple[str, ...], configured: bool, reason: str | None = None) -> ProviderConfigStatus:
    if configured:
        return ProviderConfigStatus(provider=provider, configured=True, required_env=env_names)
    missing = ", ".join(env_names) if env_names else "provider configuration"
    return ProviderConfigStatus(
        provider=provider,
        configured=False,
        required_env=env_names,
        reason=reason or f"{provider} embedding provider requires {missing}",
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
    if provider in {"jina", "tei"}:
        return _status(provider, ("TEI_ENDPOINT_URL",), bool(_setting(s, "tei_endpoint_url")))
    if provider in {"runpod_serverless_or_local", "runpod"}:
        return _status(provider, ("RUNPOD_EMBEDDING_ENDPOINT_URL",), bool(_setting(s, "runpod_embedding_endpoint_url")))
    if provider == "infinity":
        return _status(provider, ("INFINITY_ENDPOINT_URL",), bool(_setting(s, "infinity_endpoint_url")))
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

class GenericEndpointEmbeddingProvider:
    def __init__(self, provider: str, endpoint_url: str, api_key: str | None = None):
        if not endpoint_url:
            raise ProviderConfigurationError(f"{provider} embedding provider requires an endpoint URL")
        self.provider = provider
        self.endpoint_url = endpoint_url.rstrip('/')
        self.api_key = api_key
    async def embed(self, texts: list[str], model: str, dimensions: int, input_type: str | None = None) -> EmbeddingResponse:
        headers = {'Authorization': f'Bearer {self.api_key}'} if self.api_key else {}
        payload = {'model': model, 'input': texts, 'dimensions': dimensions}
        if input_type:
            payload['input_type'] = input_type
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(f'{self.endpoint_url}/embeddings', headers=headers, json=payload)
            resp.raise_for_status()
            body = resp.json()
        if 'data' in body:
            data = [EmbeddingData(embedding=item['embedding'], index=item.get('index', i)) for i, item in enumerate(body['data'])]
        else:
            data = [EmbeddingData(embedding=v, index=i) for i, v in enumerate(body.get('embeddings') or body.get('vectors') or [])]
        return EmbeddingResponse(data=data, model=body.get('model', model), provider=self.provider, dimensions=dimensions, usage=body.get('usage', {}))

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
    if provider in {'jina', 'tei'}:
        return GenericEndpointEmbeddingProvider(provider, _setting(s, 'tei_endpoint_url') or '')
    if provider in {'runpod_serverless_or_local', 'runpod'}:
        return GenericEndpointEmbeddingProvider('runpod', s.runpod_embedding_endpoint_url, s.runpod_api_key)
    if provider == 'infinity':
        return GenericEndpointEmbeddingProvider('infinity', s.infinity_endpoint_url)
    raise ProviderConfigurationError(f"unknown embedding provider: {provider_name}")
