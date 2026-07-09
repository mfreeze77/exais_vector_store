from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from svs_api import main as api_main
from svs_common.provider_probe import endpoint_response_payload, normalize_endpoint_payload
from svs_common.providers import (
    GenericEndpointEmbeddingProvider,
    GenericEndpointRerankProvider,
    ProviderConfigurationError,
)
from svs_common.schemas import ModelEndpointRequest, ModelEndpointResponse, Principal, RerankRequest, RerankResponse, RerankResult
import svs_common.providers as providers_mod
from svs_model_gateway import main as gateway_main


class _Rows:
    def __init__(self, row=None, rows=None):
        self.row = row
        self.rows = rows or []

    def mappings(self):
        return self

    def first(self):
        return self.row

    def all(self):
        return self.rows


class _Db:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls = []
        self.committed = False

    def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params or {}))
        if self.results:
            result = self.results.pop(0)
            if isinstance(result, list):
                return _Rows(rows=result)
            return _Rows(row=result)
        return _Rows()

    def commit(self):
        self.committed = True


def _principal() -> Principal:
    return Principal(tenant_id="tenant", business_instance_id="biz", user_id="user", scopes=["models:read", "models:write"])


def _install_fake_async_client(monkeypatch: pytest.MonkeyPatch, body):
    captured = {}

    class _FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return body

    class _FakeAsyncClient:
        def __init__(self, *, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return _FakeResponse()

    monkeypatch.setattr(providers_mod.httpx, "AsyncClient", _FakeAsyncClient)
    return captured


def test_model_endpoint_metadata_exposes_private_endpoint_contract_without_live_proof():
    req = ModelEndpointRequest(
        name="qwen3-embedding-4b-private-us",
        provider="runpod_serverless_or_local",
        kind="embedding",
        base_url="https://api.runpod.ai/v2/<endpoint-id>/runsync",
        model="Qwen/Qwen3-Embedding-4B",
        dimensions=2560,
        supports=["embeddings"],
        privacy="private_gpu",
        security_max_level=5,
        health_status="failed",
        p95_latency_ms=950,
        region="us",
        model_revision="rev-2026-07-09",
        auth_secret_ref="envref://RUNPOD_API_KEY",
    )

    stored = normalize_endpoint_payload(req.model_dump())
    response = ModelEndpointResponse(**endpoint_response_payload({**stored, "id": "mdl_private"}))

    assert response.status == "fallback"
    assert response.health_status == "failed"
    assert response.p95_latency_ms == 950
    assert response.security_max_level == 5
    assert response.region == "us"
    assert response.model_revision == "rev-2026-07-09"
    assert response.auth_secret_ref == "envref://RUNPOD_API_KEY"
    assert response.routing_state == "fallback"
    assert response.config["live_credential_proof"] is False
    assert "RUNPOD_API_KEY" in response.auth_secret_ref
    assert "sk-" not in str(response.model_dump())


def test_model_endpoint_routes_flatten_metadata_and_mark_failed_health_fallback():
    db = _Db()
    req = ModelEndpointRequest(
        name="qwen3-private",
        provider="runpod_serverless_or_local",
        kind="embedding",
        base_url="https://api.runpod.ai/v2/endpoint/runsync",
        model="Qwen/Qwen3-Embedding-4B",
        dimensions=2560,
        supports=["embeddings"],
        privacy="private_gpu",
        security_max_level=5,
        health_status="failed",
        region="us",
        model_revision="rev-2026-07-09",
        auth_secret_ref="envref://RUNPOD_API_KEY",
    )

    response = api_main.create_model_endpoint(req, principal=_principal(), db=db)

    assert response.status == "fallback"
    assert response.health_status == "failed"
    assert response.routing_state == "fallback"
    assert response.region == "us"
    assert response.config["auth_secret_ref"] == "envref://RUNPOD_API_KEY"
    assert response.config["live_credential_proof"] is False
    assert db.committed is True
    assert db.calls[0][1]["status"] == "fallback"


def test_model_endpoint_request_rejects_inline_secret_values():
    with pytest.raises(ValidationError):
        ModelEndpointRequest(
            name="bad-private-endpoint",
            provider="runpod_serverless_or_local",
            auth_secret_ref="inline=value",
        )

    with pytest.raises(ValidationError):
        ModelEndpointRequest(
            name="bad-private-endpoint",
            provider="runpod_serverless_or_local",
            auth_secret_ref="not-a-reference",
        )

    with pytest.raises(ValidationError):
        ModelEndpointRequest(
            name="bad-private-endpoint",
            provider="runpod_serverless_or_local",
            config={"api_key": "inline=value"},
        )


def test_runpod_embedding_adapter_normalizes_runsync_response(monkeypatch: pytest.MonkeyPatch):
    captured = _install_fake_async_client(
        monkeypatch,
        {
            "output": {
                "model": "Qwen/Qwen3-Embedding-4B",
                "data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}],
                "usage": {"items": 1},
            }
        },
    )
    provider = GenericEndpointEmbeddingProvider("runpod", "https://api.runpod.ai/v2/abc/runsync")

    response = asyncio.run(provider.embed(["chunk one"], "Qwen/Qwen3-Embedding-4B", 2, input_type="document"))

    assert captured["url"] == "https://api.runpod.ai/v2/abc/runsync"
    assert captured["headers"] == {}
    assert captured["json"] == {
        "input": {
            "operation": "embeddings",
            "model": "Qwen/Qwen3-Embedding-4B",
            "input": ["chunk one"],
            "options": {"dimensions": 2, "inputType": "document"},
        }
    }
    assert response.model == "Qwen/Qwen3-Embedding-4B"
    assert response.provider == "runpod"
    assert response.dimensions == 2
    assert response.data[0].embedding == [0.1, 0.2]
    assert response.usage == {"items": 1}


def test_infinity_rerank_adapter_normalizes_gateway_contract(monkeypatch: pytest.MonkeyPatch):
    captured = _install_fake_async_client(
        monkeypatch,
        {
            "model": "BAAI/bge-reranker-v2-m3",
            "results": [
                {"index": 0, "score": 0.2},
                {"index": 1, "score": 0.95},
            ],
        },
    )
    provider = GenericEndpointRerankProvider("infinity", "http://infinity.internal:7997")

    response = asyncio.run(provider.rerank("alpha", ["beta", "alpha beta"], "BAAI/bge-reranker-v2-m3", top_n=1))

    assert captured["url"] == "http://infinity.internal:7997/rerank"
    assert captured["json"] == {
        "model": "BAAI/bge-reranker-v2-m3",
        "query": "alpha",
        "documents": ["beta", "alpha beta"],
        "top_n": 1,
    }
    assert response.provider == "infinity"
    assert response.model == "BAAI/bge-reranker-v2-m3"
    assert [(item.index, item.relevance_score) for item in response.results] == [(1, 0.95)]


def test_failed_private_endpoint_health_disables_adapter_routing():
    provider = GenericEndpointEmbeddingProvider("tei", "http://tei.internal:8080", health_status="failed")

    with pytest.raises(ProviderConfigurationError, match="routing disabled"):
        asyncio.run(provider.embed(["text"], "BAAI/bge-m3", 1024))


def test_gateway_rerank_uses_private_adapter_when_explicit_provider_selected(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    class _FakeRerankProvider:
        async def rerank(self, query, documents, model, top_n=None):
            captured.update({"query": query, "documents": documents, "model": model, "top_n": top_n})
            return RerankResponse(
                results=[RerankResult(index=1, relevance_score=0.88)],
                model=model,
                provider="infinity",
            )

    monkeypatch.setattr(gateway_main, "provider_for_rerank", lambda provider_name: _FakeRerankProvider())

    response = asyncio.run(
        gateway_main.rerank(
            RerankRequest(
                query="alpha",
                documents=["beta", "alpha beta"],
                provider="infinity",
                model="BAAI/bge-reranker-v2-m3",
                top_n=1,
            )
        )
    )

    assert captured == {
        "query": "alpha",
        "documents": ["beta", "alpha beta"],
        "model": "BAAI/bge-reranker-v2-m3",
        "top_n": 1,
    }
    assert response.provider == "infinity"
    assert response.results[0].index == 1


def test_gateway_rerank_falls_back_when_private_adapter_runtime_fails(monkeypatch: pytest.MonkeyPatch):
    class _FailingRerankProvider:
        async def rerank(self, query, documents, model, top_n=None):
            raise providers_mod.httpx.ConnectError("endpoint unavailable")

    monkeypatch.setattr(gateway_main, "provider_for_rerank", lambda provider_name: _FailingRerankProvider())

    response = asyncio.run(
        gateway_main.rerank(
            RerankRequest(
                query="alpha",
                documents=["beta", "alpha beta"],
                provider="infinity",
                model="BAAI/bge-reranker-v2-m3",
                top_n=1,
            )
        )
    )

    assert response.provider == "local"
    assert response.model == "lexical-overlap-fallback"
    assert [(item.index, item.relevance_score) for item in response.results] == [(1, 1.0)]
