import asyncio

import pytest

import svs_common.retrieval as retrieval_mod
from svs_common.retrieval import RetrievalService
from svs_common.providers import ProviderConfigurationError
from svs_common.schemas import EmbeddingData, EmbeddingResponse, Principal, SearchRequest
from svs_common.security import build_retrieval_scope


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class _Db:
    def __init__(self, rows):
        self.rows = rows
        self.sql = ""
        self.params = {}

    def execute(self, sql, params):
        self.sql = str(sql)
        self.params = params
        return _Rows(self.rows)


def test_search_embedding_profile_comes_from_indexed_vector_store_chunks():
    service = RetrievalService.__new__(RetrievalService)
    db = _Db([{"embedding_profile_id": "openai_text_embedding_3_small_1536"}])
    principal = Principal(tenant_id="tenant", business_instance_id="biz-dev", max_security_level=5)
    scope = build_retrieval_scope(principal)
    req = SearchRequest(query="proof", vector_store_id="vs_scale", mode="markdown_docs_v1")

    profiles = service._embedding_profiles_for_search(db, scope, req, {"vector_store_id": "vs_scale"})

    assert profiles == ["openai_text_embedding_3_small_1536"]
    assert "c.vector_store_id" in db.sql
    assert db.params["vector_store_id"] == "vs_scale"
    assert db.params["max_lvl"] == 5


class _Provider:
    def __init__(self, provider="openai"):
        self.provider = provider
        self.calls = 0

    async def embed(self, texts, model, dimensions, input_type=None):
        self.calls += 1
        assert input_type == "query"
        return EmbeddingResponse(
            data=[EmbeddingData(embedding=[float(self.calls)] * dimensions, index=0)],
            model=model,
            provider=self.provider,
            dimensions=dimensions,
            usage={},
        )


def test_query_embedding_cache_reuses_same_tenant_profile_query(monkeypatch):
    service = RetrievalService.__new__(RetrievalService)
    service.settings = object()
    provider = _Provider()
    monkeypatch.setattr(retrieval_mod, "provider_for", lambda provider_name, settings=None: provider)
    scope = build_retrieval_scope(Principal(tenant_id="tenant", business_instance_id="biz-dev", max_security_level=5))

    first = asyncio.run(service._query_embedding(scope, "openai_profile", "same query", "openai", "text-embedding-3-small", 3))
    second = asyncio.run(service._query_embedding(scope, "openai_profile", "same query", "openai", "text-embedding-3-small", 3))

    assert provider.calls == 1
    assert first == second == [1.0, 1.0, 1.0]


def test_query_embedding_cache_is_scoped_to_business_instance(monkeypatch):
    service = RetrievalService.__new__(RetrievalService)
    service.settings = object()
    provider = _Provider()
    monkeypatch.setattr(retrieval_mod, "provider_for", lambda provider_name, settings=None: provider)
    scope_a = build_retrieval_scope(Principal(tenant_id="tenant", business_instance_id="biz-a", max_security_level=5))
    scope_b = build_retrieval_scope(Principal(tenant_id="tenant", business_instance_id="biz-b", max_security_level=5))

    first = asyncio.run(service._query_embedding(scope_a, "openai_profile", "same query", "openai", "text-embedding-3-small", 3))
    second = asyncio.run(service._query_embedding(scope_b, "openai_profile", "same query", "openai", "text-embedding-3-small", 3))

    assert provider.calls == 2
    assert first == [1.0, 1.0, 1.0]
    assert second == [2.0, 2.0, 2.0]


def test_query_embedding_cache_keeps_case_distinct(monkeypatch):
    service = RetrievalService.__new__(RetrievalService)
    service.settings = object()
    provider = _Provider()
    monkeypatch.setattr(retrieval_mod, "provider_for", lambda provider_name, settings=None: provider)
    scope = build_retrieval_scope(Principal(tenant_id="tenant", business_instance_id="biz-dev", max_security_level=5))

    first = asyncio.run(service._query_embedding(scope, "openai_profile", "Case Query", "openai", "text-embedding-3-small", 3))
    second = asyncio.run(service._query_embedding(scope, "openai_profile", "case query", "openai", "text-embedding-3-small", 3))

    assert provider.calls == 2
    assert first == [1.0, 1.0, 1.0]
    assert second == [2.0, 2.0, 2.0]


def test_query_embedding_cache_rejects_hash_mock_for_real_profile(monkeypatch):
    service = RetrievalService.__new__(RetrievalService)
    service.settings = object()
    provider = _Provider(provider="hash_mock")
    monkeypatch.setattr(retrieval_mod, "provider_for", lambda provider_name, settings=None: provider)
    scope = build_retrieval_scope(Principal(tenant_id="tenant", business_instance_id="biz-dev", max_security_level=5))

    with pytest.raises(ProviderConfigurationError, match="returned hash_mock vectors"):
        asyncio.run(service._query_embedding(scope, "openai_profile", "same query", "openai", "text-embedding-3-small", 3))
