from __future__ import annotations
from collections import OrderedDict, defaultdict
from typing import Any
import math
import re
import httpx
from sqlalchemy import text
from sqlalchemy.orm import Session
from .sql import jsonb_text
from .db import jsonb_param
from .schemas import SearchRequest, SearchResponse, ChunkRecord, ContextPackRequest, ContextPackResponse, ContextCitation, RetrievalAnswerRequest, RetrievalAnswerResponse, Principal
from .security import build_retrieval_scope, build_qdrant_filter, chunk_allowed_by_scope
from .providers import provider_for
from .providers import ProviderConfigurationError
from .model_registry import resolve_embedding_profile, retrieval_profiles, model_registry
from .openai_compat import (
    OPENAI_CITATION_MARKER_RE,
    chunk_file_citation,
    openai_annotation_from_citation,
    openai_file_citation_marker,
    openai_file_citation_marker_at,
    openai_message_file_citation_annotation,
    openai_model_citation_marker,
    openai_model_citation_source_id,
    output_guard_text,
    validate_openai_file_citation_annotation,
)
from .qdrant_adapter import QdrantAdapter
from .opensearch_adapter import OpenSearchAdapter
from .hashing import query_hash, sha256_text
from .ids import new_id
from .chunking import estimate_tokens
from .config import get_settings

QUERY_EMBEDDING_CACHE_MAX = 2048
LOCAL_LEXICAL_RERANKER = "local_lexical_overlap_v1"
LOCAL_LEXICAL_RERANK_STRATEGY = "candidate_idf_phrase_v1"
MODEL_GATEWAY_RERANKER = "model_gateway_rerank_v1"
MODEL_GATEWAY_RERANKERS = {MODEL_GATEWAY_RERANKER, "model_gateway"}


def _answer_snippet(text: str, max_chars: int = 700) -> str:
    without_existing_markers = OPENAI_CITATION_MARKER_RE.sub("", text)
    collapsed = re.sub(r"\s+", " ", without_existing_markers).strip()
    if len(collapsed) <= max_chars:
        return collapsed
    return collapsed[:max_chars].rstrip() + "..."


def _merge_output_guard_metadata(guards: list[dict[str, Any]]) -> dict[str, Any] | None:
    redactions: dict[str, int] = {}
    for guard in guards:
        if not isinstance(guard, dict):
            continue
        for redaction in guard.get("redactions") or []:
            if not isinstance(redaction, dict):
                continue
            kind = redaction.get("type")
            count = redaction.get("count")
            if isinstance(kind, str) and isinstance(count, int):
                redactions[kind] = redactions.get(kind, 0) + count
    if not redactions:
        return None
    return {
        "id": "pii_secret_citation_guard_v1",
        "redactions": [{"type": kind, "count": redactions[kind]} for kind in sorted(redactions)],
    }


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def _openai_model_locator_for_chunk(chunk: ChunkRecord) -> str | None:
    metadata = chunk.metadata or {}
    line_start = _positive_int(metadata.get("line_start"))
    line_end = _positive_int(metadata.get("line_end"))
    if line_start is None:
        return None
    if line_end is None or line_end < line_start:
        line_end = line_start
    if line_start == line_end:
        return f"L{line_start}"
    return f"L{line_start}-L{line_end}"


def ensure_retrieval_answer_citation_integrity(answer: str, citations: list[ContextCitation]) -> None:
    visible_markers = [match.group(0) for match in OPENAI_CITATION_MARKER_RE.finditer(answer)]
    expected_markers: list[str] = []
    for index, citation in enumerate(citations):
        marker = citation.marker
        if not marker:
            raise ValueError(f"answer citation {index} requires a visible marker")
        annotation = validate_openai_file_citation_annotation(
            citation.annotation or {},
            context=f"answer citation {index}",
        )
        annotation_index = annotation.get("index")
        actual_marker = openai_file_citation_marker_at(
            answer,
            annotation_index,
            context=f"answer citation {index}",
            text_label="answer text",
        )
        if actual_marker != marker:
            raise ValueError(f"answer citation {index} annotation index does not point at its marker")
        expected_message_annotation = openai_message_file_citation_annotation(
            annotation=annotation,
            start_index=annotation_index,
            end_index=annotation_index + len(actual_marker),
            text=actual_marker,
        )
        if citation.message_annotation is not None:
            if hasattr(citation.message_annotation, "model_dump"):
                raw_message_annotation = citation.message_annotation.model_dump(mode="python")
            else:
                raw_message_annotation = citation.message_annotation
            if raw_message_annotation != expected_message_annotation:
                raise ValueError(f"answer citation {index} message annotation does not match output text")
        expected_markers.append(marker)
    if visible_markers != expected_markers:
        raise ValueError("answer citation markers must match citations exactly")
DISABLED_RERANKERS = {"", "none", "disabled", "disabled_by_default"}
LEXICAL_MMR_DIVERSITY = "lexical_mmr_v1"
DISABLED_DIVERSITY = {"", "none", "disabled", "disabled_by_default"}
RERANK_TOKEN_RE = re.compile(r"[a-z0-9]+")
EXACT_SYMBOL_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./:-]{2,}")
RERANK_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "how",
    "in", "is", "it", "of", "on", "or", "the", "to", "was", "what", "when",
    "where", "which", "who", "why", "with",
}
FILTER_COLUMNS = (
    ("vector_store_id", "c.vector_store_id"),
    ("knowledge_base_id", "c.knowledge_base_id"),
    ("document_id", "c.document_id"),
    ("classification", "c.classification"),
    ("acl_bucket", "c.acl_bucket"),
)
RANGE_SQL_OPERATORS = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


def _has_file_attribute_filters(filters: dict | None) -> bool:
    filters = filters or {}
    return bool(
        filters.get("file_attribute_filters")
        or filters.get("file_attribute_filter_any")
        or filters.get("file_attribute_ranges")
        or filters.get("file_attribute_not_filters")
        or filters.get("file_attribute_not_any")
    )


def _append_file_attribute_filter_sql(
    extra: list[str],
    params: dict[str, object],
    filters: dict,
    *,
    param_prefix: str,
    alias: str = "vsf",
) -> None:
    file_attrs = filters.get("file_attribute_filters") or {}
    if file_attrs:
        param_name = f"{param_prefix}_exact"
        extra.append(f"AND {alias}.attributes @> CAST(:{param_name} AS jsonb)")
        params[param_name] = jsonb_param(file_attrs)

    any_options = filters.get("file_attribute_filter_any") or []
    if any_options:
        clauses = []
        for index, option in enumerate(any_options):
            if not option:
                continue
            param_name = f"{param_prefix}_any_{index}"
            clauses.append(f"{alias}.attributes @> CAST(:{param_name} AS jsonb)")
            params[param_name] = jsonb_param(option)
        if clauses:
            extra.append(f"AND ({' OR '.join(clauses)})")

    for index, not_filter in enumerate(filters.get("file_attribute_not_filters") or []):
        key = str(not_filter["key"])
        key_param = f"{param_prefix}_not_{index}_key"
        value_param = f"{param_prefix}_not_{index}_value"
        params[key_param] = key
        params[value_param] = jsonb_param({key: not_filter["value"]})
        extra.append(f"AND {alias}.attributes ? :{key_param}")
        extra.append(f"AND NOT ({alias}.attributes @> CAST(:{value_param} AS jsonb))")

    for index, not_any_filter in enumerate(filters.get("file_attribute_not_any") or []):
        key = str(not_any_filter["key"])
        values = list(not_any_filter.get("values") or [])
        key_param = f"{param_prefix}_not_any_{index}_key"
        params[key_param] = key
        clauses = []
        for value_index, value in enumerate(values):
            value_param = f"{param_prefix}_not_any_{index}_value_{value_index}"
            params[value_param] = jsonb_param({key: value})
            clauses.append(f"{alias}.attributes @> CAST(:{value_param} AS jsonb)")
        extra.append(f"AND {alias}.attributes ? :{key_param}")
        if clauses:
            extra.append(f"AND NOT ({' OR '.join(clauses)})")

    for index, range_filter in enumerate(filters.get("file_attribute_ranges") or []):
        key = str(range_filter["key"])
        op = RANGE_SQL_OPERATORS[str(range_filter["op"])]
        value = range_filter["value"]
        key_param = f"{param_prefix}_range_{index}_key"
        value_param = f"{param_prefix}_range_{index}_value"
        params[key_param] = key
        params[value_param] = value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            extra.append(
                "AND ("
                f"CASE WHEN jsonb_typeof({alias}.attributes -> :{key_param}) = 'number' "
                f"THEN ({alias}.attributes ->> :{key_param})::numeric ELSE NULL END "
                f"{op} :{value_param}"
                ")"
            )
        else:
            extra.append(
                "AND ("
                f"CASE WHEN jsonb_typeof({alias}.attributes -> :{key_param}) = 'string' "
                f"THEN {alias}.attributes ->> :{key_param} ELSE NULL END "
                f"{op} :{value_param}"
                ")"
            )


def _append_column_filter_sql(extra: list[str], params: dict[str, object], filters: dict) -> None:
    for key, col in FILTER_COLUMNS:
        if filters.get(key):
            extra.append(f"AND {col}=:{key}")
            params[key] = filters[key]

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

    def _filters_for_request(self, req: SearchRequest) -> dict:
        filters = dict(req.filters or {})
        if req.vector_store_id:
            filters["vector_store_id"] = req.vector_store_id
        if req.knowledge_base_id:
            filters["knowledge_base_id"] = req.knowledge_base_id
        return filters

    def _effective_profile_for_search(self, profile: dict, search_metadata: dict | None = None) -> dict:
        compat = (search_metadata or {}).get("openai_compat") if isinstance(search_metadata, dict) else None
        ranker = compat.get("ranker") if isinstance(compat, dict) else None
        if ranker != "none":
            return profile
        effective = dict(profile)
        effective["reranker"] = "none"
        effective["diversity"] = "none"
        effective["_rerank_disabled_by"] = "openai_ranking_options.ranker"
        effective["_requested_ranker"] = "none"
        return effective

    async def search(self, db: Session, principal: Principal, req: SearchRequest) -> SearchResponse:
        scope = build_retrieval_scope(principal)
        profile_id = req.retrieval_profile_id or "hybrid_rrf_secure_v2"
        profile = self._effective_profile_for_search(retrieval_profiles().get(profile_id, {}), req.search_metadata)
        filters = self._filters_for_request(req)

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
        dense_weight, sparse_weight, fusion_audit = self._fusion_weights(profile, req.search_metadata)
        fused = reciprocal_rank_fusion([dense, sparse], int(profile.get("rrf_k", 60)), [dense_weight, sparse_weight])
        fused = fused[: int(profile.get("fused_top_k", max(req.top_k * 2, 20)))]
        hydrate_limit = max(
            req.top_k,
            int(profile.get("context_top_k", req.top_k)),
            int(profile.get("rerank_candidate_top_k", req.top_k)),
        )
        chunks = self._hydrate_and_acl(db, principal, fused, hydrate_limit, filters)
        chunks, symbol_boost_audit = self._apply_exact_symbol_boost(chunks, req.query, profile, req.top_k)
        chunks, rerank_audit = await self._rerank_chunks(chunks, req.query, profile, req.top_k)
        audit_id = self._audit(
            db,
            principal,
            req,
            [c.id for c in chunks[:req.top_k]],
            {
                "retrieval_profile_id": profile_id,
                "fusion": fusion_audit,
                "exact_symbol_boost": symbol_boost_audit,
                "rerank": rerank_audit,
            },
        )
        return SearchResponse(query=req.query, results=chunks[:req.top_k], audit_event_id=audit_id, retrieval_profile_id=profile_id)

    def _embedding_profiles_for_search(self, db: Session, scope, req: SearchRequest, filters: dict) -> list[str]:
        params = {"tenant_id": scope.tenant_id, "biz_id": scope.business_instance_id, "max_lvl": scope.max_security_level}
        extra = []
        join_file_attrs = ""
        if _has_file_attribute_filters(filters):
            join_file_attrs = """
            JOIN vector_store_files vsf
              ON vsf.document_id=c.document_id
             AND vsf.vector_store_id=c.vector_store_id
             AND vsf.tenant_id=c.tenant_id
             AND vsf.business_instance_id=c.business_instance_id
            """
            _append_file_attribute_filter_sql(extra, params, filters, param_prefix="profile_file_attr")
        _append_column_filter_sql(extra, params, filters)
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
        if profile_ids:
            return profile_ids
        if req.vector_store_id or filters.get("vector_store_id") or req.knowledge_base_id or filters.get("knowledge_base_id"):
            return []
        return [resolve_embedding_profile(req.mode or "markdown_docs_v1", scope.max_security_level)]

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

    def _fusion_weights(self, profile: dict, search_metadata: dict | None = None) -> tuple[float, float, dict]:
        dense_weight = float(profile.get("dense_weight", 1.0))
        sparse_weight = float(profile.get("sparse_weight", 1.0))
        source = "retrieval_profile"
        compat = (search_metadata or {}).get("openai_compat") if isinstance(search_metadata, dict) else None
        hybrid = compat.get("hybrid_search") if isinstance(compat, dict) else None
        if isinstance(hybrid, dict) and hybrid:
            if hybrid.get("embedding_weight") is not None:
                dense_weight = float(hybrid["embedding_weight"])
            if hybrid.get("text_weight") is not None:
                sparse_weight = float(hybrid["text_weight"])
            if dense_weight < 0 or sparse_weight < 0:
                raise ProviderConfigurationError("hybrid_search weights must be non-negative")
            if dense_weight <= 0 and sparse_weight <= 0:
                raise ProviderConfigurationError("hybrid_search requires dense or sparse weight greater than zero")
            source = "openai_ranking_options.hybrid_search"
        return dense_weight, sparse_weight, {
            "dense_weight": dense_weight,
            "sparse_weight": sparse_weight,
            "source": source,
        }

    def _postgres_sparse_search(self, db: Session, scope, query: str, filters: dict, limit: int) -> list[dict]:
        """Small-cell sparse retrieval fallback using Postgres generated tsvector."""
        params = {"tenant_id": scope.tenant_id, "biz_id": scope.business_instance_id, "max_lvl": scope.max_security_level, "query": query, "limit": limit}
        extra = []
        join_file_attrs = ""
        if _has_file_attribute_filters(filters):
            join_file_attrs = """
            JOIN vector_store_files vsf
              ON vsf.document_id=c.document_id
             AND vsf.vector_store_id=c.vector_store_id
             AND vsf.tenant_id=c.tenant_id
             AND vsf.business_instance_id=c.business_instance_id
            """
            _append_file_attribute_filter_sql(extra, params, filters, param_prefix="sparse_file_attr")
        _append_column_filter_sql(extra, params, filters)
        rows = db.execute(jsonb_text(f"""
            SELECT c.id, c.document_id, c.document_version_id,
                   ts_rank_cd(search_vector, websearch_to_tsquery('english', :query)) AS score
            FROM chunks c
            {join_file_attrs}
            WHERE c.tenant_id=:tenant_id AND c.business_instance_id=:biz_id AND c.active=true
              AND c.security_level <= :max_lvl
              AND c.search_vector @@ websearch_to_tsquery('english', :query)
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
        params = {
            "ids": ids,
            "tenant_id": principal.tenant_id,
            "biz_id": principal.business_instance_id,
            "max_lvl": principal.max_security_level,
            "citation_vs_id": filters.get("vector_store_id"),
        }
        join_file_attrs = ""
        extra = []
        if _has_file_attribute_filters(filters):
            join_file_attrs = """
            JOIN vector_store_files vsf
              ON vsf.document_id=c.document_id
             AND vsf.vector_store_id=c.vector_store_id
             AND vsf.tenant_id=c.tenant_id
             AND vsf.business_instance_id=c.business_instance_id
            """
            _append_file_attribute_filter_sql(extra, params, filters, param_prefix="hydrate_file_attr")
        rows = db.execute(jsonb_text(f"""
            SELECT c.id, c.document_id, c.document_version_id, c.ordinal, c.text, c.heading_path, c.page_start, c.page_end,
                   c.metadata, c.security_level, c.classification, c.allowed_groups, c.allowed_roles,
                   d.title, d.filename, d.source_uri, cite.file_id
            FROM chunks c
            {join_file_attrs}
            JOIN documents d
              ON d.id=c.document_id
             AND d.tenant_id=c.tenant_id
             AND d.business_instance_id=c.business_instance_id
            LEFT JOIN document_versions dv
              ON dv.id=d.current_version_id
             AND dv.document_id=d.id
             AND dv.tenant_id=d.tenant_id
             AND dv.business_instance_id=d.business_instance_id
            LEFT JOIN LATERAL (
                SELECT coalesce(
                    f.attributes->>'attached_from_file_id',
                    dv.metadata #>> '{{attributes,_openai_file_id}}',
                    f.document_id,
                    f.id
                ) AS file_id
                FROM vector_store_files f
                WHERE f.tenant_id=c.tenant_id
                  AND f.business_instance_id=c.business_instance_id
                  AND f.document_id=c.document_id
                  AND f.status <> 'cancelled'
                  AND (
                    f.vector_store_id=c.vector_store_id
                    OR (CAST(:citation_vs_id AS text) IS NOT NULL AND f.vector_store_id=CAST(:citation_vs_id AS text))
                  )
                ORDER BY f.created_at DESC
                LIMIT 1
            ) cite ON true
            WHERE c.id = ANY(:ids) AND c.tenant_id=:tenant_id AND c.business_instance_id=:biz_id
              AND c.active=true AND c.security_level <= :max_lvl
              {' '.join(extra)}
        """, "file_attr_filter"), params).mappings().all()
        score_map = {x.get("payload", {}).get("chunk_id") or x["id"]: x.get("score", 0.0) for x in fused}
        by_id = {}
        for r in rows:
            ch = ChunkRecord(
                id=r["id"], document_id=r["document_id"], document_version_id=r["document_version_id"],
                file_id=r["file_id"], title=r["title"], filename=r["filename"], source_uri=r["source_uri"],
                ordinal=r["ordinal"], text=r["text"], heading_path=list(r["heading_path"] or []),
                page_start=r["page_start"], page_end=r["page_end"], metadata=dict(r["metadata"] or {}),
                security_level=r["security_level"], classification=r["classification"],
                allowed_groups=list(r["allowed_groups"] or []), allowed_roles=list(r["allowed_roles"] or []),
                score=float(score_map.get(r["id"], 0.0)), source="hybrid_rrf",
            )
            citation = chunk_file_citation(ch)
            ch.annotations.append(openai_annotation_from_citation(citation))
            ch.citation = citation
            if chunk_allowed_by_scope(ch, scope):
                by_id[ch.id] = ch
        return [by_id[i] for i in ids if i in by_id][:limit]

    def _query_exact_symbols(self, query: str, *, max_symbols: int = 32) -> list[str]:
        symbols: list[str] = []
        seen: set[str] = set()
        for raw in EXACT_SYMBOL_TOKEN_RE.findall(query or ""):
            token = raw.strip("`'\"()[]{}<>,")
            if len(token) < 3:
                continue
            lower = token.lower()
            if lower in RERANK_STOPWORDS:
                continue
            has_symbol_char = any(char in token for char in "_./:-")
            has_digit = any(char.isdigit() for char in token)
            has_upper = any(char.isupper() for char in token)
            has_lower = any(char.islower() for char in token)
            is_all_caps = token.upper() == token and has_upper
            is_mixed_case_symbol = has_upper and has_lower and token != token.capitalize()
            if not (has_symbol_char or has_digit or is_all_caps or is_mixed_case_symbol):
                continue
            if lower in seen:
                continue
            seen.add(lower)
            symbols.append(token)
            if len(symbols) >= max_symbols:
                break
        return symbols

    def _chunk_symbol_haystack(self, chunk: ChunkRecord) -> str:
        metadata = chunk.metadata or {}
        metadata_terms: list[str] = []
        for key, value in metadata.items():
            if isinstance(key, str):
                metadata_terms.append(key)
            if isinstance(value, (str, int, float, bool)):
                metadata_terms.append(str(value))
        return "\n".join(
            value
            for value in [
                chunk.text,
                chunk.title or "",
                chunk.filename or "",
                chunk.source_uri or "",
                " ".join(chunk.heading_path or []),
                " ".join(metadata_terms),
            ]
            if value
        )

    def _symbol_matches_chunk(self, symbol: str, chunk: ChunkRecord) -> bool:
        haystack = self._chunk_symbol_haystack(chunk)
        if not haystack:
            return False
        if "/" in symbol:
            return symbol.lower() in haystack.lower()
        pattern = re.compile(
            rf"(?<![A-Za-z0-9_./:-]){re.escape(symbol)}(?![A-Za-z0-9_./:-])",
            re.I,
        )
        return bool(pattern.search(haystack))

    def _apply_exact_symbol_boost(
        self,
        chunks: list[ChunkRecord],
        query: str,
        profile: dict,
        top_k: int,
    ) -> tuple[list[ChunkRecord], dict]:
        boost = float(profile.get("exact_symbol_boost") or 0.0)
        audit: dict[str, Any] = {
            "enabled": False,
            "boost": boost,
            "candidate_count": len(chunks),
            "result_count": min(len(chunks), top_k),
        }
        if boost <= 0 or len(chunks) <= 1:
            return chunks, audit

        symbols = self._query_exact_symbols(query)
        audit["symbols"] = symbols
        if not symbols:
            audit["reason"] = "no_exact_symbol_terms"
            return chunks, audit

        scored: list[tuple[float, float, int, ChunkRecord, list[str]]] = []
        boosted_count = 0
        for index, chunk in enumerate(chunks):
            matches = [symbol for symbol in symbols if self._symbol_matches_chunk(symbol, chunk)]
            base_score = float(chunk.score or 0.0)
            boosted_score = base_score
            if matches:
                coverage = len(matches) / max(len(symbols), 1)
                boosted_score = base_score + (boost * coverage)
                boosted_count += 1
                chunk.score = round(boosted_score, 6)
                chunk.source = "hybrid_rrf_symbol_boost"
                if chunk.citation:
                    citation = dict(chunk.citation)
                    citation.update({
                        "exact_symbol_boost": boost,
                        "exact_symbol_matches": matches,
                        "exact_symbol_match_count": len(matches),
                        "exact_symbol_base_score": round(base_score, 6),
                        "exact_symbol_score": chunk.score,
                    })
                    chunk.citation = citation
                    chunk.annotations = [openai_annotation_from_citation(citation)]
            scored.append((boosted_score, base_score, -index, chunk, matches))

        if boosted_count <= 0:
            audit.update({"enabled": True, "boosted_count": 0})
            return chunks, audit

        scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        ranked = [chunk for _, _, _, chunk, _ in scored]
        matched_symbols = sorted({symbol for _, _, _, _, matches in scored for symbol in matches})
        audit.update({
            "enabled": True,
            "boosted_count": boosted_count,
            "matched_symbols": matched_symbols,
        })
        return ranked, audit

    async def _rerank_chunks(
        self,
        chunks: list[ChunkRecord],
        query: str,
        profile: dict,
        top_k: int,
    ) -> tuple[list[ChunkRecord], dict]:
        reranker = str(profile.get("reranker") or "disabled").strip()
        candidate_top_k = max(1, int(profile.get("rerank_candidate_top_k", max(top_k * 2, 20))))
        candidate_count = min(len(chunks), candidate_top_k)
        base_audit = {
            "enabled": False,
            "reranker": reranker or "disabled",
            "candidate_count": candidate_count,
            "result_count": min(len(chunks), top_k),
        }
        if profile.get("_rerank_disabled_by"):
            base_audit["source"] = profile["_rerank_disabled_by"]
            base_audit["requested_ranker"] = profile.get("_requested_ranker")
        if reranker.lower() in DISABLED_RERANKERS or candidate_count <= 1:
            return chunks, base_audit

        rerank_weight = self._profile_float(profile, "rerank_weight", 0.65)
        fusion_weight = self._profile_float(profile, "rerank_fusion_weight", 0.35)
        if rerank_weight <= 0 and fusion_weight <= 0:
            raise ProviderConfigurationError("rerank_weight and rerank_fusion_weight cannot both be zero")

        candidates = chunks[:candidate_count]
        remainder = chunks[candidate_count:]
        if reranker == LOCAL_LEXICAL_RERANKER:
            rerank_scores = self._local_lexical_rerank_scores(query, [ch.text for ch in candidates], profile)
            reranker_provider = "local"
            reranker_model = LOCAL_LEXICAL_RERANKER
        elif reranker in MODEL_GATEWAY_RERANKERS:
            rerank_scores, gateway_meta = await self._model_gateway_rerank_scores(
                query,
                [ch.text for ch in candidates],
                profile,
                candidate_count,
            )
            reranker_provider = gateway_meta.get("provider") or "model_gateway"
            reranker_model = gateway_meta.get("model") or str(profile.get("reranker_profile_id") or reranker)
        else:
            raise ProviderConfigurationError(f"Unsupported retrieval reranker: {reranker}")

        return self._apply_rerank_scores(
            candidates,
            remainder,
            rerank_scores,
            reranker=reranker,
            reranker_provider=reranker_provider,
            reranker_model=reranker_model,
            rerank_weight=rerank_weight,
            fusion_weight=fusion_weight,
            top_k=top_k,
            profile=profile,
        )

    async def _model_gateway_rerank_scores(
        self,
        query: str,
        documents: list[str],
        profile: dict,
        top_n: int,
    ) -> tuple[list[float], dict]:
        base_url = str(getattr(self.settings, "model_gateway_url", "") or "").rstrip("/")
        if not base_url:
            raise ProviderConfigurationError("model-gateway reranker requires MODEL_GATEWAY_URL")
        payload = {
            "query": query,
            "documents": documents,
            "model_profile_id": profile.get("reranker_profile_id") or profile.get("model_profile_id") or profile.get("reranker"),
            "top_n": top_n,
        }
        timeout = float(profile.get("rerank_timeout_sec", 30))
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(f"{base_url}/internal/models/rerank", json=payload)
                response.raise_for_status()
                body = response.json()
            scores = [0.0] * len(documents)
            for item in body.get("results") or []:
                index = int(item["index"])
                if 0 <= index < len(scores):
                    scores[index] = float(item["relevance_score"])
            return scores, {"provider": body.get("provider"), "model": body.get("model")}
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise ProviderConfigurationError(f"model-gateway reranker failed: {exc}") from exc

    def _apply_rerank_scores(
        self,
        candidates: list[ChunkRecord],
        remainder: list[ChunkRecord],
        rerank_scores: list[float],
        *,
        reranker: str,
        reranker_provider: str,
        reranker_model: str,
        rerank_weight: float,
        fusion_weight: float,
        top_k: int,
        profile: dict,
    ) -> tuple[list[ChunkRecord], dict]:
        max_fusion_score = max((float(ch.score or 0.0) for ch in candidates), default=0.0)
        scored: list[tuple[float, float, float, int, ChunkRecord]] = []
        for index, ch in enumerate(candidates):
            fusion_score = float(ch.score or 0.0)
            normalized_fusion = fusion_score / max_fusion_score if max_fusion_score > 0 else 0.0
            rerank_score = float(rerank_scores[index]) if index < len(rerank_scores) else 0.0
            combined = (rerank_weight * rerank_score) + (fusion_weight * normalized_fusion)
            scored.append((combined, rerank_score, normalized_fusion, index, ch))

        scored.sort(key=lambda item: (item[0], item[1], item[2], -item[3]), reverse=True)
        ranked: list[ChunkRecord] = []
        for combined, rerank_score, normalized_fusion, _, ch in scored:
            ch.score = round(combined, 6)
            ch.source = "hybrid_rrf_rerank"
            if ch.citation:
                citation = dict(ch.citation)
                citation.update({
                    "score": ch.score,
                    "rerank_score": round(rerank_score, 6),
                    "fusion_score": round(normalized_fusion, 6),
                    "reranker": reranker,
                    "reranker_provider": reranker_provider,
                    "reranker_model": reranker_model,
                })
                ch.citation = citation
                ch.annotations = [openai_annotation_from_citation(citation)]
            ranked.append(ch)

        ranked, diversity_audit = self._apply_diversity_selection(ranked, profile, top_k)
        audit = {
            "enabled": True,
            "reranker": reranker,
            "candidate_count": len(candidates),
            "result_count": min(len(ranked), top_k),
            "rerank_weight": rerank_weight,
            "fusion_weight": fusion_weight,
            "reranker_provider": reranker_provider,
            "reranker_model": reranker_model,
        }
        if reranker == LOCAL_LEXICAL_RERANKER:
            audit["reranker_strategy"] = LOCAL_LEXICAL_RERANK_STRATEGY
        if diversity_audit:
            audit["diversity"] = diversity_audit
        return ranked + remainder, audit

    def _profile_float(self, profile: dict, key: str, default: float) -> float:
        value = float(profile.get(key, default))
        return max(0.0, min(value, 1.0))

    def _local_lexical_rerank_scores(self, query: str, documents: list[str], profile: dict) -> list[float]:
        query_tokens = self._rerank_tokens(query)
        if not query_tokens:
            return [0.0 for _ in documents]
        query_terms = list(dict.fromkeys(query_tokens))
        document_tokens = [self._rerank_tokens(document) for document in documents]
        document_sets = [set(tokens) for tokens in document_tokens]
        candidate_count = max(len(documents), 1)
        idf: dict[str, float] = {}
        for token in query_terms:
            doc_frequency = sum(1 for tokens in document_sets if token in tokens)
            idf[token] = math.log((1 + candidate_count) / (1 + doc_frequency)) + 1.0
        total_idf = sum(idf.values()) or 1.0
        return [
            self._local_lexical_rerank_score_from_tokens(
                query_tokens=query_tokens,
                query_terms=query_terms,
                doc_tokens=tokens,
                idf=idf,
                total_idf=total_idf,
                profile=profile,
            )
            for tokens in document_tokens
        ]

    def _local_lexical_rerank_score(
        self,
        query: str,
        text_value: str,
        profile: dict,
    ) -> float:
        return self._local_lexical_rerank_scores(query, [text_value], profile)[0]

    def _local_lexical_rerank_score_from_tokens(
        self,
        *,
        query_tokens: list[str],
        query_terms: list[str],
        doc_tokens: list[str],
        idf: dict[str, float],
        total_idf: float,
        profile: dict,
    ) -> float:
        if not doc_tokens:
            return 0.0
        doc_set = set(doc_tokens)
        weighted_coverage = sum(idf[token] for token in query_terms if token in doc_set) / total_idf
        query_hits = sum(1 for token in doc_tokens if token in idf)
        density_window = max(1, min(len(doc_tokens), len(query_terms) * 8))
        density = min(1.0, query_hits / density_window)
        ordered_pair_score = self._ordered_query_pair_score(query_tokens, doc_tokens)
        proximity_score = self._query_proximity_score(query_terms, doc_tokens)
        exact_bonus = self._profile_float(profile, "rerank_exact_phrase_bonus", 0.2)
        phrase = " ".join(query_tokens)
        doc_text = " ".join(doc_tokens)
        phrase_bonus = exact_bonus if phrase and phrase in doc_text else 0.0
        return min(
            1.0,
            (weighted_coverage * 0.72)
            + (density * 0.10)
            + (ordered_pair_score * 0.10)
            + (proximity_score * 0.08)
            + phrase_bonus,
        )

    def _ordered_query_pair_score(self, query_tokens: list[str], doc_tokens: list[str]) -> float:
        query_pairs = list(zip(query_tokens, query_tokens[1:]))
        if not query_pairs or len(doc_tokens) < 2:
            return 0.0
        doc_pairs = set(zip(doc_tokens, doc_tokens[1:]))
        return sum(1 for pair in query_pairs if pair in doc_pairs) / len(query_pairs)

    def _query_proximity_score(self, query_terms: list[str], doc_tokens: list[str]) -> float:
        doc_set = set(doc_tokens)
        required = {token for token in query_terms if token in doc_set}
        if len(required) <= 1:
            return 0.0
        counts: dict[str, int] = defaultdict(int)
        have = 0
        best_window: int | None = None
        left = 0
        for right, token in enumerate(doc_tokens):
            if token in required:
                if counts[token] == 0:
                    have += 1
                counts[token] += 1
            while have == len(required) and left <= right:
                window = right - left + 1
                best_window = window if best_window is None else min(best_window, window)
                left_token = doc_tokens[left]
                if left_token in required:
                    counts[left_token] -= 1
                    if counts[left_token] == 0:
                        have -= 1
                left += 1
        if not best_window:
            return 0.0
        return min(1.0, len(required) / best_window)

    def _rerank_tokens(self, value: str) -> list[str]:
        return [token for token in RERANK_TOKEN_RE.findall((value or "").lower()) if token not in RERANK_STOPWORDS]

    def _apply_diversity_selection(
        self,
        ranked: list[ChunkRecord],
        profile: dict,
        top_k: int,
    ) -> tuple[list[ChunkRecord], dict | None]:
        diversity = str(profile.get("diversity") or "disabled").strip()
        if diversity.lower() in DISABLED_DIVERSITY or len(ranked) <= 1 or top_k <= 1:
            return ranked, None
        if diversity != LEXICAL_MMR_DIVERSITY:
            raise ProviderConfigurationError(f"Unsupported retrieval diversity selector: {diversity}")

        selection_count = min(len(ranked), top_k)
        mmr_lambda = self._profile_float(profile, "diversity_lambda", 0.82)
        remaining = list(enumerate(ranked))
        selected: list[tuple[int, ChunkRecord, float, float]] = []

        first_index, first_chunk = remaining.pop(0)
        selected.append((first_index, first_chunk, float(first_chunk.score or 0.0), 0.0))
        while remaining and len(selected) < selection_count:
            selected_chunks = [chunk for _, chunk, _, _ in selected]
            best_position = 0
            best_key: tuple[float, float, float, int] | None = None
            best_score = 0.0
            best_similarity = 0.0
            for position, (original_index, chunk) in enumerate(remaining):
                relevance = float(chunk.score or 0.0)
                similarity = max((self._chunk_lexical_similarity(chunk, existing) for existing in selected_chunks), default=0.0)
                mmr_score = (mmr_lambda * relevance) - ((1.0 - mmr_lambda) * similarity)
                key = (mmr_score, relevance, -similarity, -original_index)
                if best_key is None or key > best_key:
                    best_position = position
                    best_key = key
                    best_score = mmr_score
                    best_similarity = similarity
            original_index, chunk = remaining.pop(best_position)
            selected.append((original_index, chunk, best_score, best_similarity))

        selected_indices = {index for index, _, _, _ in selected}
        selected_chunks: list[ChunkRecord] = []
        for rank, (_, chunk, diversity_score, similarity) in enumerate(selected, start=1):
            if chunk.citation:
                citation = dict(chunk.citation)
                citation.update({
                    "diversity_method": diversity,
                    "diversity_rank": rank,
                    "diversity_score": round(diversity_score, 6),
                    "diversity_similarity": round(similarity, 6),
                    "diversity_lambda": mmr_lambda,
                })
                chunk.citation = citation
                chunk.annotations = [openai_annotation_from_citation(citation)]
            selected_chunks.append(chunk)

        reordered = selected_chunks + [chunk for index, chunk in enumerate(ranked) if index not in selected_indices]
        return reordered, {
            "enabled": True,
            "method": diversity,
            "lambda": mmr_lambda,
            "candidate_count": len(ranked),
            "selected_count": len(selected_chunks),
            "result_count": selection_count,
        }

    def _chunk_lexical_similarity(self, left: ChunkRecord, right: ChunkRecord) -> float:
        left_tokens = set(self._rerank_tokens(left.text))
        right_tokens = set(self._rerank_tokens(right.text))
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens.intersection(right_tokens)) / len(left_tokens.union(right_tokens))

    def _context_neighbor_window(self, profile: dict) -> tuple[int, int]:
        expand = profile.get("expand_neighbors")
        if not expand:
            return 0, 0
        if isinstance(expand, dict):
            before = max(0, int(expand.get("before", 0) or 0))
            after = max(0, int(expand.get("after", 0) or 0))
            return before, after
        window = max(0, int(profile.get("neighbor_window", 0) or 0))
        return window, window

    def _context_chunk_from_row(self, row, *, source: str, score: float | None = None) -> ChunkRecord:
        return ChunkRecord(
            id=row["id"], document_id=row["document_id"], document_version_id=row["document_version_id"],
            file_id=row["file_id"], title=row["title"], filename=row["filename"], source_uri=row["source_uri"],
            ordinal=row["ordinal"], text=row["text"], heading_path=list(row["heading_path"] or []),
            page_start=row["page_start"], page_end=row["page_end"], metadata=dict(row["metadata"] or {}),
            security_level=row["security_level"], classification=row["classification"],
            allowed_groups=list(row["allowed_groups"] or []), allowed_roles=list(row["allowed_roles"] or []),
            score=score, source=source,
        )

    def _contextualize_chunk(
        self,
        chunk: ChunkRecord,
        relation: str,
        direct_hit: ChunkRecord,
        offset: int,
        extra_citation: dict | None = None,
    ) -> ChunkRecord:
        contextual = chunk.model_copy(deep=True)
        if relation == "parent_section":
            contextual.source = "context_parent_section"
        elif relation != "direct":
            contextual.source = "context_neighbor"
        citation = dict(contextual.citation or chunk_file_citation(contextual))
        citation.update({
            "context_relation": relation,
            "source_chunk_id": direct_hit.id,
            "neighbor_offset": offset,
        })
        if extra_citation:
            citation.update(extra_citation)
        contextual.citation = citation
        contextual.annotations = [openai_annotation_from_citation(citation)]
        return contextual

    def _expand_context_neighbors(
        self,
        db: Session,
        principal: Principal,
        chunks: list[ChunkRecord],
        profile: dict,
        filters: dict | None = None,
    ) -> list[ChunkRecord]:
        before, after = self._context_neighbor_window(profile)
        if not chunks or (before <= 0 and after <= 0):
            return chunks

        scope = build_retrieval_scope(principal)
        filters = filters or {}
        params: dict[str, object] = {
            "tenant_id": principal.tenant_id,
            "biz_id": principal.business_instance_id,
            "max_lvl": principal.max_security_level,
            "citation_vs_id": filters.get("vector_store_id"),
        }
        ranges = []
        for index, chunk in enumerate(chunks):
            params[f"doc_{index}"] = chunk.document_id
            params[f"start_{index}"] = max(0, int(chunk.ordinal) - before)
            params[f"end_{index}"] = int(chunk.ordinal) + after
            ranges.append(f"(c.document_id=:doc_{index} AND c.ordinal BETWEEN :start_{index} AND :end_{index})")
        if not ranges:
            return chunks

        join_file_attrs = ""
        extra = []
        if _has_file_attribute_filters(filters):
            join_file_attrs = """
            JOIN vector_store_files vsf
              ON vsf.document_id=c.document_id
             AND vsf.vector_store_id=c.vector_store_id
             AND vsf.tenant_id=c.tenant_id
             AND vsf.business_instance_id=c.business_instance_id
            """
            _append_file_attribute_filter_sql(extra, params, filters, param_prefix="neighbor_file_attr")
        _append_column_filter_sql(extra, params, filters)

        rows = db.execute(jsonb_text(f"""
            SELECT c.id, c.document_id, c.document_version_id, c.ordinal, c.text, c.heading_path, c.page_start, c.page_end,
                   c.metadata, c.security_level, c.classification, c.allowed_groups, c.allowed_roles,
                   d.title, d.filename, d.source_uri, cite.file_id
            FROM chunks c
            {join_file_attrs}
            JOIN documents d
              ON d.id=c.document_id
             AND d.tenant_id=c.tenant_id
             AND d.business_instance_id=c.business_instance_id
            LEFT JOIN document_versions dv
              ON dv.id=d.current_version_id
             AND dv.document_id=d.id
             AND dv.tenant_id=d.tenant_id
             AND dv.business_instance_id=d.business_instance_id
            LEFT JOIN LATERAL (
                SELECT coalesce(
                    f.attributes->>'attached_from_file_id',
                    dv.metadata #>> '{{attributes,_openai_file_id}}',
                    f.document_id,
                    f.id
                ) AS file_id
                FROM vector_store_files f
                WHERE f.tenant_id=c.tenant_id
                  AND f.business_instance_id=c.business_instance_id
                  AND f.document_id=c.document_id
                  AND f.status <> 'cancelled'
                  AND (
                    f.vector_store_id=c.vector_store_id
                    OR (CAST(:citation_vs_id AS text) IS NOT NULL AND f.vector_store_id=CAST(:citation_vs_id AS text))
                  )
                ORDER BY f.created_at DESC
                LIMIT 1
            ) cite ON true
            WHERE c.tenant_id=:tenant_id AND c.business_instance_id=:biz_id
              AND c.active=true AND c.security_level <= :max_lvl
              AND ({' OR '.join(ranges)})
              {' '.join(extra)}
            ORDER BY c.document_id ASC, c.ordinal ASC
        """, "file_attr_filter"), params).mappings().all()

        by_doc_ordinal: dict[tuple[str, int], ChunkRecord] = {}
        for r in rows:
            neighbor = self._context_chunk_from_row(r, source="context_neighbor")
            citation = chunk_file_citation(neighbor)
            neighbor.citation = citation
            neighbor.annotations = [openai_annotation_from_citation(citation)]
            if chunk_allowed_by_scope(neighbor, scope):
                by_doc_ordinal[(neighbor.document_id, neighbor.ordinal)] = neighbor

        expanded: list[ChunkRecord] = []
        seen: set[str] = set()
        for direct in chunks:
            for offset in range(-before, after + 1):
                relation = "direct"
                candidate = direct
                if offset < 0:
                    relation = "neighbor_before"
                    candidate = by_doc_ordinal.get((direct.document_id, direct.ordinal + offset))
                elif offset > 0:
                    relation = "neighbor_after"
                    candidate = by_doc_ordinal.get((direct.document_id, direct.ordinal + offset))
                if candidate is None or candidate.id in seen:
                    continue
                seen.add(candidate.id)
                expanded.append(self._contextualize_chunk(candidate, relation, direct, offset))
        return expanded

    def _parent_heading_prefix(self, chunk: ChunkRecord) -> list[str]:
        heading = list(chunk.heading_path or [])
        if len(heading) <= 1:
            return heading
        return heading[:-1]

    def _expand_context_parent_sections(
        self,
        db: Session,
        principal: Principal,
        chunks: list[ChunkRecord],
        profile: dict,
        filters: dict | None = None,
    ) -> list[ChunkRecord]:
        if not chunks or not profile.get("expand_parent_sections"):
            return chunks

        parent_specs: list[tuple[ChunkRecord, list[str]]] = []
        prefix_by_chunk_id: dict[str, list[str]] = {}
        for chunk in chunks:
            prefix = self._parent_heading_prefix(chunk)
            if prefix:
                parent_specs.append((chunk, prefix))
                prefix_by_chunk_id[chunk.id] = prefix
        if not parent_specs:
            return chunks

        scope = build_retrieval_scope(principal)
        filters = filters or {}
        params: dict[str, object] = {
            "tenant_id": principal.tenant_id,
            "biz_id": principal.business_instance_id,
            "max_lvl": principal.max_security_level,
            "citation_vs_id": filters.get("vector_store_id"),
            "parent_limit": max(1, int(profile.get("parent_section_max_chunks", profile.get("context_top_k", 12)))) * len(parent_specs),
        }
        parent_clauses = []
        for spec_index, (chunk, prefix) in enumerate(parent_specs):
            params[f"parent_doc_{spec_index}"] = chunk.document_id
            params[f"parent_depth_{spec_index}"] = len(prefix)
            heading_checks = [f"c.heading_path[{level + 1}]=:parent_heading_{spec_index}_{level}" for level in range(len(prefix))]
            for level, heading in enumerate(prefix):
                params[f"parent_heading_{spec_index}_{level}"] = heading
            parent_clauses.append(
                "("
                f"c.document_id=:parent_doc_{spec_index} "
                f"AND array_length(c.heading_path, 1) >= :parent_depth_{spec_index} "
                f"AND {' AND '.join(heading_checks)}"
                ")"
            )

        join_file_attrs = ""
        extra = []
        if _has_file_attribute_filters(filters):
            join_file_attrs = """
            JOIN vector_store_files vsf
              ON vsf.document_id=c.document_id
             AND vsf.vector_store_id=c.vector_store_id
             AND vsf.tenant_id=c.tenant_id
             AND vsf.business_instance_id=c.business_instance_id
            """
            _append_file_attribute_filter_sql(extra, params, filters, param_prefix="parent_file_attr")
        _append_column_filter_sql(extra, params, filters)

        rows = db.execute(jsonb_text(f"""
            SELECT c.id, c.document_id, c.document_version_id, c.ordinal, c.text, c.heading_path, c.page_start, c.page_end,
                   c.metadata, c.security_level, c.classification, c.allowed_groups, c.allowed_roles,
                   d.title, d.filename, d.source_uri, cite.file_id
            FROM chunks c
            {join_file_attrs}
            JOIN documents d
              ON d.id=c.document_id
             AND d.tenant_id=c.tenant_id
             AND d.business_instance_id=c.business_instance_id
            LEFT JOIN document_versions dv
              ON dv.id=d.current_version_id
             AND dv.document_id=d.id
             AND dv.tenant_id=d.tenant_id
             AND dv.business_instance_id=d.business_instance_id
            LEFT JOIN LATERAL (
                SELECT coalesce(
                    f.attributes->>'attached_from_file_id',
                    dv.metadata #>> '{{attributes,_openai_file_id}}',
                    f.document_id,
                    f.id
                ) AS file_id
                FROM vector_store_files f
                WHERE f.tenant_id=c.tenant_id
                  AND f.business_instance_id=c.business_instance_id
                  AND f.document_id=c.document_id
                  AND f.status <> 'cancelled'
                  AND (
                    f.vector_store_id=c.vector_store_id
                    OR (CAST(:citation_vs_id AS text) IS NOT NULL AND f.vector_store_id=CAST(:citation_vs_id AS text))
                  )
                ORDER BY f.created_at DESC
                LIMIT 1
            ) cite ON true
            WHERE c.tenant_id=:tenant_id AND c.business_instance_id=:biz_id
              AND c.active=true AND c.security_level <= :max_lvl
              AND ({' OR '.join(parent_clauses)})
              {' '.join(extra)}
            ORDER BY c.document_id ASC, c.ordinal ASC
            LIMIT :parent_limit
        """, "file_attr_filter"), params).mappings().all()

        parent_candidates = []
        for r in rows:
            parent_chunk = self._context_chunk_from_row(r, source="context_parent_section")
            citation = chunk_file_citation(parent_chunk)
            parent_chunk.citation = citation
            parent_chunk.annotations = [openai_annotation_from_citation(citation)]
            if chunk_allowed_by_scope(parent_chunk, scope):
                parent_candidates.append(parent_chunk)

        expanded: list[ChunkRecord] = []
        seen: set[str] = set()
        for direct in chunks:
            prefix = prefix_by_chunk_id.get(direct.id)
            if not prefix:
                if direct.id not in seen:
                    seen.add(direct.id)
                    expanded.append(self._contextualize_chunk(direct, "direct", direct, 0))
                continue
            for candidate in sorted(parent_candidates, key=lambda ch: (ch.document_id, ch.ordinal)):
                if candidate.id in seen or candidate.document_id != direct.document_id:
                    continue
                if candidate.heading_path[:len(prefix)] != prefix:
                    continue
                seen.add(candidate.id)
                relation = "direct" if candidate.id == direct.id else "parent_section"
                expanded.append(self._contextualize_chunk(
                    candidate,
                    relation,
                    direct,
                    candidate.ordinal - direct.ordinal,
                    {"parent_heading_path": prefix},
                ))
            if direct.id not in seen:
                seen.add(direct.id)
                expanded.append(self._contextualize_chunk(
                    direct,
                    "direct",
                    direct,
                    0,
                    {"parent_heading_path": prefix},
                ))
        return expanded

    def _merge_context_expansions(
        self,
        direct_chunks: list[ChunkRecord],
        *expanded_lists: list[ChunkRecord],
    ) -> list[ChunkRecord]:
        direct_ids = {chunk.id for chunk in direct_chunks}
        buckets: dict[str, list[ChunkRecord]] = {chunk.id: [] for chunk in direct_chunks}
        for expanded in expanded_lists:
            for chunk in expanded:
                source_id = (chunk.citation or {}).get("source_chunk_id")
                if source_id not in buckets and chunk.id in direct_ids:
                    source_id = chunk.id
                if source_id in buckets:
                    buckets[source_id].append(chunk)

        merged: list[ChunkRecord] = []
        seen: set[str] = set()
        for direct in direct_chunks:
            candidates = buckets.get(direct.id) or [direct]
            for candidate in candidates:
                if candidate.id in seen:
                    continue
                seen.add(candidate.id)
                merged.append(candidate)
        return merged

    def _audit(
        self,
        db: Session,
        principal: Principal,
        req: SearchRequest,
        result_ids: list[str],
        retrieval_metadata: dict | None = None,
    ) -> str:
        aud = new_id("aud")
        metadata = {"top_k": req.top_k, "result_ids": result_ids, **(req.search_metadata or {})}
        if retrieval_metadata:
            metadata.update(retrieval_metadata)
        db.execute(jsonb_text("""
            INSERT INTO audit_events(id, tenant_id, business_instance_id, user_id, api_key_id, event_type, action, resource_type,
              resource_id, security_level, query_hash, metadata)
            VALUES (:id, :tenant_id, :biz_id, :user_id, :api_key_id, 'retrieval', 'search', 'vector_store',
              :resource_id, :lvl, :query_hash, CAST(:metadata AS jsonb))
        """, 'metadata'), {"id": aud, "tenant_id": principal.tenant_id, "biz_id": principal.business_instance_id, "user_id": principal.user_id, "api_key_id": principal.api_key_id,
              "resource_id": req.vector_store_id, "lvl": principal.max_security_level, "query_hash": query_hash(req.query),
              "metadata": jsonb_param(metadata)})
        db.execute(jsonb_text("""
            INSERT INTO usage_events(id, tenant_id, business_instance_id, user_id, api_key_id, event_type, quantity, unit, metadata)
            VALUES (:id, :tenant_id, :biz_id, :user_id, :api_key_id, 'retrieval.query', 1, 'query', CAST(:metadata AS jsonb))
        """, 'metadata'), {"id": new_id("use"), "tenant_id": principal.tenant_id, "biz_id": principal.business_instance_id, "user_id": principal.user_id,
              "api_key_id": principal.api_key_id,
              "metadata": jsonb_param({"vector_store_id": req.vector_store_id, "top_k": req.top_k, "result_count": len(result_ids)})})
        return aud

    async def context_pack(self, db: Session, principal: Principal, req: ContextPackRequest) -> ContextPackResponse:
        search = await self.search(db, principal, req)
        profile = retrieval_profiles().get(search.retrieval_profile_id or req.retrieval_profile_id or "hybrid_rrf_secure_v2", {})
        filters = self._filters_for_request(req)
        parent_enabled = bool(profile.get("expand_parent_sections"))
        neighbor_before, neighbor_after = self._context_neighbor_window(profile)
        neighbor_enabled = neighbor_before > 0 or neighbor_after > 0
        context_chunks = search.results
        parent_chunks = self._expand_context_parent_sections(db, principal, search.results, profile, filters) if parent_enabled else []
        neighbor_chunks = self._expand_context_neighbors(db, principal, search.results, profile, filters) if neighbor_enabled else []
        if parent_enabled and neighbor_enabled:
            context_chunks = self._merge_context_expansions(search.results, parent_chunks, neighbor_chunks)
        elif parent_enabled:
            context_chunks = parent_chunks
        elif neighbor_enabled:
            context_chunks = neighbor_chunks
        parts, citations, total = [], [], 0
        context_separator = "\n\n---\n\n"
        included_chunks = []
        for i, ch in enumerate(context_chunks, start=1):
            t = estimate_tokens(ch.text)
            if total + t > req.max_context_tokens:
                break
            total += t
            citation = dict(ch.citation or chunk_file_citation(ch))
            marker = openai_file_citation_marker(i)
            model_source_id = openai_model_citation_source_id(i - 1)
            model_locator = _openai_model_locator_for_chunk(ch)
            model_marker = openai_model_citation_marker(model_source_id, locator=model_locator)
            source_label = (
                f"[Source {i}: file_id={citation['file_id']} filename={citation['filename']} "
                f"chunk_id={ch.id} document_id={ch.document_id} model_source_id={model_source_id}]"
            )
            model_marker_line = f"Citation Marker: {model_marker}"
            chunk_text = ch.text or ""
            marker_separator = "" if not chunk_text or chunk_text[-1].isspace() else " "
            part_without_marker = f"{source_label}\n{model_marker_line}\n{chunk_text}"
            context_offset = sum(len(part) for part in parts) + len(context_separator) * len(parts)
            marker_index = context_offset + len(part_without_marker) + len(marker_separator)
            citation["index"] = marker_index
            citation["marker"] = marker
            annotation = openai_annotation_from_citation(citation)
            message_annotation = openai_message_file_citation_annotation(
                annotation=annotation,
                start_index=marker_index,
                end_index=marker_index + len(marker),
                text=marker,
            )
            parts.append(f"{part_without_marker}{marker_separator}{marker}")
            included_chunks.append(ch)
            citations.append(ContextCitation(
                chunk_id=ch.id,
                document_id=ch.document_id,
                file_id=citation["file_id"],
                title=citation.get("title"),
                filename=citation["filename"],
                url=citation.get("url"),
                page_start=ch.page_start,
                page_end=ch.page_end,
                heading_path=ch.heading_path,
                annotation=annotation,
                message_annotation=message_annotation,
                marker=marker,
                model_source_id=model_source_id,
                model_marker=model_marker,
                model_locator=model_locator,
                context_relation=citation.get("context_relation"),
                source_chunk_id=citation.get("source_chunk_id"),
                neighbor_offset=citation.get("neighbor_offset"),
                parent_heading_path=list(citation.get("parent_heading_path") or []),
            ))
        return ContextPackResponse(query=req.query, context=context_separator.join(parts), citations=citations, chunks=included_chunks, token_estimate=total, audit_event_id=search.audit_event_id)

    async def answer(self, db: Session, principal: Principal, req: RetrievalAnswerRequest) -> RetrievalAnswerResponse:
        context = await self.context_pack(db, principal, req)
        cited_chunks: list[ChunkRecord] = []
        answer_citations: list[ContextCitation] = []
        output_guards: list[dict[str, Any]] = []
        if not context.chunks:
            answer_text = "No matching vector store content found."
        else:
            answer_parts = ["Answer from retrieved sources:"]
            answer_separator = "\n"
            for chunk, context_citation in zip(context.chunks, context.citations, strict=True):
                if len(answer_citations) >= req.max_answer_sources:
                    break
                guarded_text, output_guard = output_guard_text(chunk.text or "")
                snippet = _answer_snippet(guarded_text)
                if not snippet:
                    continue
                if output_guard:
                    output_guards.append(output_guard)
                marker = openai_file_citation_marker(len(answer_citations) + 1)
                marker_separator = "" if snippet[-1].isspace() else " "
                line_without_marker = f"- {snippet}"
                answer_offset = sum(len(part) for part in answer_parts) + len(answer_separator) * len(answer_parts)
                marker_index = answer_offset + len(line_without_marker) + len(marker_separator)
                file_id = context_citation.file_id or chunk.file_id or chunk.document_id
                filename = context_citation.filename or chunk.filename or chunk.title or chunk.document_id
                model_source_id = context_citation.model_source_id
                model_locator = context_citation.model_locator
                model_marker = context_citation.model_marker
                if not model_source_id or not model_marker:
                    model_source_id = model_source_id or openai_model_citation_source_id(len(answer_citations))
                    model_marker = openai_model_citation_marker(model_source_id, locator=model_locator)
                annotation = {
                    "type": "file_citation",
                    "index": marker_index,
                    "file_id": str(file_id),
                    "filename": str(filename),
                }
                message_annotation = openai_message_file_citation_annotation(
                    annotation=annotation,
                    start_index=marker_index,
                    end_index=marker_index + len(marker),
                    text=marker,
                )
                answer_parts.append(f"{line_without_marker}{marker_separator}{marker}")
                answer_citations.append(context_citation.model_copy(update={
                    "annotation": annotation,
                    "message_annotation": message_annotation,
                    "marker": marker,
                    "model_source_id": model_source_id,
                    "model_marker": model_marker,
                    "model_locator": model_locator,
                }))
                cited_chunks.append(chunk)
            answer_text = answer_separator.join(answer_parts) if answer_citations else "No matching vector store content found."
        ensure_retrieval_answer_citation_integrity(answer_text, answer_citations)
        output_guard = _merge_output_guard_metadata(output_guards)
        return RetrievalAnswerResponse(
            query=req.query,
            answer=answer_text,
            citations=answer_citations,
            chunks=cited_chunks,
            context=context.context,
            answer_style=req.answer_style,
            token_estimate=context.token_estimate + estimate_tokens(answer_text),
            audit_event_id=context.audit_event_id,
            output_guard=output_guard,
        )
