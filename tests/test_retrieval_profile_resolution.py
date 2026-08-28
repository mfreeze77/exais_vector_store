import asyncio
import inspect
import json
from types import SimpleNamespace

import pytest

import svs_common.retrieval as retrieval_mod
from svs_common.model_registry import retrieval_profiles, vectorization_modes
from svs_common.openai_compat import file_attribute_payload_key
from svs_common.retrieval import RetrievalService, ensure_retrieval_answer_citation_integrity
from svs_common.providers import ProviderConfigurationError
from svs_common.schemas import ChunkRecord, ContextCitation, ContextPackRequest, ContextPackResponse, EmbeddingData, EmbeddingResponse, Principal, RetrievalAnswerRequest, SearchRequest, SearchResponse
from svs_common.security import build_qdrant_filter, build_retrieval_scope


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


class _AuditDb:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params):
        self.calls.append((str(sql), params))
        return _Rows([])


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


def test_search_embedding_profile_filters_by_file_attributes():
    service = RetrievalService.__new__(RetrievalService)
    db = _Db([{"embedding_profile_id": "openai_text_embedding_3_small_1536"}])
    principal = Principal(tenant_id="tenant", business_instance_id="biz-dev", max_security_level=5)
    scope = build_retrieval_scope(principal)
    req = SearchRequest(query="proof", vector_store_id="vs_scale", mode="markdown_docs_v1")

    profiles = service._embedding_profiles_for_search(
        db,
        scope,
        req,
        {"vector_store_id": "vs_scale", "file_attribute_filters": {"region": "us"}},
    )

    assert profiles == ["openai_text_embedding_3_small_1536"]
    assert "JOIN vector_store_files vsf" in db.sql
    assert "vsf.attributes @> CAST(:profile_file_attr_exact AS jsonb)" in db.sql
    assert db.params["profile_file_attr_exact"] == '{"region":"us"}'


def test_search_embedding_profile_does_not_fallback_for_empty_vector_store_scope():
    service = RetrievalService.__new__(RetrievalService)
    db = _Db([])
    principal = Principal(tenant_id="tenant", business_instance_id="biz-dev", max_security_level=5)
    scope = build_retrieval_scope(principal)
    req = SearchRequest(query="proof", vector_store_id="vs_empty", mode="markdown_docs_v1")

    profiles = service._embedding_profiles_for_search(db, scope, req, {"vector_store_id": "vs_empty"})

    assert profiles == []
    assert "c.vector_store_id" in db.sql
    assert db.params["vector_store_id"] == "vs_empty"


def test_qdrant_filter_supports_file_attribute_alternatives():
    scope = build_retrieval_scope(Principal(tenant_id="tenant", business_instance_id="biz-dev", max_security_level=5))

    filt = build_qdrant_filter(
        scope,
        {
            "vector_store_id": "vs_scale",
            "file_attribute_filters": {"region": "us"},
            "file_attribute_filter_any": [
                {"category": "blog"},
                {"category": "announcement"},
            ],
            "file_attribute_ranges": [
                {"key": "created_at", "op": "gte", "value": "2026-01-01"},
            ],
        },
    )

    category_key = file_attribute_payload_key("category")

    assert {"key": file_attribute_payload_key("region"), "match": {"value": "us"}} in filt["must"]
    assert filt["should"] == [
        {"must": [{"key": category_key, "match": {"value": "blog"}}]},
        {"must": [{"key": category_key, "match": {"value": "announcement"}}]},
    ]


def test_qdrant_filter_supports_file_attribute_negation():
    scope = build_retrieval_scope(Principal(tenant_id="tenant", business_instance_id="biz-dev", max_security_level=5))

    filt = build_qdrant_filter(
        scope,
        {
            "file_attribute_not_filters": [{"key": "region", "value": "us"}],
            "file_attribute_not_any": [{"key": "category", "values": ["blog", "announcement"]}],
        },
    )

    assert filt["must_not"] == [
        {"key": file_attribute_payload_key("region"), "match": {"value": "us"}},
        {"key": file_attribute_payload_key("category"), "match": {"value": "blog"}},
        {"key": file_attribute_payload_key("category"), "match": {"value": "announcement"}},
    ]


def test_qdrant_filter_supports_numeric_file_attribute_ranges_only():
    scope = build_retrieval_scope(Principal(tenant_id="tenant", business_instance_id="biz-dev", max_security_level=5))

    filt = build_qdrant_filter(
        scope,
        {
            "file_attribute_ranges": [
                {"key": "priority", "op": "gte", "value": 5},
                {"key": "created_at", "op": "gte", "value": "2026-01-01"},
            ],
        },
    )

    assert {
        "key": file_attribute_payload_key("priority"),
        "range": {"gte": 5},
    } in filt["must"]
    assert not any(item.get("key") == file_attribute_payload_key("created_at") for item in filt["must"])


def test_search_embedding_profile_filters_by_file_attribute_alternatives():
    service = RetrievalService.__new__(RetrievalService)
    db = _Db([{"embedding_profile_id": "openai_text_embedding_3_small_1536"}])
    principal = Principal(tenant_id="tenant", business_instance_id="biz-dev", max_security_level=5)
    scope = build_retrieval_scope(principal)
    req = SearchRequest(query="proof", vector_store_id="vs_scale", mode="markdown_docs_v1")

    profiles = service._embedding_profiles_for_search(
        db,
        scope,
        req,
        {
            "vector_store_id": "vs_scale",
            "file_attribute_filter_any": [
                {"category": "blog"},
                {"category": "announcement"},
            ],
            "file_attribute_ranges": [
                {"key": "created_at", "op": "gte", "value": "2026-01-01"},
            ],
        },
    )

    assert profiles == ["openai_text_embedding_3_small_1536"]
    assert "JOIN vector_store_files vsf" in db.sql
    assert "vsf.attributes @> CAST(:profile_file_attr_any_0 AS jsonb)" in db.sql
    assert "OR vsf.attributes @> CAST(:profile_file_attr_any_1 AS jsonb)" in db.sql
    assert db.params["profile_file_attr_any_0"] == '{"category":"blog"}'
    assert db.params["profile_file_attr_any_1"] == '{"category":"announcement"}'


def test_search_embedding_profile_filters_by_file_attribute_ranges():
    service = RetrievalService.__new__(RetrievalService)
    db = _Db([{"embedding_profile_id": "openai_text_embedding_3_small_1536"}])
    principal = Principal(tenant_id="tenant", business_instance_id="biz-dev", max_security_level=5)
    scope = build_retrieval_scope(principal)
    req = SearchRequest(query="proof", vector_store_id="vs_scale", mode="markdown_docs_v1")

    profiles = service._embedding_profiles_for_search(
        db,
        scope,
        req,
        {
            "vector_store_id": "vs_scale",
            "file_attribute_ranges": [
                {"key": "created_at", "op": "gte", "value": "2026-01-01"},
                {"key": "created_at", "op": "lt", "value": "2026-02-01"},
                {"key": "priority", "op": "gte", "value": 5},
            ],
        },
    )

    assert profiles == ["openai_text_embedding_3_small_1536"]
    assert "JOIN vector_store_files vsf" in db.sql
    assert "jsonb_typeof(vsf.attributes -> :profile_file_attr_range_0_key) = 'string'" in db.sql
    assert "vsf.attributes ->> :profile_file_attr_range_0_key ELSE NULL END >= :profile_file_attr_range_0_value" in db.sql
    assert "jsonb_typeof(vsf.attributes -> :profile_file_attr_range_2_key) = 'number'" in db.sql
    assert "(vsf.attributes ->> :profile_file_attr_range_2_key)::numeric ELSE NULL END >= :profile_file_attr_range_2_value" in db.sql
    assert db.params["profile_file_attr_range_0_key"] == "created_at"
    assert db.params["profile_file_attr_range_0_value"] == "2026-01-01"
    assert db.params["profile_file_attr_range_2_key"] == "priority"
    assert db.params["profile_file_attr_range_2_value"] == 5


def test_search_embedding_profile_filters_by_file_attribute_negation():
    service = RetrievalService.__new__(RetrievalService)
    db = _Db([{"embedding_profile_id": "openai_text_embedding_3_small_1536"}])
    principal = Principal(tenant_id="tenant", business_instance_id="biz-dev", max_security_level=5)
    scope = build_retrieval_scope(principal)
    req = SearchRequest(query="proof", vector_store_id="vs_scale", mode="markdown_docs_v1")

    profiles = service._embedding_profiles_for_search(
        db,
        scope,
        req,
        {
            "vector_store_id": "vs_scale",
            "file_attribute_not_filters": [{"key": "region", "value": "us"}],
            "file_attribute_not_any": [{"key": "category", "values": ["blog", "announcement"]}],
        },
    )

    assert profiles == ["openai_text_embedding_3_small_1536"]
    assert "JOIN vector_store_files vsf" in db.sql
    assert "vsf.attributes ? :profile_file_attr_not_0_key" in db.sql
    assert "NOT (vsf.attributes @> CAST(:profile_file_attr_not_0_value AS jsonb))" in db.sql
    assert "vsf.attributes ? :profile_file_attr_not_any_0_key" in db.sql
    assert "NOT (vsf.attributes @> CAST(:profile_file_attr_not_any_0_value_0 AS jsonb)" in db.sql
    assert "OR vsf.attributes @> CAST(:profile_file_attr_not_any_0_value_1 AS jsonb))" in db.sql
    assert db.params["profile_file_attr_not_0_key"] == "region"
    assert db.params["profile_file_attr_not_0_value"] == '{"region":"us"}'
    assert db.params["profile_file_attr_not_any_0_key"] == "category"
    assert db.params["profile_file_attr_not_any_0_value_0"] == '{"category":"blog"}'
    assert db.params["profile_file_attr_not_any_0_value_1"] == '{"category":"announcement"}'


def test_postgres_sparse_search_filters_by_file_attribute_alternatives():
    service = RetrievalService.__new__(RetrievalService)
    db = _Db([])
    scope = build_retrieval_scope(Principal(tenant_id="tenant", business_instance_id="biz-dev", max_security_level=5))

    service._postgres_sparse_search(
        db,
        scope,
        "proof",
        {
            "vector_store_id": "vs_scale",
            "file_attribute_filter_any": [
                {"category": "blog"},
                {"category": "announcement"},
            ],
        },
        10,
    )

    assert "JOIN vector_store_files vsf" in db.sql
    assert "vsf.attributes @> CAST(:sparse_file_attr_any_0 AS jsonb)" in db.sql
    assert "OR vsf.attributes @> CAST(:sparse_file_attr_any_1 AS jsonb)" in db.sql
    assert db.params["sparse_file_attr_any_0"] == '{"category":"blog"}'
    assert db.params["sparse_file_attr_any_1"] == '{"category":"announcement"}'


def test_postgres_sparse_search_uses_phrase_aware_websearch_query():
    service = RetrievalService.__new__(RetrievalService)
    db = _Db([])
    scope = build_retrieval_scope(Principal(tenant_id="tenant", business_instance_id="biz-dev", max_security_level=5))

    service._postgres_sparse_search(
        db,
        scope,
        '"marker warmup" OR retries',
        {"vector_store_id": "vs_scale"},
        10,
    )

    assert "ts_rank_cd(search_vector, websearch_to_tsquery('english', :query)) AS score" in db.sql
    assert "c.search_vector @@ websearch_to_tsquery('english', :query)" in db.sql
    assert "plainto_tsquery" not in db.sql
    assert db.params["query"] == '"marker warmup" OR retries'
    assert db.params["vector_store_id"] == "vs_scale"


def test_postgres_sparse_search_filters_by_file_attribute_ranges():
    service = RetrievalService.__new__(RetrievalService)
    db = _Db([])
    scope = build_retrieval_scope(Principal(tenant_id="tenant", business_instance_id="biz-dev", max_security_level=5))

    service._postgres_sparse_search(
        db,
        scope,
        "proof",
        {
            "vector_store_id": "vs_scale",
            "file_attribute_ranges": [
                {"key": "created_at", "op": "gte", "value": "2026-01-01"},
            ],
        },
        10,
    )

    assert "JOIN vector_store_files vsf" in db.sql
    assert "jsonb_typeof(vsf.attributes -> :sparse_file_attr_range_0_key) = 'string'" in db.sql
    assert "vsf.attributes ->> :sparse_file_attr_range_0_key ELSE NULL END >= :sparse_file_attr_range_0_value" in db.sql
    assert db.params["sparse_file_attr_range_0_key"] == "created_at"
    assert db.params["sparse_file_attr_range_0_value"] == "2026-01-01"


def test_hydration_filters_by_file_attribute_alternatives():
    service = RetrievalService.__new__(RetrievalService)
    db = _Db([])
    principal = Principal(tenant_id="tenant", business_instance_id="biz-dev", max_security_level=5)

    service._hydrate_and_acl(
        db,
        principal,
        [{"id": "chk_1", "payload": {"chunk_id": "chk_1"}, "score": 0.9}],
        10,
        {
            "vector_store_id": "vs_scale",
            "file_attribute_filter_any": [
                {"category": "blog"},
                {"category": "announcement"},
            ],
            "file_attribute_ranges": [
                {"key": "created_at", "op": "gte", "value": "2026-01-01"},
            ],
        },
    )

    assert "JOIN vector_store_files vsf" in db.sql
    assert "vsf.attributes @> CAST(:hydrate_file_attr_any_0 AS jsonb)" in db.sql
    assert "OR vsf.attributes @> CAST(:hydrate_file_attr_any_1 AS jsonb)" in db.sql
    assert db.params["hydrate_file_attr_any_0"] == '{"category":"blog"}'
    assert db.params["hydrate_file_attr_any_1"] == '{"category":"announcement"}'


def test_hydration_filters_by_file_attribute_ranges():
    service = RetrievalService.__new__(RetrievalService)
    db = _Db([])
    principal = Principal(tenant_id="tenant", business_instance_id="biz-dev", max_security_level=5)

    service._hydrate_and_acl(
        db,
        principal,
        [{"id": "chk_1", "payload": {"chunk_id": "chk_1"}, "score": 0.9}],
        10,
        {
            "vector_store_id": "vs_scale",
            "file_attribute_ranges": [
                {"key": "priority", "op": "gte", "value": 5},
            ],
        },
    )

    assert "JOIN vector_store_files vsf" in db.sql
    assert "jsonb_typeof(vsf.attributes -> :hydrate_file_attr_range_0_key) = 'number'" in db.sql
    assert "(vsf.attributes ->> :hydrate_file_attr_range_0_key)::numeric ELSE NULL END >= :hydrate_file_attr_range_0_value" in db.sql
    assert db.params["hydrate_file_attr_range_0_key"] == "priority"
    assert db.params["hydrate_file_attr_range_0_value"] == 5


def test_hydration_post_acl_filters_security_groups_and_roles():
    service = RetrievalService.__new__(RetrievalService)
    principal = Principal(
        tenant_id="tenant",
        business_instance_id="biz-dev",
        groups=["engineering"],
        roles=["reader"],
        max_security_level=3,
    )
    rows = [
        {
            "id": "chk_allowed",
            "document_id": "doc_allowed",
            "document_version_id": "dv_allowed",
            "file_id": "file_allowed",
            "title": "Allowed doc",
            "filename": "allowed.md",
            "source_uri": None,
            "ordinal": 1,
            "text": "Allowed candidate.",
            "heading_path": [],
            "page_start": None,
            "page_end": None,
            "metadata": {},
            "security_level": 3,
            "classification": "tenant_private",
            "allowed_groups": ["engineering"],
            "allowed_roles": ["reader"],
        },
        {
            "id": "chk_group_blocked",
            "document_id": "doc_group_blocked",
            "document_version_id": "dv_group_blocked",
            "file_id": "file_group_blocked",
            "title": "Group blocked doc",
            "filename": "group-blocked.md",
            "source_uri": None,
            "ordinal": 2,
            "text": "Blocked by group.",
            "heading_path": [],
            "page_start": None,
            "page_end": None,
            "metadata": {},
            "security_level": 1,
            "classification": "tenant_private",
            "allowed_groups": ["finance"],
            "allowed_roles": [],
        },
        {
            "id": "chk_role_blocked",
            "document_id": "doc_role_blocked",
            "document_version_id": "dv_role_blocked",
            "file_id": "file_role_blocked",
            "title": "Role blocked doc",
            "filename": "role-blocked.md",
            "source_uri": None,
            "ordinal": 3,
            "text": "Blocked by role.",
            "heading_path": [],
            "page_start": None,
            "page_end": None,
            "metadata": {},
            "security_level": 1,
            "classification": "tenant_private",
            "allowed_groups": [],
            "allowed_roles": ["admin"],
        },
        {
            "id": "chk_level_blocked",
            "document_id": "doc_level_blocked",
            "document_version_id": "dv_level_blocked",
            "file_id": "file_level_blocked",
            "title": "Level blocked doc",
            "filename": "level-blocked.md",
            "source_uri": None,
            "ordinal": 4,
            "text": "Blocked by security level.",
            "heading_path": [],
            "page_start": None,
            "page_end": None,
            "metadata": {},
            "security_level": 5,
            "classification": "tenant_private",
            "allowed_groups": [],
            "allowed_roles": [],
        },
    ]
    db = _Db(rows)

    chunks = service._hydrate_and_acl(
        db,
        principal,
        [
            {"id": row["id"], "payload": {"chunk_id": row["id"]}, "score": 0.9 - (index * 0.1)}
            for index, row in enumerate(rows)
        ],
        10,
        {},
    )

    assert [chunk.id for chunk in chunks] == ["chk_allowed"]
    assert "c.security_level <= :max_lvl" in db.sql
    assert db.params["tenant_id"] == "tenant"
    assert db.params["biz_id"] == "biz-dev"
    assert db.params["max_lvl"] == 3


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


def test_default_secure_retrieval_profile_declares_local_reranker():
    profile = retrieval_profiles()["hybrid_rrf_secure_v2"]

    assert profile["reranker"] == "local_lexical_overlap_v1"
    assert profile["rerank_candidate_top_k"] >= 10
    assert profile["rerank_weight"] > profile["rerank_fusion_weight"]
    assert profile["diversity"] == "lexical_mmr_v1"
    assert 0.0 < profile["diversity_lambda"] <= 1.0


def test_vectorization_modes_reference_defined_retrieval_profiles():
    profiles = retrieval_profiles()
    missing = {
        mode_id: mode["retrieval_profile"]
        for mode_id, mode in vectorization_modes().items()
        if mode.get("retrieval_profile") and mode["retrieval_profile"] not in profiles
    }

    assert missing == {}


def test_multimodal_retrieval_profiles_are_resolvable_and_safe():
    profiles = retrieval_profiles()

    for profile_id in ("hybrid_multimodal_pdf_v1", "hybrid_multimodal_secure_v1"):
        profile = profiles[profile_id]
        assert profile["fusion"] == "reciprocal_rank_fusion"
        assert profile["reranker"] == "local_lexical_overlap_v1"
        assert profile["diversity"] == "lexical_mmr_v1"
        assert 0.0 < profile["diversity_lambda"] <= 1.0
        assert profile["rerank_candidate_top_k"] >= profile["context_top_k"]
        assert profile["require_post_acl_check"] is True
        assert profile["require_citations"] is True
        assert profile["output_guard"] == "pii_secret_citation_guard_v1"

    assert profiles["hybrid_multimodal_pdf_v1"]["expand_parent_sections"] is True
    assert profiles["hybrid_multimodal_pdf_v1"]["require_page_citations"] is True
    assert profiles["hybrid_multimodal_secure_v1"]["require_pre_filter"] is True


def test_profile_rerank_promotes_query_relevant_chunk():
    service = RetrievalService.__new__(RetrievalService)
    profile = {
        "reranker": "local_lexical_overlap_v1",
        "rerank_candidate_top_k": 10,
        "rerank_weight": 0.9,
        "rerank_fusion_weight": 0.1,
        "rerank_exact_phrase_bonus": 0.2,
    }
    high_fusion = ChunkRecord(
        id="chk_high",
        document_id="doc_high",
        ordinal=0,
        text="Generic platform notes without the requested terms.",
        score=1.0,
        citation={"type": "file_citation", "index": 0, "file_id": "file_high", "filename": "high.md"},
    )
    exact_match = ChunkRecord(
        id="chk_exact",
        document_id="doc_exact",
        ordinal=1,
        text="The alpha citation marker answer appears in this source.",
        score=0.05,
        citation={"type": "file_citation", "index": 0, "file_id": "file_exact", "filename": "exact.md"},
    )

    reranked, audit = asyncio.run(service._rerank_chunks(
        [high_fusion, exact_match],
        "alpha citation marker",
        profile,
        top_k=1,
    ))

    assert [chunk.id for chunk in reranked] == ["chk_exact", "chk_high"]
    assert audit["enabled"] is True
    assert audit["reranker"] == "local_lexical_overlap_v1"
    assert reranked[0].source == "hybrid_rrf_rerank"
    assert reranked[0].citation["reranker"] == "local_lexical_overlap_v1"
    assert reranked[0].citation["rerank_score"] > reranked[1].citation["rerank_score"]
    assert reranked[0].annotations == [{
        "type": "file_citation",
        "index": 0,
        "file_id": "file_exact",
        "filename": "exact.md",
    }]


def test_rerank_mmr_diversity_promotes_distinct_evidence_after_top_candidate():
    service = RetrievalService.__new__(RetrievalService)
    candidates = [
        ChunkRecord(
            id="chk_primary",
            document_id="doc_primary",
            ordinal=0,
            text="alpha retry timeout marker warmup endpoint citation source",
            score=1.0,
            citation={"type": "file_citation", "index": 0, "file_id": "file_primary", "filename": "primary.md"},
        ),
        ChunkRecord(
            id="chk_duplicate",
            document_id="doc_duplicate",
            ordinal=1,
            text="alpha retry timeout marker warmup endpoint citation source duplicate details",
            score=0.99,
            citation={"type": "file_citation", "index": 0, "file_id": "file_duplicate", "filename": "duplicate.md"},
        ),
        ChunkRecord(
            id="chk_distinct",
            document_id="doc_distinct",
            ordinal=2,
            text="alpha billing escalation owner source for customer invoice policy",
            score=0.92,
            citation={"type": "file_citation", "index": 0, "file_id": "file_distinct", "filename": "distinct.md"},
        ),
    ]

    reranked, audit = service._apply_rerank_scores(
        candidates,
        [],
        [1.0, 0.98, 0.92],
        reranker="local_lexical_overlap_v1",
        reranker_provider="local",
        reranker_model="local_lexical_overlap_v1",
        rerank_weight=1.0,
        fusion_weight=0.0,
        top_k=2,
        profile={"diversity": "lexical_mmr_v1", "diversity_lambda": 0.55},
    )

    assert [chunk.id for chunk in reranked[:3]] == ["chk_primary", "chk_distinct", "chk_duplicate"]
    assert audit["diversity"] == {
        "enabled": True,
        "method": "lexical_mmr_v1",
        "lambda": 0.55,
        "candidate_count": 3,
        "selected_count": 2,
        "result_count": 2,
    }
    assert reranked[0].citation["diversity_rank"] == 1
    assert reranked[1].citation["diversity_rank"] == 2
    assert reranked[1].citation["diversity_method"] == "lexical_mmr_v1"
    assert reranked[1].citation["diversity_similarity"] < reranked[2].citation.get("diversity_similarity", 1.0)
    assert "diversity_rank" not in reranked[2].citation
    assert set(reranked[1].annotations[0]) == {"type", "index", "file_id", "filename"}


def test_rerank_mmr_diversity_disabled_preserves_reranked_order_and_audit_shape():
    service = RetrievalService.__new__(RetrievalService)
    candidates = [
        ChunkRecord(id="chk_a", document_id="doc_a", ordinal=0, text="alpha answer", score=1.0),
        ChunkRecord(id="chk_b", document_id="doc_b", ordinal=1, text="alpha answer duplicate", score=0.9),
        ChunkRecord(id="chk_c", document_id="doc_c", ordinal=2, text="distinct beta answer", score=0.8),
    ]

    reranked, audit = service._apply_rerank_scores(
        candidates,
        [],
        [1.0, 0.9, 0.8],
        reranker="local_lexical_overlap_v1",
        reranker_provider="local",
        reranker_model="local_lexical_overlap_v1",
        rerank_weight=1.0,
        fusion_weight=0.0,
        top_k=2,
        profile={"diversity": "disabled"},
    )

    assert [chunk.id for chunk in reranked] == ["chk_a", "chk_b", "chk_c"]
    assert audit == {
        "enabled": True,
        "reranker": "local_lexical_overlap_v1",
        "candidate_count": 3,
        "result_count": 2,
        "rerank_weight": 1.0,
        "fusion_weight": 0.0,
        "reranker_provider": "local",
        "reranker_model": "local_lexical_overlap_v1",
        "reranker_strategy": "candidate_idf_phrase_v1",
    }


def test_local_lexical_rerank_uses_candidate_idf_for_discriminating_terms():
    service = RetrievalService.__new__(RetrievalService)
    profile = {
        "reranker": "local_lexical_overlap_v1",
        "rerank_candidate_top_k": 10,
        "rerank_weight": 0.95,
        "rerank_fusion_weight": 0.05,
        "rerank_exact_phrase_bonus": 0.1,
    }
    common_only = ChunkRecord(
        id="chk_common",
        document_id="doc_common",
        ordinal=0,
        text="alpha beta general policy alpha beta general notes",
        score=1.0,
        citation={"type": "file_citation", "index": 0, "file_id": "file_common", "filename": "common.md"},
    )
    discriminating = ChunkRecord(
        id="chk_rare",
        document_id="doc_rare",
        ordinal=1,
        text="alpha beta critical-retention exception policy",
        score=0.05,
        citation={"type": "file_citation", "index": 0, "file_id": "file_rare", "filename": "rare.md"},
    )

    scores = service._local_lexical_rerank_scores(
        "alpha beta critical retention",
        [common_only.text, discriminating.text],
        profile,
    )
    reranked, audit = asyncio.run(service._rerank_chunks(
        [common_only, discriminating],
        "alpha beta critical retention",
        profile,
        top_k=1,
    ))

    assert scores[1] > scores[0]
    assert [chunk.id for chunk in reranked] == ["chk_rare", "chk_common"]
    assert audit["reranker_strategy"] == "candidate_idf_phrase_v1"
    assert reranked[0].citation["rerank_score"] > reranked[1].citation["rerank_score"]
    assert set(reranked[0].annotations[0]) == {"type", "index", "file_id", "filename"}


def test_profile_rerank_disabled_preserves_fused_order_and_scores():
    service = RetrievalService.__new__(RetrievalService)
    chunks = [
        ChunkRecord(id="chk_a", document_id="doc_a", ordinal=0, text="alpha answer", score=0.2),
        ChunkRecord(id="chk_b", document_id="doc_b", ordinal=1, text="beta answer", score=0.1),
    ]

    reranked, audit = asyncio.run(service._rerank_chunks(chunks, "beta", {"reranker": "disabled"}, top_k=1))

    assert reranked == chunks
    assert [chunk.score for chunk in reranked] == [0.2, 0.1]
    assert audit == {
        "enabled": False,
        "reranker": "disabled",
        "candidate_count": 2,
        "result_count": 1,
    }


def test_unsupported_reranker_fails_closed():
    service = RetrievalService.__new__(RetrievalService)
    chunks = [
        ChunkRecord(id="chk_a", document_id="doc_a", ordinal=0, text="alpha answer", score=0.2),
        ChunkRecord(id="chk_b", document_id="doc_b", ordinal=1, text="beta answer", score=0.1),
    ]

    with pytest.raises(ProviderConfigurationError, match="Unsupported retrieval reranker"):
        asyncio.run(service._rerank_chunks(chunks, "alpha", {"reranker": "unknown_reranker"}, top_k=1))


def test_model_gateway_rerank_promotes_gateway_relevant_chunk(monkeypatch):
    service = RetrievalService.__new__(RetrievalService)
    profile = {
        "reranker": "model_gateway_rerank_v1",
        "reranker_profile_id": "optional_voyage_or_qwen_reranker_v1",
        "rerank_candidate_top_k": 10,
        "rerank_weight": 0.9,
        "rerank_fusion_weight": 0.1,
    }
    high_fusion = ChunkRecord(
        id="chk_high",
        document_id="doc_high",
        ordinal=0,
        text="Generic platform notes.",
        score=1.0,
        citation={"type": "file_citation", "index": 0, "file_id": "file_high", "filename": "high.md"},
    )
    gateway_match = ChunkRecord(
        id="chk_gateway",
        document_id="doc_gateway",
        ordinal=1,
        text="Gateway reranker says this is the strongest source.",
        score=0.05,
        citation={"type": "file_citation", "index": 0, "file_id": "file_gateway", "filename": "gateway.md"},
    )

    async def fake_gateway_scores(query, documents, rerank_profile, top_n):
        assert query == "best source"
        assert documents == ["Generic platform notes.", "Gateway reranker says this is the strongest source."]
        assert rerank_profile["reranker_profile_id"] == "optional_voyage_or_qwen_reranker_v1"
        assert top_n == 2
        return [0.01, 0.99], {"provider": "model_gateway", "model": "cohere-rerank-v3.5"}

    monkeypatch.setattr(service, "_model_gateway_rerank_scores", fake_gateway_scores)

    reranked, audit = asyncio.run(service._rerank_chunks(
        [high_fusion, gateway_match],
        "best source",
        profile,
        top_k=1,
    ))

    assert [chunk.id for chunk in reranked] == ["chk_gateway", "chk_high"]
    assert audit["enabled"] is True
    assert audit["reranker"] == "model_gateway_rerank_v1"
    assert audit["reranker_provider"] == "model_gateway"
    assert audit["reranker_model"] == "cohere-rerank-v3.5"
    assert reranked[0].citation["reranker"] == "model_gateway_rerank_v1"
    assert reranked[0].citation["reranker_provider"] == "model_gateway"
    assert reranked[0].citation["reranker_model"] == "cohere-rerank-v3.5"
    assert reranked[0].citation["rerank_score"] == 0.99


def test_model_gateway_rerank_scores_posts_configured_contract(monkeypatch):
    captured = {}

    class _FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "results": [{"index": 1, "relevance_score": 0.92}],
                "model": "cohere-rerank-v3.5",
                "provider": "model_gateway",
            }

    class _FakeAsyncClient:
        def __init__(self, *, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, json):
            captured["url"] = url
            captured["json"] = json
            return _FakeResponse()

    monkeypatch.setattr(retrieval_mod.httpx, "AsyncClient", _FakeAsyncClient)
    service = RetrievalService.__new__(RetrievalService)
    service.settings = SimpleNamespace(model_gateway_url="http://model-gateway:8081")

    scores, meta = asyncio.run(service._model_gateway_rerank_scores(
        "alpha",
        ["first", "second"],
        {
            "reranker": "model_gateway_rerank_v1",
            "reranker_profile_id": "optional_voyage_or_qwen_reranker_v1",
            "rerank_timeout_sec": 7,
        },
        top_n=2,
    ))

    assert captured["url"] == "http://model-gateway:8081/internal/models/rerank"
    assert captured["json"] == {
        "query": "alpha",
        "documents": ["first", "second"],
        "model_profile_id": "optional_voyage_or_qwen_reranker_v1",
        "top_n": 2,
    }
    assert captured["timeout"] == 7
    assert scores == [0.0, 0.92]
    assert meta == {"provider": "model_gateway", "model": "cohere-rerank-v3.5"}


def test_model_gateway_retrieval_profile_declares_gateway_reranker():
    profile = retrieval_profiles()["hybrid_rrf_model_gateway_rerank_v1"]

    assert profile["reranker"] == "model_gateway_rerank_v1"
    assert profile["reranker_profile_id"] == "optional_voyage_or_qwen_reranker_v1"
    assert profile["rerank_candidate_top_k"] >= 10


def test_fusion_weights_use_profile_defaults_without_openai_override():
    service = RetrievalService.__new__(RetrievalService)

    dense_weight, sparse_weight, audit = service._fusion_weights(
        {"dense_weight": 0.35, "sparse_weight": 0.65},
        {},
    )

    assert dense_weight == 0.35
    assert sparse_weight == 0.65
    assert audit == {
        "dense_weight": 0.35,
        "sparse_weight": 0.65,
        "source": "retrieval_profile",
    }


def test_fusion_weights_use_openai_hybrid_search_override():
    service = RetrievalService.__new__(RetrievalService)

    dense_weight, sparse_weight, audit = service._fusion_weights(
        {"dense_weight": 0.35, "sparse_weight": 0.65},
        {"openai_compat": {"hybrid_search": {"embedding_weight": 0.8, "text_weight": 0.2}}},
    )

    assert dense_weight == 0.8
    assert sparse_weight == 0.2
    assert audit == {
        "dense_weight": 0.8,
        "sparse_weight": 0.2,
        "source": "openai_ranking_options.hybrid_search",
    }


def test_fusion_weights_allow_one_openai_weight_with_profile_default_for_other_side():
    service = RetrievalService.__new__(RetrievalService)

    dense_weight, sparse_weight, audit = service._fusion_weights(
        {"dense_weight": 0.35, "sparse_weight": 0.65},
        {"openai_compat": {"hybrid_search": {"embedding_weight": 0.9}}},
    )

    assert dense_weight == 0.9
    assert sparse_weight == 0.65
    assert audit["source"] == "openai_ranking_options.hybrid_search"


def test_code_symbol_retrieval_profile_declares_exact_symbol_boost():
    profile = retrieval_profiles()["hybrid_code_symbol_rrf_v2"]

    assert profile["fusion"] == "weighted_rrf"
    assert profile["sparse_weight"] > profile["dense_weight"]
    assert profile["exact_symbol_boost"] > 0


def test_exact_symbol_boost_promotes_symbol_chunk_and_preserves_annotation_shape():
    service = RetrievalService.__new__(RetrievalService)
    generic = ChunkRecord(
        id="chk_generic",
        document_id="doc_generic",
        ordinal=0,
        text="General environment setup notes without the requested config key.",
        score=1.0,
        citation={"type": "file_citation", "index": 0, "file_id": "file_generic", "filename": "generic.md"},
    )
    symbol_match = ChunkRecord(
        id="chk_symbol",
        document_id="doc_symbol",
        ordinal=1,
        text="Set MODEL_GATEWAY_URL before enabling the internal reranker endpoint.",
        filename="settings.py",
        score=0.05,
        citation={"type": "file_citation", "index": 0, "file_id": "file_symbol", "filename": "settings.py"},
    )

    boosted, audit = service._apply_exact_symbol_boost(
        [generic, symbol_match],
        "Where is MODEL_GATEWAY_URL configured?",
        {"exact_symbol_boost": 2.0},
        top_k=1,
    )

    assert [chunk.id for chunk in boosted] == ["chk_symbol", "chk_generic"]
    assert audit["enabled"] is True
    assert audit["boost"] == 2.0
    assert audit["symbols"] == ["MODEL_GATEWAY_URL"]
    assert audit["matched_symbols"] == ["MODEL_GATEWAY_URL"]
    assert audit["boosted_count"] == 1
    assert boosted[0].score == 2.05
    assert boosted[0].source == "hybrid_rrf_symbol_boost"
    assert boosted[0].citation["exact_symbol_matches"] == ["MODEL_GATEWAY_URL"]
    assert boosted[0].citation["exact_symbol_base_score"] == 0.05
    assert boosted[0].citation["exact_symbol_score"] == 2.05
    assert boosted[0].annotations == [{
        "type": "file_citation",
        "index": 0,
        "file_id": "file_symbol",
        "filename": "settings.py",
    }]


def test_exact_symbol_boost_disabled_preserves_existing_order_and_scores():
    service = RetrievalService.__new__(RetrievalService)
    chunks = [
        ChunkRecord(id="chk_a", document_id="doc_a", ordinal=0, text="MODEL_GATEWAY_URL", score=0.1),
        ChunkRecord(id="chk_b", document_id="doc_b", ordinal=1, text="generic", score=0.2),
    ]

    boosted, audit = service._apply_exact_symbol_boost(
        chunks,
        "MODEL_GATEWAY_URL",
        {"exact_symbol_boost": 0},
        top_k=2,
    )

    assert boosted == chunks
    assert [chunk.score for chunk in boosted] == [0.1, 0.2]
    assert audit == {
        "enabled": False,
        "boost": 0.0,
        "candidate_count": 2,
        "result_count": 2,
    }


def test_exact_symbol_query_terms_are_conservative():
    service = RetrievalService.__new__(RetrievalService)

    assert service._query_exact_symbols("where are api keys stored") == []
    assert service._query_exact_symbols("Find RetrievalService._query_embedding, getUserID, and /v1/vector_stores") == [
        "RetrievalService._query_embedding",
        "getUserID",
        "v1/vector_stores",
    ]


def test_openai_ranker_none_disables_request_scoped_rerank_and_diversity():
    service = RetrievalService.__new__(RetrievalService)
    profile = service._effective_profile_for_search(
        {
            "reranker": "local_lexical_overlap_v1",
            "rerank_candidate_top_k": 10,
            "diversity": "lexical_mmr_v1",
        },
        {"openai_compat": {"ranker": "none"}},
    )
    chunks = [
        ChunkRecord(id="chk_high", document_id="doc_1", ordinal=0, text="generic", score=0.9),
        ChunkRecord(id="chk_exact", document_id="doc_2", ordinal=1, text="alpha exact phrase", score=0.1),
    ]

    reranked, audit = asyncio.run(service._rerank_chunks(chunks, "alpha exact phrase", profile, top_k=2))

    assert reranked == chunks
    assert audit == {
        "enabled": False,
        "reranker": "none",
        "candidate_count": 2,
        "result_count": 2,
        "source": "openai_ranking_options.ranker",
        "requested_ranker": "none",
    }


def test_openai_ranker_auto_preserves_profile_rerank():
    service = RetrievalService.__new__(RetrievalService)
    profile = service._effective_profile_for_search(
        {"reranker": "local_lexical_overlap_v1", "rerank_candidate_top_k": 10, "diversity": "disabled"},
        {"openai_compat": {"ranker": "auto"}},
    )
    chunks = [
        ChunkRecord(id="chk_high", document_id="doc_1", ordinal=0, text="generic", score=0.9),
        ChunkRecord(id="chk_exact", document_id="doc_2", ordinal=1, text="alpha exact phrase", score=0.1),
    ]

    reranked, audit = asyncio.run(service._rerank_chunks(chunks, "alpha exact phrase", profile, top_k=2))

    assert [chunk.id for chunk in reranked] == ["chk_exact", "chk_high"]
    assert audit["enabled"] is True
    assert audit["reranker"] == "local_lexical_overlap_v1"


def test_retrieval_audit_records_rerank_metadata():
    service = RetrievalService.__new__(RetrievalService)
    db = _AuditDb()
    principal = Principal(tenant_id="tenant", business_instance_id="biz-dev", user_id="usr", max_security_level=5)
    req = SearchRequest(query="alpha", vector_store_id="vs_123", top_k=2)

    service._audit(
        db,
        principal,
        req,
        ["chk_exact", "chk_high"],
        {
            "retrieval_profile_id": "hybrid_rrf_secure_v2",
            "exact_symbol_boost": {"enabled": True, "boosted_count": 1, "matched_symbols": ["MODEL_GATEWAY_URL"]},
            "rerank": {"enabled": True, "reranker": "local_lexical_overlap_v1", "candidate_count": 2},
        },
    )

    metadata = json.loads(db.calls[0][1]["metadata"])
    assert metadata["retrieval_profile_id"] == "hybrid_rrf_secure_v2"
    assert metadata["exact_symbol_boost"]["boosted_count"] == 1
    assert metadata["exact_symbol_boost"]["matched_symbols"] == ["MODEL_GATEWAY_URL"]
    assert metadata["rerank"]["enabled"] is True
    assert metadata["rerank"]["reranker"] == "local_lexical_overlap_v1"
    assert metadata["result_ids"] == ["chk_exact", "chk_high"]


def _neighbor_row(
    *,
    chunk_id: str,
    ordinal: int,
    text: str,
    document_id: str = "doc_1",
    file_id: str = "file_doc",
    security_level: int = 1,
    allowed_groups: list[str] | None = None,
    allowed_roles: list[str] | None = None,
    heading_path: list[str] | None = None,
):
    return {
        "id": chunk_id,
        "document_id": document_id,
        "document_version_id": "dv_1",
        "file_id": file_id,
        "title": "Context doc",
        "filename": "context.md",
        "source_uri": "https://docs.example.test/context.md",
        "ordinal": ordinal,
        "text": text,
        "heading_path": heading_path or ["Section"],
        "page_start": ordinal + 1,
        "page_end": ordinal + 1,
        "metadata": {},
        "security_level": security_level,
        "classification": "tenant_private",
        "allowed_groups": allowed_groups or [],
        "allowed_roles": allowed_roles or [],
    }


def test_context_neighbor_expansion_fetches_same_document_neighbors_with_filters():
    service = RetrievalService.__new__(RetrievalService)
    principal = Principal(
        tenant_id="tenant",
        business_instance_id="biz-dev",
        groups=["eng"],
        roles=["admin"],
        max_security_level=5,
    )
    direct = ChunkRecord(
        id="chk_2",
        document_id="doc_1",
        file_id="file_doc",
        filename="context.md",
        ordinal=2,
        text="Direct retrieval hit.",
        score=0.9,
        citation={"type": "file_citation", "index": 0, "file_id": "file_doc", "filename": "context.md"},
    )
    db = _Db([
        _neighbor_row(chunk_id="chk_1", ordinal=1, text="Previous chunk."),
        _neighbor_row(chunk_id="chk_3", ordinal=3, text="Following chunk."),
    ])

    expanded = service._expand_context_neighbors(
        db,
        principal,
        [direct],
        {"expand_neighbors": True, "neighbor_window": 1},
        {
            "vector_store_id": "vs_1",
            "file_attribute_filters": {"region": "us"},
            "file_attribute_filter_any": [
                {"category": "blog"},
                {"category": "announcement"},
            ],
            "file_attribute_ranges": [
                {"key": "created_at", "op": "gte", "value": "2026-01-01"},
            ],
        },
    )

    assert [chunk.id for chunk in expanded] == ["chk_1", "chk_2", "chk_3"]
    assert "JOIN vector_store_files vsf" in db.sql
    assert "vsf.attributes @> CAST(:neighbor_file_attr_exact AS jsonb)" in db.sql
    assert "vsf.attributes @> CAST(:neighbor_file_attr_any_0 AS jsonb)" in db.sql
    assert "OR vsf.attributes @> CAST(:neighbor_file_attr_any_1 AS jsonb)" in db.sql
    assert "jsonb_typeof(vsf.attributes -> :neighbor_file_attr_range_0_key) = 'string'" in db.sql
    assert "c.vector_store_id=:vector_store_id" in db.sql
    assert db.params["tenant_id"] == "tenant"
    assert db.params["biz_id"] == "biz-dev"
    assert db.params["max_lvl"] == 5
    assert db.params["vector_store_id"] == "vs_1"
    assert db.params["neighbor_file_attr_exact"] == '{"region":"us"}'
    assert db.params["neighbor_file_attr_any_0"] == '{"category":"blog"}'
    assert db.params["neighbor_file_attr_any_1"] == '{"category":"announcement"}'
    assert db.params["neighbor_file_attr_range_0_key"] == "created_at"
    assert db.params["neighbor_file_attr_range_0_value"] == "2026-01-01"

    assert expanded[0].citation["context_relation"] == "neighbor_before"
    assert expanded[0].citation["source_chunk_id"] == "chk_2"
    assert expanded[0].citation["neighbor_offset"] == -1
    assert expanded[1].citation["context_relation"] == "direct"
    assert expanded[2].citation["context_relation"] == "neighbor_after"
    assert expanded[0].annotations == [{
        "type": "file_citation",
        "index": 0,
        "file_id": "file_doc",
        "filename": "context.md",
    }]


def test_context_neighbor_expansion_disabled_or_zero_window_preserves_chunks_without_query():
    service = RetrievalService.__new__(RetrievalService)
    principal = Principal(tenant_id="tenant", business_instance_id="biz-dev", max_security_level=5)
    direct = ChunkRecord(id="chk_2", document_id="doc_1", ordinal=2, text="Direct retrieval hit.")
    db = _Db([_neighbor_row(chunk_id="chk_1", ordinal=1, text="Previous chunk.")])

    assert service._expand_context_neighbors(db, principal, [direct], {"expand_neighbors": False, "neighbor_window": 1}, {}) == [direct]
    assert db.sql == ""
    assert service._expand_context_neighbors(db, principal, [direct], {"expand_neighbors": True, "neighbor_window": 0}, {}) == [direct]
    assert db.sql == ""


def test_context_neighbor_expansion_post_acl_filters_neighbor_rows():
    service = RetrievalService.__new__(RetrievalService)
    principal = Principal(
        tenant_id="tenant",
        business_instance_id="biz-dev",
        groups=["eng"],
        roles=["admin"],
        max_security_level=5,
    )
    direct = ChunkRecord(id="chk_2", document_id="doc_1", ordinal=2, text="Direct retrieval hit.")
    db = _Db([
        _neighbor_row(chunk_id="chk_1", ordinal=1, text="Allowed previous chunk.", allowed_groups=["eng"]),
        _neighbor_row(chunk_id="chk_3", ordinal=3, text="Blocked following chunk.", allowed_groups=["finance"]),
    ])

    expanded = service._expand_context_neighbors(
        db,
        principal,
        [direct],
        {"expand_neighbors": True, "neighbor_window": 1},
        {},
    )

    assert [chunk.id for chunk in expanded] == ["chk_1", "chk_2"]


def test_context_parent_section_expansion_fetches_heading_prefix_with_filters():
    service = RetrievalService.__new__(RetrievalService)
    principal = Principal(
        tenant_id="tenant",
        business_instance_id="biz-dev",
        groups=["eng"],
        roles=["admin"],
        max_security_level=5,
    )
    direct = ChunkRecord(
        id="chk_2",
        document_id="doc_1",
        file_id="file_doc",
        filename="context.md",
        ordinal=2,
        text="Direct panel hit.",
        heading_path=["Electrical", "Panel A"],
        citation={"type": "file_citation", "index": 0, "file_id": "file_doc", "filename": "context.md"},
    )
    db = _Db([
        _neighbor_row(chunk_id="chk_1", ordinal=1, text="Electrical overview.", heading_path=["Electrical"]),
        _neighbor_row(chunk_id="chk_2", ordinal=2, text="Direct panel hit.", heading_path=["Electrical", "Panel A"]),
        _neighbor_row(chunk_id="chk_3", ordinal=3, text="Sibling panel notes.", heading_path=["Electrical", "Panel B"]),
        _neighbor_row(chunk_id="chk_4", ordinal=4, text="Blocked finance notes.", heading_path=["Electrical", "Panel C"], allowed_groups=["finance"]),
        _neighbor_row(chunk_id="chk_5", ordinal=5, text="Mechanical notes.", heading_path=["Mechanical"]),
    ])

    expanded = service._expand_context_parent_sections(
        db,
        principal,
        [direct],
        {"expand_parent_sections": True, "parent_section_max_chunks": 10},
        {
            "vector_store_id": "vs_1",
            "file_attribute_filters": {"region": "us"},
            "file_attribute_filter_any": [
                {"category": "blog"},
                {"category": "announcement"},
            ],
            "file_attribute_ranges": [
                {"key": "created_at", "op": "lt", "value": "2026-02-01"},
            ],
        },
    )

    assert [chunk.id for chunk in expanded] == ["chk_1", "chk_2", "chk_3"]
    assert "array_length(c.heading_path, 1) >= :parent_depth_0" in db.sql
    assert "c.heading_path[1]=:parent_heading_0_0" in db.sql
    assert "JOIN vector_store_files vsf" in db.sql
    assert "vsf.attributes @> CAST(:parent_file_attr_exact AS jsonb)" in db.sql
    assert "vsf.attributes @> CAST(:parent_file_attr_any_0 AS jsonb)" in db.sql
    assert "OR vsf.attributes @> CAST(:parent_file_attr_any_1 AS jsonb)" in db.sql
    assert "jsonb_typeof(vsf.attributes -> :parent_file_attr_range_0_key) = 'string'" in db.sql
    assert "c.vector_store_id=:vector_store_id" in db.sql
    assert db.params["parent_heading_0_0"] == "Electrical"
    assert db.params["parent_depth_0"] == 1
    assert db.params["parent_file_attr_exact"] == '{"region":"us"}'
    assert db.params["parent_file_attr_any_0"] == '{"category":"blog"}'
    assert db.params["parent_file_attr_any_1"] == '{"category":"announcement"}'
    assert db.params["parent_file_attr_range_0_key"] == "created_at"
    assert db.params["parent_file_attr_range_0_value"] == "2026-02-01"

    assert expanded[0].citation["context_relation"] == "parent_section"
    assert expanded[0].citation["source_chunk_id"] == "chk_2"
    assert expanded[0].citation["neighbor_offset"] == -1
    assert expanded[0].citation["parent_heading_path"] == ["Electrical"]
    assert expanded[1].citation["context_relation"] == "direct"
    assert expanded[2].citation["context_relation"] == "parent_section"
    assert expanded[0].annotations == [{
        "type": "file_citation",
        "index": 0,
        "file_id": "file_doc",
        "filename": "context.md",
    }]


def test_context_parent_section_expansion_disabled_or_no_heading_preserves_chunks_without_query():
    service = RetrievalService.__new__(RetrievalService)
    principal = Principal(tenant_id="tenant", business_instance_id="biz-dev", max_security_level=5)
    direct = ChunkRecord(id="chk_2", document_id="doc_1", ordinal=2, text="Direct retrieval hit.")
    db = _Db([_neighbor_row(chunk_id="chk_1", ordinal=1, text="Previous chunk.")])

    assert service._expand_context_parent_sections(db, principal, [direct], {"expand_parent_sections": False}, {}) == [direct]
    assert db.sql == ""
    assert service._expand_context_parent_sections(db, principal, [direct], {"expand_parent_sections": True}, {}) == [direct]
    assert db.sql == ""


def test_context_parent_section_expansion_preserves_mixed_unheaded_direct_hits():
    service = RetrievalService.__new__(RetrievalService)
    principal = Principal(tenant_id="tenant", business_instance_id="biz-dev", max_security_level=5)
    headed = ChunkRecord(
        id="chk_2",
        document_id="doc_1",
        ordinal=2,
        text="Direct headed hit.",
        heading_path=["Electrical", "Panel A"],
    )
    unheaded = ChunkRecord(id="chk_9", document_id="doc_2", ordinal=9, text="Direct unheaded hit.")
    db = _Db([
        _neighbor_row(chunk_id="chk_1", ordinal=1, text="Electrical overview.", heading_path=["Electrical"]),
        _neighbor_row(chunk_id="chk_2", ordinal=2, text="Direct headed hit.", heading_path=["Electrical", "Panel A"]),
    ])

    expanded = service._expand_context_parent_sections(
        db,
        principal,
        [headed, unheaded],
        {"expand_parent_sections": True, "parent_section_max_chunks": 10},
        {},
    )

    assert [chunk.id for chunk in expanded] == ["chk_1", "chk_2", "chk_9"]
    assert expanded[-1].citation["context_relation"] == "direct"
    assert expanded[-1].citation["source_chunk_id"] == "chk_9"


def test_context_pack_merges_parent_sections_and_neighbors_before_token_trim(monkeypatch):
    service = RetrievalService.__new__(RetrievalService)
    principal = Principal(tenant_id="tenant", business_instance_id="biz-dev", max_security_level=5)
    direct = ChunkRecord(
        id="chk_2",
        document_id="doc_1",
        file_id="file_doc",
        filename="context.md",
        ordinal=2,
        text="direct",
        heading_path=["Electrical", "Panel A"],
    )
    parent = ChunkRecord(
        id="chk_1",
        document_id="doc_1",
        file_id="file_doc",
        filename="context.md",
        ordinal=1,
        text="parent",
        metadata={"line_start": 8, "line_end": 13},
        citation={
            "type": "file_citation",
            "index": 0,
            "file_id": "file_doc",
            "filename": "context.md",
            "context_relation": "parent_section",
            "source_chunk_id": "chk_2",
            "neighbor_offset": -1,
            "parent_heading_path": ["Electrical"],
        },
    )
    neighbor = ChunkRecord(
        id="chk_3",
        document_id="doc_1",
        file_id="file_doc",
        filename="context.md",
        ordinal=3,
        text="neighbor",
        citation={
            "type": "file_citation",
            "index": 0,
            "file_id": "file_doc",
            "filename": "context.md",
            "context_relation": "neighbor_after",
            "source_chunk_id": "chk_2",
            "neighbor_offset": 1,
        },
    )
    too_large = ChunkRecord(
        id="chk_4",
        document_id="doc_1",
        file_id="file_doc",
        filename="context.md",
        ordinal=4,
        text="too many words to fit",
        citation={
            "type": "file_citation",
            "index": 0,
            "file_id": "file_doc",
            "filename": "context.md",
            "context_relation": "neighbor_after",
            "source_chunk_id": "chk_2",
            "neighbor_offset": 2,
        },
    )

    async def fake_search(db, principal, req):
        return SearchResponse(query=req.query, results=[direct], audit_event_id="aud_1", retrieval_profile_id="profile_on")

    service.search = fake_search
    service._expand_context_parent_sections = lambda db, principal, chunks, profile, filters: [parent, direct]
    service._expand_context_neighbors = lambda db, principal, chunks, profile, filters: [direct, neighbor, too_large]
    monkeypatch.setattr(
        retrieval_mod,
        "retrieval_profiles",
        lambda: {"profile_on": {"expand_parent_sections": True, "expand_neighbors": True, "neighbor_window": 1}},
    )

    result = asyncio.run(service.context_pack(_Db([]), principal, ContextPackRequest(query="context", max_context_tokens=3)))

    assert [citation.chunk_id for citation in result.citations] == ["chk_1", "chk_2", "chk_3"]
    assert [chunk.id for chunk in result.chunks] == ["chk_1", "chk_2", "chk_3"]
    assert "too many words to fit" not in result.context
    expected_model_markers = [
        "\ue200cite\ue202turn0file0\ue202L8-L13\ue201",
        "\ue200cite\ue202turn0file1\ue201",
        "\ue200cite\ue202turn0file2\ue201",
    ]
    for index, (citation, marker, model_marker) in enumerate(
        zip(result.citations, ["【1†source】", "【2†source】", "【3†source】"], expected_model_markers, strict=True)
    ):
        marker_index = result.context.index(marker)
        assert citation.marker == marker
        assert citation.annotation == {
            "type": "file_citation",
            "index": marker_index,
            "file_id": "file_doc",
            "filename": "context.md",
        }
        assert citation.message_annotation.model_dump(mode="python") == {
            "type": "file_citation",
            "start_index": marker_index,
            "end_index": marker_index + len(marker),
            "text": marker,
            "file_citation": {"file_id": "file_doc"},
        }
        assert citation.model_source_id == f"turn0file{index}"
        assert citation.model_marker == model_marker
        assert f"Citation Marker: {model_marker}" in result.context
        assert result.context[marker_index:marker_index + len(marker)] == marker
    assert result.citations[0].model_locator == "L8-L13"
    assert result.citations[1].model_locator is None
    assert result.citations[0].context_relation == "parent_section"
    assert result.citations[0].parent_heading_path == ["Electrical"]
    assert result.citations[2].context_relation == "neighbor_after"


def test_context_pack_uses_expanded_chunks_and_trims_chunks_to_citations(monkeypatch):
    service = RetrievalService.__new__(RetrievalService)
    principal = Principal(tenant_id="tenant", business_instance_id="biz-dev", max_security_level=5)
    direct = ChunkRecord(
        id="chk_2",
        document_id="doc_1",
        file_id="file_doc",
        filename="context.md",
        ordinal=2,
        text="direct",
    )
    neighbor = ChunkRecord(
        id="chk_1",
        document_id="doc_1",
        file_id="file_doc",
        filename="context.md",
        ordinal=1,
        text="neighbor",
        citation={
            "type": "file_citation",
            "index": 0,
            "file_id": "file_doc",
            "filename": "context.md",
            "context_relation": "neighbor_before",
            "source_chunk_id": "chk_2",
            "neighbor_offset": -1,
        },
    )
    too_large = ChunkRecord(
        id="chk_3",
        document_id="doc_1",
        file_id="file_doc",
        filename="context.md",
        ordinal=3,
        text="too many words to fit",
    )

    async def fake_search(db, principal, req):
        return SearchResponse(query=req.query, results=[direct], audit_event_id="aud_1", retrieval_profile_id="profile_on")

    service.search = fake_search
    service._expand_context_neighbors = lambda db, principal, chunks, profile, filters: [neighbor, direct, too_large]
    monkeypatch.setattr(retrieval_mod, "retrieval_profiles", lambda: {"profile_on": {"expand_neighbors": True, "neighbor_window": 1}})

    result = asyncio.run(service.context_pack(_Db([]), principal, ContextPackRequest(query="context", max_context_tokens=2)))

    assert [citation.chunk_id for citation in result.citations] == ["chk_1", "chk_2"]
    assert [chunk.id for chunk in result.chunks] == ["chk_1", "chk_2"]
    assert result.citations[0].context_relation == "neighbor_before"
    assert result.citations[0].source_chunk_id == "chk_2"
    assert result.citations[0].neighbor_offset == -1
    marker_index = result.context.index("【1†source】")
    assert result.citations[0].marker == "【1†source】"
    assert result.citations[0].annotation == {
        "type": "file_citation",
        "index": marker_index,
        "file_id": "file_doc",
        "filename": "context.md",
    }
    assert result.context[marker_index:marker_index + len("【1†source】")] == "【1†source】"


def test_neighbor_expansion_is_not_in_native_search_result_selection():
    source = inspect.getsource(RetrievalService.search)

    assert "_expand_context_neighbors" not in source
    assert "_expand_context_parent_sections" not in source


def test_retrieval_answer_builds_extractively_from_context_pack_and_redacts():
    service = RetrievalService.__new__(RetrievalService)
    principal = Principal(tenant_id="tenant", business_instance_id="biz-dev", max_security_level=5)
    chunks = [
        ChunkRecord(
            id="chk_1",
            document_id="doc_1",
            file_id="file_1",
            filename="source-1.md",
            ordinal=1,
            text="Contact bob@example.com for the approval token. Authorization: Bearer abcdefghijklmnop. Existing 【9†source】 marker.",
        ),
        ChunkRecord(
            id="chk_2",
            document_id="doc_2",
            file_id="file_2",
            filename="source-2.md",
            ordinal=2,
            text="Second source confirms the escalation path.",
        ),
    ]
    citations = [
        ContextCitation(chunk_id="chk_1", document_id="doc_1", file_id="file_1", filename="source-1.md", marker="【1†source】"),
        ContextCitation(chunk_id="chk_2", document_id="doc_2", file_id="file_2", filename="source-2.md", marker="【2†source】"),
    ]

    async def fake_context_pack(db, principal, req):
        return ContextPackResponse(
            query=req.query,
            context="context text",
            citations=citations,
            chunks=chunks,
            token_estimate=12,
            audit_event_id="aud_answer",
        )

    service.context_pack = fake_context_pack

    result = asyncio.run(service.answer(_Db([]), principal, RetrievalAnswerRequest(query="contact", max_answer_sources=2)))

    assert result.query == "contact"
    assert result.answer.startswith("Answer from retrieved sources:")
    assert "bob@example.com" not in result.answer
    assert "abcdefghijklmnop" not in result.answer
    assert "[REDACTED_EMAIL]" in result.answer
    assert "Bearer [REDACTED_SECRET]" in result.answer
    assert "【9†source】" not in result.answer
    assert [citation.marker for citation in result.citations] == ["【1†source】", "【2†source】"]
    assert [citation.chunk_id for citation in result.citations] == ["chk_1", "chk_2"]
    assert [citation.model_source_id for citation in result.citations] == ["turn0file0", "turn0file1"]
    assert [citation.model_marker for citation in result.citations] == [
        "\ue200cite\ue202turn0file0\ue201",
        "\ue200cite\ue202turn0file1\ue201",
    ]
    for citation in result.citations:
        marker = citation.marker
        marker_index = result.answer.index(marker)
        assert citation.annotation == {
            "type": "file_citation",
            "index": marker_index,
            "file_id": citation.file_id,
            "filename": citation.filename,
        }
        assert citation.message_annotation == {
            "type": "file_citation",
            "start_index": marker_index,
            "end_index": marker_index + len(marker),
            "text": marker,
            "file_citation": {"file_id": citation.file_id},
        }
    assert [chunk.id for chunk in result.chunks] == ["chk_1", "chk_2"]
    assert result.context == "context text"
    assert result.audit_event_id == "aud_answer"
    assert result.output_guard["id"] == "pii_secret_citation_guard_v1"


def test_retrieval_answer_limits_citations_to_context_pack_sources():
    service = RetrievalService.__new__(RetrievalService)
    principal = Principal(tenant_id="tenant", business_instance_id="biz-dev", max_security_level=5)
    chunks = [
        ChunkRecord(id="chk_1", document_id="doc_1", file_id="file_1", filename="source-1.md", ordinal=1, text="First."),
        ChunkRecord(id="chk_2", document_id="doc_2", file_id="file_2", filename="source-2.md", ordinal=2, text="Second."),
    ]

    async def fake_context_pack(db, principal, req):
        return ContextPackResponse(
            query=req.query,
            context="context text",
            citations=[
                ContextCitation(chunk_id="chk_1", document_id="doc_1", file_id="file_1", filename="source-1.md"),
                ContextCitation(chunk_id="chk_2", document_id="doc_2", file_id="file_2", filename="source-2.md"),
            ],
            chunks=chunks,
            token_estimate=3,
        )

    service.context_pack = fake_context_pack

    result = asyncio.run(service.answer(_Db([]), principal, RetrievalAnswerRequest(query="limit", max_answer_sources=1)))

    assert [citation.chunk_id for citation in result.citations] == ["chk_1"]
    assert [chunk.id for chunk in result.chunks] == ["chk_1"]
    assert "【1†source】" in result.answer
    assert "【2†source】" not in result.answer


def test_retrieval_answer_citation_integrity_guard_rejects_bad_payloads():
    valid = ContextCitation(
        chunk_id="chk_1",
        document_id="doc_1",
        file_id="file_1",
        filename="source.md",
        marker="【1†source】",
        annotation={"type": "file_citation", "index": len("Answer "), "file_id": "file_1", "filename": "source.md"},
    )
    ensure_retrieval_answer_citation_integrity("Answer 【1†source】", [valid])

    with pytest.raises(ValueError, match="markers must match"):
        ensure_retrieval_answer_citation_integrity("Answer 【1†source】", [])

    malformed = valid.model_copy(update={"annotation": {**valid.annotation, "quote": "extra"}})
    with pytest.raises(ValueError, match="strict OpenAI file_citation"):
        ensure_retrieval_answer_citation_integrity("Answer 【1†source】", [malformed])

    wrong_index = valid.model_copy(update={"annotation": {**valid.annotation, "index": 0}})
    with pytest.raises(ValueError, match="does not point"):
        ensure_retrieval_answer_citation_integrity("Answer 【1†source】", [wrong_index])
