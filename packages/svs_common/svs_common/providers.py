from __future__ import annotations
import hashlib, math
from typing import Protocol
import httpx
from .config import get_settings
from .schemas import EmbeddingData, EmbeddingResponse

class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str], model: str, dimensions: int) -> EmbeddingResponse: ...

class HashEmbeddingProvider:
    provider = 'hash_mock'
    async def embed(self, texts: list[str], model: str = 'deterministic-dev-hash', dimensions: int = 1536) -> EmbeddingResponse:
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
    async def embed(self, texts: list[str], model: str, dimensions: int) -> EmbeddingResponse:
        s = get_settings()
        if not s.openai_api_key:
            return await HashEmbeddingProvider().embed(texts, 'deterministic-dev-hash', dimensions)
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                'https://api.openai.com/v1/embeddings',
                headers={'Authorization': f'Bearer {s.openai_api_key}'},
                json={'model': model, 'input': texts, 'dimensions': dimensions},
            )
            resp.raise_for_status()
            body = resp.json()
        data = [EmbeddingData(embedding=item['embedding'], index=item['index']) for item in body.get('data', [])]
        return EmbeddingResponse(data=data, model=body.get('model', model), provider=self.provider, dimensions=dimensions, usage=body.get('usage', {}))

class VoyageEmbeddingProvider:
    provider = 'voyage'
    async def embed(self, texts: list[str], model: str, dimensions: int) -> EmbeddingResponse:
        s = get_settings()
        if not s.voyage_api_key:
            return await HashEmbeddingProvider().embed(texts, 'deterministic-dev-hash', dimensions)
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                'https://api.voyageai.com/v1/embeddings',
                headers={'Authorization': f'Bearer {s.voyage_api_key}'},
                json={'model': model, 'input': texts, 'output_dimension': dimensions},
            )
            resp.raise_for_status()
            body = resp.json()
        data = [EmbeddingData(embedding=item['embedding'], index=i) for i, item in enumerate(body.get('data', []))]
        return EmbeddingResponse(data=data, model=model, provider=self.provider, dimensions=dimensions, usage=body.get('usage', {}))

class CohereEmbeddingProvider:
    provider = 'cohere'
    async def embed(self, texts: list[str], model: str, dimensions: int) -> EmbeddingResponse:
        s = get_settings()
        if not s.cohere_api_key:
            return await HashEmbeddingProvider().embed(texts, 'deterministic-dev-hash', dimensions)
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                'https://api.cohere.com/v2/embed',
                headers={'Authorization': f'Bearer {s.cohere_api_key}'},
                json={'model': model, 'texts': texts, 'input_type': 'search_document', 'embedding_types': ['float']},
            )
            resp.raise_for_status()
            body = resp.json()
        vectors = body.get('embeddings', {}).get('float') or body.get('embeddings') or []
        data = [EmbeddingData(embedding=v[:dimensions], index=i) for i, v in enumerate(vectors)]
        return EmbeddingResponse(data=data, model=model, provider=self.provider, dimensions=dimensions, usage=body.get('meta', {}).get('billed_units', {}))

class GenericEndpointEmbeddingProvider:
    def __init__(self, provider: str, endpoint_url: str, api_key: str | None = None):
        self.provider = provider
        self.endpoint_url = endpoint_url.rstrip('/')
        self.api_key = api_key
    async def embed(self, texts: list[str], model: str, dimensions: int) -> EmbeddingResponse:
        headers = {'Authorization': f'Bearer {self.api_key}'} if self.api_key else {}
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(f'{self.endpoint_url}/embeddings', headers=headers, json={'model': model, 'input': texts, 'dimensions': dimensions})
            resp.raise_for_status()
            body = resp.json()
        if 'data' in body:
            data = [EmbeddingData(embedding=item['embedding'], index=item.get('index', i)) for i, item in enumerate(body['data'])]
        else:
            data = [EmbeddingData(embedding=v, index=i) for i, v in enumerate(body.get('embeddings') or body.get('vectors') or [])]
        return EmbeddingResponse(data=data, model=body.get('model', model), provider=self.provider, dimensions=dimensions, usage=body.get('usage', {}))

def provider_for(provider_name: str) -> EmbeddingProvider:
    s = get_settings()
    if provider_name == 'openai':
        return OpenAIEmbeddingProvider()
    if provider_name == 'voyage':
        return VoyageEmbeddingProvider()
    if provider_name == 'cohere':
        return CohereEmbeddingProvider()
    if provider_name in {'jina', 'tei'} and s.tei_endpoint_url:
        return GenericEndpointEmbeddingProvider(provider_name, s.tei_endpoint_url)
    if provider_name in {'runpod_serverless_or_local', 'runpod'} and s.runpod_embedding_endpoint_url:
        return GenericEndpointEmbeddingProvider('runpod', s.runpod_embedding_endpoint_url, s.runpod_api_key)
    if provider_name == 'infinity' and s.infinity_endpoint_url:
        return GenericEndpointEmbeddingProvider('infinity', s.infinity_endpoint_url)
    return HashEmbeddingProvider()
