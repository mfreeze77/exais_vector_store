from __future__ import annotations
from enum import IntEnum
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator

class SecurityLevel(IntEnum):
    PUBLIC = 0
    TENANT_PRIVATE = 1
    TEAM_RESTRICTED = 2
    CONFIDENTIAL = 3
    REGULATED = 4
    ISOLATED = 5

class Principal(BaseModel):
    tenant_id: str
    business_instance_id: str
    user_id: str | None = None
    api_key_id: str | None = None
    roles: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    max_security_level: int = 1
    scopes: list[str] = Field(default_factory=list)

class RetrievalScope(BaseModel):
    tenant_id: str
    business_instance_id: str
    user_id: str | None = None
    groups: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    max_security_level: int = 1
    allowed_knowledge_base_ids: list[str] = Field(default_factory=list)
    allowed_vector_store_ids: list[str] = Field(default_factory=list)

class VectorStoreCreateRequest(BaseModel):
    name: str
    knowledge_base_id: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] | None = None
    expires_after: dict[str, Any] | None = None

class VectorStoreResponse(BaseModel):
    id: str
    object: str = 'vector_store'
    name: str
    status: str = 'completed'
    usage_bytes: int = 0
    attributes: dict[str, Any] = Field(default_factory=dict)
    created_at: int | None = None
    expires_after: dict[str, Any] | None = None
    expires_at: int | None = None
    last_active_at: int | None = None

class DocumentIngestRequest(BaseModel):
    vector_store_id: str | None = None
    knowledge_base_id: str | None = None
    title: str
    filename: str | None = None
    mime_type: str | None = None
    content: str
    mode: str = 'auto_detect_v1'
    source_uri: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    security_level: int = 1
    classification: str = 'tenant_private'
    allowed_groups: list[str] = Field(default_factory=list)
    allowed_roles: list[str] = Field(default_factory=list)
    source_trust: str = 'user_upload'

    @field_validator('security_level')
    @classmethod
    def validate_level(cls, v: int) -> int:
        if v < 0 or v > 5:
            raise ValueError('security_level must be 0..5')
        return v

class IngestionJobResponse(BaseModel):
    id: str
    status: str
    document_id: str | None = None
    vector_store_file_id: str | None = None

class IngestionJobDetail(BaseModel):
    id: str
    status: str
    job_type: str
    attempts: int = 0
    max_attempts: int = 3
    last_error: str | None = None
    document_id: str | None = None
    vector_store_file_id: str | None = None
    created_at: int | None = None
    updated_at: int | None = None
    completed_at: int | None = None

class ChunkRecord(BaseModel):
    id: str
    document_id: str
    document_version_id: str | None = None
    ordinal: int
    text: str
    heading_path: list[str] = Field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    security_level: int = 1
    classification: str = 'tenant_private'
    allowed_groups: list[str] = Field(default_factory=list)
    allowed_roles: list[str] = Field(default_factory=list)
    score: float | None = None
    source: str | None = None

class SearchRequest(BaseModel):
    query: str
    vector_store_id: str | None = None
    knowledge_base_id: str | None = None
    retrieval_profile_id: str | None = None
    mode: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    top_k: int = 10
    include_content: bool = True
    include_metadata: bool = True
    search_metadata: dict[str, Any] = Field(default_factory=dict)

class SearchResponse(BaseModel):
    query: str
    results: list[ChunkRecord]
    audit_event_id: str | None = None
    retrieval_profile_id: str | None = None

class OpenAIVectorStoreRankingOptions(BaseModel):
    model_config = ConfigDict(extra='forbid')

    ranker: Literal['none', 'auto', 'default-2024-11-15'] = 'auto'
    score_threshold: float | None = Field(default=None, ge=0, le=1)

class OpenAIVectorStoreSearchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    query: str
    filters: dict[str, Any] | None = None
    # Historical ExAIS planning docs used attribute_filter. Keep it as a
    # compatibility alias while preferring OpenAI's filters field.
    attribute_filter: dict[str, Any] | None = None
    max_num_results: int = Field(default=10, ge=1, le=50)
    top_k: int | None = Field(default=None, ge=1, le=50)
    ranking_options: OpenAIVectorStoreRankingOptions | None = None
    rewrite_query: bool = False
    retrieval_profile_id: str | None = None
    mode: str | None = None
    include_content: bool = True
    include_metadata: bool = True

class ContextPackRequest(SearchRequest):
    max_context_tokens: int = 6000
    require_citations: bool = True

class ContextCitation(BaseModel):
    chunk_id: str
    document_id: str
    title: str | None = None
    filename: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    heading_path: list[str] = Field(default_factory=list)

class ContextPackResponse(BaseModel):
    query: str
    context: str
    citations: list[ContextCitation]
    chunks: list[ChunkRecord]
    token_estimate: int
    audit_event_id: str | None = None

class EmbeddingRequest(BaseModel):
    input: list[str] | str
    model_profile_id: str | None = None
    model: str | None = None
    dimensions: int | None = None
    security_level: int = 1
    provider: str | None = None
    input_type: Literal['query', 'document'] | None = None

class EmbeddingData(BaseModel):
    object: str = 'embedding'
    embedding: list[float]
    index: int

class EmbeddingResponse(BaseModel):
    object: str = 'list'
    data: list[EmbeddingData]
    model: str
    provider: str
    dimensions: int
    usage: dict[str, int | float] = Field(default_factory=dict)

class RerankRequest(BaseModel):
    query: str
    documents: list[str]
    model_profile_id: str | None = None
    top_n: int | None = None

class RerankResult(BaseModel):
    index: int
    relevance_score: float

class RerankResponse(BaseModel):
    results: list[RerankResult]
    model: str
    provider: str

class TokenizeRequest(BaseModel):
    text: str
    model_profile_id: str | None = None
    model: str | None = None

class TokenizeResponse(BaseModel):
    tokens: int
    model: str | None = None
    method: str

class ModelEndpointRequest(BaseModel):
    name: str
    provider: str
    kind: Literal['embedding', 'reranker', 'tokenizer', 'multimodal'] = 'embedding'
    base_url: str | None = None
    model: str | None = None
    dimensions: int | None = None
    privacy: str = 'external_api'
    security_max_level: int = 3
    status: str = 'active'
    config: dict[str, Any] = Field(default_factory=dict)

class ModelEndpointResponse(ModelEndpointRequest):
    id: str
    created_at: int | None = None
    updated_at: int | None = None

class IngestionPreviewRequest(DocumentIngestRequest):
    persist: bool = True

class ModelCandidate(BaseModel):
    model_profile_id: str
    provider: str
    model: str | None = None
    dimensions: int | None = None
    privacy: str = 'unknown'
    configured: bool = True
    required_env: list[str] = Field(default_factory=list)
    score: float = 0.0
    allowed: bool = True
    reasons: list[str] = Field(default_factory=list)

class IngestionPlanResponse(BaseModel):
    id: str | None = None
    mode: str
    parser: str | None = None
    chunker: str | None = None
    embedding_profile_id: str
    retrieval_profile_id: str
    candidates: list[ModelCandidate] = Field(default_factory=list)
    estimated_tokens: int
    estimated_chunks: int
    warnings: list[str] = Field(default_factory=list)
    persisted: bool = False

class BakeoffRunRequest(BaseModel):
    name: str
    mode: str = 'markdown_docs_v1'
    model_profile_ids: list[str]
    queries: list[dict[str, Any]] = Field(default_factory=list)
    top_k: int = 10

class BakeoffRunResponse(BaseModel):
    id: str
    status: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    results: list[dict[str, Any]] = Field(default_factory=list)

class ReindexRequest(BaseModel):
    vector_store_id: str | None = None
    document_id: str | None = None
    after_chunk_id: str | None = None
    batch_size: int | None = None
    force: bool = False

class MaintenanceResult(BaseModel):
    ok: bool = True
    action: str
    processed: int = 0
    details: dict[str, Any] = Field(default_factory=dict)

class InstanceManifest(BaseModel):
    apiVersion: str = 'svs/v1'
    kind: str = 'Instance'
    metadata: dict[str, Any]
    product: dict[str, Any]
    runtime: dict[str, Any] = Field(default_factory=dict)
    storage: dict[str, Any] = Field(default_factory=dict)
    security: dict[str, Any] = Field(default_factory=dict)
    retrieval: dict[str, Any] = Field(default_factory=dict)
    models: dict[str, Any] = Field(default_factory=dict)
    backups: dict[str, Any] = Field(default_factory=dict)
