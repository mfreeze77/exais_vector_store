from __future__ import annotations
from collections import OrderedDict, defaultdict
from sqlalchemy import text
from sqlalchemy.orm import Session
from .sql import jsonb_text
from .db import jsonb_param
from .schemas import SearchRequest, SearchResponse, ChunkRecord, ContextPackRequest, ContextPackResponse, ContextCitation, Principal
from .security import build_retrieval_scope, build_qdrant_filter, chunk_allowed_by_scope
from .providers import provider_for
from .providers import ProviderConfigurationError
from .model_registry import resolve_embedding_profile, retrieval_profiles, model_registry
from .qdrant_adapter import QdrantAdapter
from .opensearch_adapter import OpenSearchAdapter
from .hashing import query_hash, sha256_text
from .ids import new_id
from .chunking import estimate_tokens
from .config import get_settings

QUERY_EMBEDDING_CACHE_MAX = 2048

def reciprocal_rank_fusion(result_lists: list[list[dict]], k: int = 60, weights: list[float] | None = None) -> list[dict]:
    scores, payloads = defaultdict(float), {}
    weights = weights or [1.0] * len(result_lists)
    for list_idx, results in enumerate(result_lists):
        for rank, item in enumerate(results, start=1):
            item_id = item["id"]
            scores[item_id] += weights[list_idx] * (1.0 / (k + rank))
            payloads[item_id] = item
    return sorted([{**payloads[i], "score": s} for i, s in scores.items()], key=lambda x: x["score"], reverse=True)

class RetrievalService:
    def __init__(self):
        self.settings = get_settings()
        self.qdrant = QdrantAdapter()
        self.opensearch = OpenSearchAdapter()
        self._query_embedding_cache: OrderedDict[tuple, list[float]] = OrderedDict()

    async def search(self, db: Session, principal: Principal, req: SearchRequest) -> SearchResponse:
        scope = build_retrieval_scope(principal)
        profile_id = req.retrieval_profile_id or "hybrid_rrf_secure_v2"
        profile = retrieval_profiles().get(profile_id, {})
        filters = dict(req.filters or {})
        if req.vector_store_id: filters["vector_store_id"] = req.vector_store_id
        if req.knowledge_base_id: filters["knowledge_base_id"] = req.knowledge_base_id

        dense_lists = []
        registry = model_registry().get("models", {})
        for embedding_profile_id in self._embedding_profiles_for_search(db, scope, req, filters):
            emb_profile = registry.get(embedding_profile_id)
            if not emb_profile:
                raise ProviderConfigurationError(f"Unknown embedding profile: {embedding_profile_id}")
            provider_name = emb_profile.get("provider", "hash_mock")
            model = emb_profile.get("model", "deterministic-dev-hash")
            dimensions = int(emb_profile.get("dimensions", 1536))
            query_vector = await self._query_embedding(
                scope,
                embedding_profile_id,
                req.query,
                provider_name,
                model,
                dimensions,
            )
            dense_lists.append(self.qdrant.search(
                self.qdrant.collection_name(scope.business_instance_id, embedding_profile_id),
                query_vector,
                build_qdrant_filter(scope, filters),
                int(profile.get("dense_top_k", req.top_k * 4)),
            ))
        dense = reciprocal_rank_fusion(dense_lists) if len(dense_lists) > 1 else (dense_lists[0] if dense_lists else [])
        sparse_limit = int(profile.get("sparse_top_k", req.top_k * 4))
        if self.settings.svs_sparse_backend == "opensearch":
            sparse = self.opensearch.search(
                self.opensearch.index_name(scope.business_instance_id),
                req.query,
                {"tenant_id": scope.tenant_id, "business_instance_id": scope.business_instance_id, "max_security_level": scope.max_security_level, **filters},
                sparse_limit,
            )
        else:
            sparse = self._postgres_sparse_search(db, scope, req.query, filters, sparse_limit)
        dense_weight = float(profile.get("dense_weight", 1.0))
        sparse_weight = float(profile.get("sparse_weight", 1.0))
        fused = reciprocal_rank_fusion([dense, sparse], int(profile.get("rrf_k", 60)), [dense_weight, sparse_weight])
        fused = fused[: int(profile.get("fused_top_k", max(req.top_k * 2, 20)))]
        chunks = self._hydrate_and_acl(db, principal, fused, max(req.top_k, int(profile.get("context_top_k", req.top_k))), filters)
        audit_id = self._audit(db, principal, req, [c.id for c in chunks])
        return SearchResponse(query=req.query, results=chunks[:req.top_k], audit_event_id=audit_id, retrieval_profile_id=profile_id)

    def _embedding_profiles_for_search(self, db: Session, scope, req: SearchRequest, filters: dict) -> list[str]:
        params = {"tenant_id": scope.tenant_id, "biz_id": scope.business_instance_id, "max_lvl": scope.max_security_level}
        extra = []
        join_file_attrs = ""
        file_attrs = filters.get("file_attribute_filters") or {}
        if file_attrs:
            join_file_attrs = """
            JOIN vector_store_files vsf
              ON vsf.document_id=c.document_id
             AND vsf.vector_store_id=c.vector_store_id
             AND vsf.tenant_id=c.tenant_id
             AND vsf.business_instance_id=c.business_instance_id
            """
            extra.append("AND vsf.attributes @> CAST(:file_attr_filter AS jsonb)")
            params["file_attr_filter"] = jsonb_param(file_attrs)
        for key, col in (("vector_store_id", "c.vector_store_id"), ("knowledge_base_id", "c.knowledge_base_id"), ("document_id", "c.document_id"), ("classification", "c.classification"), ("acl_bucket", "c.acl_bucket")):
            if filters.get(key):
                extra.append(f"AND {col}=:{key}")
                params[key] = filters[key]
        rows = db.execute(jsonb_text(f"""
            SELECT e.embedding_profile_id, count(*) AS chunk_count
            FROM chunks c
            {join_file_attrs}
            JOIN embeddings e
              ON e.chunk_id=c.id
             AND e.tenant_id=c.tenant_id
             AND e.business_instance_id=c.business_instance_id
            WHERE c.tenant_id=:tenant_id AND c.business_instance_id=:biz_id
              AND c.active=true AND c.security_level <= :max_lvl
              AND e.status='active'
              {' '.join(extra)}
            GROUP BY e.embedding_profile_id
            ORDER BY chunk_count DESC, e.embedding_profile_id
            LIMIT 8
        """, "file_attr_filter"), params).mappings().all()
        profile_ids = [r["embedding_profile_id"] for r in rows if r["embedding_profile_id"]]
        return profile_ids or [resolve_embedding_profile(req.mode or "markdown_docs_v1", scope.max_security_level)]

    async def _query_embedding(self, scope, embedding_profile_id: str, query: str, provider_name: str, model: str, dimensions: int) -> list[float]:
        cache = getattr(self, "_query_embedding_cache", None)
        if cache is None:
            cache = self._query_embedding_cache = OrderedDict()
        key = (
            scope.tenant_id,
            scope.business_instance_id,
            embedding_profile_id,
            provider_name,
            model,
            dimensions,
            sha256_text(query),
        )
        cached = cache.get(key)
        if cached is not None:
            cache.move_to_end(key)
            return cached
        provider = provider_for(provider_name, self.settings)
        emb = await provider.embed([query], model, dimensions, input_type="query")
        if provider_name != "hash_mock" and emb.provider == "hash_mock":
            raise ProviderConfigurationError(
                f"Embedding profile {embedding_profile_id} returned hash_mock vectors for real provider {provider_name}"
            )
        vector = list(emb.data[0].embedding)
        cache[key] = vector
        if len(cache) > QUERY_EMBEDDING_CACHE_MAX:
            cache.popitem(last=False)
        return vector

    def _postgres_sparse_search(self, db: Session, scope, query: str, filters: dict, limit: int) -> list[dict]:
        """Small-cell sparse retrieval fallback using Postgres generated tsvector."""
        params = {"tenant_id": scope.tenant_id, "biz_id": scope.business_instance_id, "max_lvl": scope.max_security_level, "query": query, "limit": limit}
        extra = []
        join_file_attrs = ""
        file_attrs = filters.get("file_attribute_filters") or {}
        if file_attrs:
            join_file_attrs = """
            JOIN vector_store_files vsf
              ON vsf.document_id=c.document_id
             AND vsf.vector_store_id=c.vector_store_id
             AND vsf.tenant_id=c.tenant_id
             AND vsf.business_instance_id=c.business_instance_id
            """
            extra.append("AND vsf.attributes @> CAST(:file_attr_filter AS jsonb)")
            params["file_attr_filter"] = jsonb_param(file_attrs)
        for key, col in (("vector_store_id", "c.vector_store_id"), ("knowledge_base_id", "c.knowledge_base_id"), ("document_id", "c.document_id"), ("classification", "c.classification"), ("acl_bucket", "c.acl_bucket")):
            if filters.get(key):
                extra.append(f"AND {col}=:{key}")
                params[key] = filters[key]
        rows = db.execute(jsonb_text(f"""
            SELECT c.id, c.document_id, c.document_version_id,
                   ts_rank_cd(search_vector, plainto_tsquery('english', :query)) AS score
            FROM chunks c
            {join_file_attrs}
            WHERE c.tenant_id=:tenant_id AND c.business_instance_id=:biz_id AND c.active=true
              AND c.security_level <= :max_lvl
              AND c.search_vector @@ plainto_tsquery('english', :query)
              {' '.join(extra)}
            ORDER BY score DESC, c.created_at DESC
            LIMIT :limit
        """, "file_attr_filter"), params).mappings().all()
        return [{"id": r["id"], "score": float(r["score"] or 0), "payload": {"chunk_id": r["id"], "document_id": r["document_id"], "document_version_id": r["document_version_id"]}} for r in rows]

    def _hydrate_and_acl(self, db: Session, principal: Principal, fused: list[dict], limit: int, filters: dict | None = None) -> list[ChunkRecord]:
        scope = build_retrieval_scope(principal)
        ids = [x.get("payload", {}).get("chunk_id") or x["id"] for x in fused if x.get("payload")]
        if not ids:
            return []
        filters = filters or {}
        params = {"ids": ids, "tenant_id": principal.tenant_id, "biz_id": principal.business_instance_id, "max_lvl": principal.max_security_level}
        join_file_attrs = ""
        extra = ""
        file_attrs = filters.get("file_attribute_filters") or {}
        if file_attrs:
            join_file_attrs = """
            JOIN vector_store_files vsf
              ON vsf.document_id=c.document_id
             AND vsf.vector_store_id=c.vector_store_id
             AND vsf.tenant_id=c.tenant_id
             AND vsf.business_instance_id=c.business_instance_id
            """
            extra = "AND vsf.attributes @> CAST(:file_attr_filter AS jsonb)"
            params["file_attr_filter"] = jsonb_param(file_attrs)
        rows = db.execute(jsonb_text(f"""
            SELECT c.id, c.document_id, c.document_version_id, c.ordinal, c.text, c.heading_path, c.page_start, c.page_end,
                   c.metadata, c.security_level, c.classification, c.allowed_groups, c.allowed_roles
            FROM chunks c
            {join_file_attrs}
            WHERE c.id = ANY(:ids) AND c.tenant_id=:tenant_id AND c.business_instance_id=:biz_id
              AND c.active=true AND c.security_level <= :max_lvl
              {extra}
        """, "file_attr_filter"), params).mappings().all()
        score_map = {x.get("payload", {}).get("chunk_id") or x["id"]: x.get("score", 0.0) for x in fused}
        by_id = {}
        for r in rows:
            ch = ChunkRecord(
                id=r["id"], document_id=r["document_id"], document_version_id=r["document_version_id"],
                ordinal=r["ordinal"], text=r["text"], heading_path=list(r["heading_path"] or []),
                page_start=r["page_start"], page_end=r["page_end"], metadata=dict(r["metadata"] or {}),
                security_level=r["security_level"], classification=r["classification"],
                allowed_groups=list(r["allowed_groups"] or []), allowed_roles=list(r["allowed_roles"] or []),
                score=float(score_map.get(r["id"], 0.0)), source="hybrid_rrf",
            )
            if chunk_allowed_by_scope(ch, scope):
                by_id[ch.id] = ch
        return [by_id[i] for i in ids if i in by_id][:limit]

    def _audit(self, db: Session, principal: Principal, req: SearchRequest, result_ids: list[str]) -> str:
        aud = new_id("aud")
        db.execute(jsonb_text("""
            INSERT INTO audit_events(id, tenant_id, business_instance_id, user_id, api_key_id, event_type, action, resource_type,
              resource_id, security_level, query_hash, metadata)
            VALUES (:id, :tenant_id, :biz_id, :user_id, :api_key_id, 'retrieval', 'search', 'vector_store',
              :resource_id, :lvl, :query_hash, CAST(:metadata AS jsonb))
        """, 'metadata'), {"id": aud, "tenant_id": principal.tenant_id, "biz_id": principal.business_instance_id, "user_id": principal.user_id, "api_key_id": principal.api_key_id,
              "resource_id": req.vector_store_id, "lvl": principal.max_security_level, "query_hash": query_hash(req.query),
              "metadata": jsonb_param({"top_k": req.top_k, "result_ids": result_ids, **(req.search_metadata or {})})})
        db.execute(jsonb_text("""
            INSERT INTO usage_events(id, tenant_id, business_instance_id, user_id, event_type, quantity, unit, metadata)
            VALUES (:id, :tenant_id, :biz_id, :user_id, 'retrieval.query', 1, 'query', CAST(:metadata AS jsonb))
        """, 'metadata'), {"id": new_id("use"), "tenant_id": principal.tenant_id, "biz_id": principal.business_instance_id, "user_id": principal.user_id,
              "metadata": jsonb_param({"vector_store_id": req.vector_store_id, "top_k": req.top_k, "result_count": len(result_ids)})})
        return aud

    async def context_pack(self, db: Session, principal: Principal, req: ContextPackRequest) -> ContextPackResponse:
        search = await self.search(db, principal, req)
        parts, citations, total = [], [], 0
        for i, ch in enumerate(search.results, start=1):
            t = estimate_tokens(ch.text)
            if total + t > req.max_context_tokens:
                break
            total += t
            parts.append(f"[Source {i}: chunk_id={ch.id} document_id={ch.document_id}]\n{ch.text}")
            citations.append(ContextCitation(chunk_id=ch.id, document_id=ch.document_id, page_start=ch.page_start, page_end=ch.page_end, heading_path=ch.heading_path))
        return ContextPackResponse(query=req.query, context="\n\n---\n\n".join(parts), citations=citations, chunks=search.results[:len(citations)], token_estimate=total, audit_event_id=search.audit_event_id)
