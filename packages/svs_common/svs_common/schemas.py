from __future__ import annotations
from datetime import datetime
from enum import IntEnum
from typing import Annotated, Any, Literal, get_args
from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, PrivateAttr, RootModel, field_validator, model_validator
from .openai_metadata import validate_openai_metadata
from .secrets import parse_secret_reference

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
    # WAVE-125: caller-side identifier of the bound user, when the API key is
    # bound to a caller-provisioned user with an external_id.
    external_id: str | None = None


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra='allow')

    ok: bool
    service: str
    version: str
    sparse_backend: str
    dense_backend: str


class ReadinessResponse(BaseModel):
    model_config = ConfigDict(extra='allow')

    ready: bool
    db: bool | None = None
    qdrant: bool | None = None


class PrometheusMetricsResponse(RootModel[str]):
    pass


class OpenAIFileContentResponse(RootModel[str]):
    pass


class VectorizationModesResponse(BaseModel):
    modes: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ModelRegistryResponse(BaseModel):
    model_config = ConfigDict(extra='allow')

    models: dict[str, dict[str, Any]] = Field(default_factory=dict)
    rerankers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    policies: dict[str, Any] = Field(default_factory=dict)


class RetrievalProfilesResponse(BaseModel):
    profiles: dict[str, dict[str, Any]] = Field(default_factory=dict)

class RetrievalScope(BaseModel):
    tenant_id: str
    business_instance_id: str
    user_id: str | None = None
    groups: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    max_security_level: int = 1
    allowed_knowledge_base_ids: list[str] = Field(default_factory=list)
    allowed_vector_store_ids: list[str] = Field(default_factory=list)


def _validate_vector_store_expires_after(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError('expires_after must be an object')
    extra_fields = sorted(set(value) - {'anchor', 'days'})
    if extra_fields:
        raise ValueError('expires_after supports only anchor and days')
    if value.get('anchor') != 'last_active_at':
        raise ValueError("expires_after.anchor must be 'last_active_at'")
    days = value.get('days')
    if isinstance(days, bool) or not isinstance(days, int) or days <= 0:
        raise ValueError('expires_after.days must be a positive integer')
    return {'anchor': 'last_active_at', 'days': days}


def _validate_vector_store_metadata(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    return validate_openai_metadata(value, context='vector store metadata')


def validate_openai_chunking_strategy(value: Any, *, context: str = 'chunking_strategy') -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f'{context} must be an object')
    kind = value.get('type')
    if kind == 'auto':
        extra_fields = sorted(set(value) - {'type'})
        if extra_fields:
            raise ValueError(f'{context} auto strategy supports only type')
        return {'type': 'auto'}
    if kind != 'static':
        raise ValueError(f"{context}.type must be 'auto' or 'static'")

    allowed_fields = {'type', 'max_chunk_size_tokens', 'chunk_overlap_tokens'}
    extra_fields = sorted(set(value) - allowed_fields)
    if extra_fields:
        raise ValueError(f'{context} static strategy supports only type, max_chunk_size_tokens, and chunk_overlap_tokens')

    normalized: dict[str, Any] = {'type': 'static'}
    max_tokens = value.get('max_chunk_size_tokens')
    if max_tokens is not None:
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 100 or max_tokens > 4096:
            raise ValueError(f'{context}.max_chunk_size_tokens must be between 100 and 4096 inclusive')
        normalized['max_chunk_size_tokens'] = max_tokens

    overlap_tokens = value.get('chunk_overlap_tokens')
    if overlap_tokens is not None:
        if isinstance(overlap_tokens, bool) or not isinstance(overlap_tokens, int) or overlap_tokens < 0:
            raise ValueError(f'{context}.chunk_overlap_tokens must be a non-negative integer')
        effective_max = max_tokens if max_tokens is not None else 800
        if overlap_tokens > effective_max / 2:
            raise ValueError(f'{context}.chunk_overlap_tokens must not exceed max_chunk_size_tokens / 2')
        normalized['chunk_overlap_tokens'] = overlap_tokens
    return normalized


class VectorStoreCreateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: str | None = None
    description: str | None = None
    file_ids: list[str] = Field(default_factory=list)
    knowledge_base_id: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] | None = None
    expires_after: dict[str, Any] | None = None
    chunking_strategy: dict[str, Any] | None = None

    @field_validator('expires_after', mode='before')
    @classmethod
    def validate_expires_after(cls, value: Any) -> dict[str, Any] | None:
        return _validate_vector_store_expires_after(value)

    @field_validator('attributes', 'metadata', mode='before')
    @classmethod
    def validate_metadata(cls, value: Any) -> dict[str, str] | None:
        return _validate_vector_store_metadata(value)

    @field_validator('chunking_strategy', mode='before')
    @classmethod
    def validate_chunking_strategy(cls, value: Any) -> dict[str, Any] | None:
        return validate_openai_chunking_strategy(value)

class VectorStoreUpdateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: str | None = None
    description: str | None = None
    attributes: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    expires_after: dict[str, Any] | None = None
    chunking_strategy: dict[str, Any] | None = None

    @field_validator('expires_after', mode='before')
    @classmethod
    def validate_expires_after(cls, value: Any) -> dict[str, Any] | None:
        return _validate_vector_store_expires_after(value)

    @field_validator('attributes', 'metadata', mode='before')
    @classmethod
    def validate_metadata(cls, value: Any) -> dict[str, str] | None:
        return _validate_vector_store_metadata(value)

    @field_validator('chunking_strategy', mode='before')
    @classmethod
    def validate_chunking_strategy(cls, value: Any) -> dict[str, Any] | None:
        return validate_openai_chunking_strategy(value)


class NullableVectorStoreCreateRequest(RootModel[VectorStoreCreateRequest | None]):
    pass


class NullableVectorStoreUpdateRequest(RootModel[VectorStoreUpdateRequest | None]):
    pass

class VectorStoreResponse(BaseModel):
    id: str
    object: str = 'vector_store'
    name: str | None = None
    description: str | None = None
    status: str = 'completed'
    bytes: int = 0
    usage_bytes: int = 0
    file_counts: dict[str, int] = Field(default_factory=lambda: {'in_progress': 0, 'completed': 0, 'failed': 0, 'cancelled': 0, 'total': 0})
    attributes: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: int | None = None
    expires_after: dict[str, Any] | None = None
    expires_at: int | None = None
    last_active_at: int | None = None


class VectorStoreListResponse(BaseModel):
    model_config = ConfigDict(extra='allow')

    object: str = 'list'
    data: list[VectorStoreResponse] = Field(default_factory=list)
    first_id: str | None = None
    last_id: str | None = None
    has_more: bool = False


class VectorStoreDeletedResponse(BaseModel):
    model_config = ConfigDict(extra='allow')

    id: str
    object: str = 'vector_store.deleted'
    deleted: bool


class OpenAIFile(BaseModel):
    model_config = ConfigDict(extra='allow')

    id: str
    object: str = 'file'
    bytes: int = 0
    created_at: int | None = None
    filename: str
    purpose: str
    expires_at: int | None = None
    status: str | None = None
    status_details: str | None = None


class OpenAIFileListResponse(BaseModel):
    model_config = ConfigDict(extra='allow')

    object: str = 'list'
    data: list[OpenAIFile] = Field(default_factory=list)
    first_id: str | None = None
    last_id: str | None = None
    has_more: bool = False


class OpenAIFileDeletedResponse(BaseModel):
    model_config = ConfigDict(extra='allow')

    id: str
    object: str = 'file'
    deleted: bool


class OpenAIVectorStoreFileLastError(BaseModel):
    model_config = ConfigDict(extra='allow')

    code: str | None = None
    message: str | None = None


class OpenAIVectorStoreFile(BaseModel):
    model_config = ConfigDict(extra='allow')

    id: str
    object: str = 'vector_store.file'
    vector_store_id: str
    status: str | None = None
    usage_bytes: int = 0
    created_at: int | None = None
    last_error: OpenAIVectorStoreFileLastError | dict[str, Any] | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    chunking_strategy: dict[str, Any] | None = None


class OpenAIVectorStoreFileListResponse(BaseModel):
    model_config = ConfigDict(extra='allow')

    object: str = 'list'
    data: list[OpenAIVectorStoreFile] = Field(default_factory=list)
    first_id: str | None = None
    last_id: str | None = None
    has_more: bool = False


class OpenAIVectorStoreFileDeletedResponse(BaseModel):
    model_config = ConfigDict(extra='allow')

    id: str
    object: str = 'vector_store.file.deleted'
    deleted: bool = True


class OpenAIVectorStoreFileContentItem(BaseModel):
    model_config = ConfigDict(extra='allow')

    type: str | None = None
    text: str | None = None
    heading_path: list[str] | None = None
    page_start: int | None = None
    page_end: int | None = None


class OpenAIVectorStoreFileContentResponse(BaseModel):
    model_config = ConfigDict(extra='allow')

    object: str = 'vector_store.file_content'
    data: list[OpenAIVectorStoreFileContentItem] = Field(default_factory=list)
    has_more: bool | None = None
    next_page: str | None = None


class OpenAIVectorStoreFileAttachRequest(BaseModel):
    model_config = ConfigDict(extra='allow')

    file_id: str | None = None
    title: str | None = None
    filename: str | None = None
    mime_type: str | None = None
    content: str | None = None
    mode: str | None = None
    source_uri: str | None = None
    attributes: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    chunking_strategy: dict[str, Any] | None = None
    security_level: int | None = None
    classification: str | None = None
    allowed_groups: list[str] | None = None
    allowed_roles: list[str] | None = None
    source_trust: str | None = None


class OpenAIVectorStoreFileUpdateRequest(BaseModel):
    model_config = ConfigDict(extra='allow')

    attributes: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None


class OpenAIVectorStoreFileBatchCreateRequest(BaseModel):
    model_config = ConfigDict(extra='allow')

    file_ids: list[str] | None = None
    files: list[dict[str, Any]] | None = None
    attributes: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    chunking_strategy: dict[str, Any] | None = None


class OpenAIVectorStoreFileBatchCounts(BaseModel):
    model_config = ConfigDict(extra='allow')

    in_progress: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0
    total: int = 0


class OpenAIVectorStoreFileBatch(BaseModel):
    model_config = ConfigDict(extra='allow')

    id: str
    object: str = 'vector_store.file_batch'
    vector_store_id: str
    status: str
    file_counts: OpenAIVectorStoreFileBatchCounts | dict[str, int]
    created_at: int | None = None
    completed_at: int | None = None


class OpenAIVectorStoreFileBatchFilesPage(BaseModel):
    model_config = ConfigDict(extra='allow')

    object: str = 'list'
    data: list[OpenAIVectorStoreFile] = Field(default_factory=list)
    first_id: str | None = None
    last_id: str | None = None
    has_more: bool = False


class DocumentIngestRequest(BaseModel):
    vector_store_id: str | None = None
    knowledge_base_id: str | None = None
    title: str
    filename: str | None = None
    mime_type: str | None = None
    content: str
    mode: str = 'auto_detect_v1'
    source_uri: str | None = None
    source_identity: str | None = Field(default=None, min_length=1, max_length=512)
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

    @field_validator('source_identity')
    @classmethod
    def validate_source_identity(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError('source_identity must not be blank')
        return value

class IngestionJobResponse(BaseModel):
    id: str
    status: str
    document_id: str | None = None
    vector_store_file_id: str | None = None

class IngestionJobDetail(BaseModel):
    model_config = ConfigDict(extra='allow')

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
    payload: dict[str, Any] = Field(default_factory=dict)


class IngestionJobListResponse(BaseModel):
    object: str = 'list'
    data: list[IngestionJobDetail] = Field(default_factory=list)
    first_id: str | None = None
    last_id: str | None = None
    has_more: bool = False

class ChunkRecord(BaseModel):
    id: str
    document_id: str
    document_version_id: str | None = None
    file_id: str | None = None
    title: str | None = None
    filename: str | None = None
    source_uri: str | None = None
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
    annotations: list[dict[str, Any]] = Field(default_factory=list)
    citation: dict[str, Any] | None = None

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

class OpenAIVectorStoreHybridSearchOptions(BaseModel):
    model_config = ConfigDict(extra='forbid')

    embedding_weight: float | None = Field(default=None, ge=0)
    text_weight: float | None = Field(default=None, ge=0)

    @model_validator(mode='before')
    @classmethod
    def normalize_rrf_aliases(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        if 'rrf_embedding_weight' in normalized and 'embedding_weight' not in normalized:
            normalized['embedding_weight'] = normalized.pop('rrf_embedding_weight')
        if 'rrf_text_weight' in normalized and 'text_weight' not in normalized:
            normalized['text_weight'] = normalized.pop('rrf_text_weight')
        return normalized

    @model_validator(mode='after')
    def require_nonzero_weight(self):
        embedding = self.embedding_weight if self.embedding_weight is not None else 0.0
        text = self.text_weight if self.text_weight is not None else 0.0
        if embedding <= 0 and text <= 0:
            raise ValueError('hybrid_search requires embedding_weight or text_weight greater than zero')
        return self

class OpenAIVectorStoreRankingOptions(BaseModel):
    model_config = ConfigDict(extra='forbid')

    ranker: Literal['none', 'auto', 'default-2024-11-15'] = 'auto'
    score_threshold: float | None = Field(default=None, ge=0, le=1)
    hybrid_search: OpenAIVectorStoreHybridSearchOptions | None = None

class OpenAIVectorStoreSearchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    _graph_expansion_limit: int | None = PrivateAttr(default=None)

    query: str | list[str]
    lens: str | None = None
    inputs: dict[str, Any] | None = None
    filters: dict[str, Any] | None = None
    # Historical ExAIS planning docs used attribute_filter. Keep it as a
    # compatibility alias while preferring OpenAI's filters field.
    attribute_filter: dict[str, Any] | None = None
    max_num_results: int = Field(default=10, ge=1, le=50)
    top_k: int | None = Field(default=None, ge=1, le=50)
    ranking_options: OpenAIVectorStoreRankingOptions | None = None
    rewrite_query: bool = False
    next_page: str | None = None
    retrieval_profile_id: str | None = None
    mode: str | None = None
    include_content: bool = True
    include_metadata: bool = True

    @property
    def graph_expansion_limit(self) -> int | None:
        return self._graph_expansion_limit

    def bind_graph_expansion_limit(self, limit: int) -> OpenAIVectorStoreSearchRequest:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError('graph expansion limit must be a non-negative integer')
        bound = self.model_copy(deep=True)
        bound._graph_expansion_limit = limit
        return bound

    @field_validator('query', mode='before')
    @classmethod
    def validate_query(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        if not value:
            raise ValueError('query array must contain at least one string')
        normalized: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError('query array entries must be strings')
            stripped = item.strip()
            if not stripped:
                raise ValueError('query array entries must be non-empty strings')
            normalized.append(stripped)
        return normalized

    @field_validator('lens')
    @classmethod
    def validate_lens(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError('lens must be a non-empty string')
        return stripped

    @field_validator('inputs')
    @classmethod
    def validate_inputs(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError('inputs must be an object')
        return value


OPENAI_RESPONSES_FILE_SEARCH_DEFAULT_MAX_NUM_RESULTS = 20


class OpenAIResponseFileSearchTool(BaseModel):
    model_config = ConfigDict(extra='allow')

    type: str = Field(default='file_search', description='OpenAI Responses tool type. ExAIS currently implements file_search.')
    vector_store_ids: list[str] = Field(default_factory=list)
    lens: str | None = None
    inputs: dict[str, Any] | None = None
    filters: dict[str, Any] | None = None
    max_num_results: int = Field(default=OPENAI_RESPONSES_FILE_SEARCH_DEFAULT_MAX_NUM_RESULTS, ge=1, le=50)
    ranking_options: dict[str, Any] | None = None


class OpenAIResponseRequest(BaseModel):
    model_config = ConfigDict(extra='allow')

    model: str | None = None
    input: Any = None
    tools: list[OpenAIResponseFileSearchTool] | None = None
    tool_choice: Any = None
    include: list[str] | str | None = None
    previous_response_id: str | None = None
    conversation: Any = None
    instructions: str | None = None
    store: bool | None = None
    stream: Any = Field(default=None, description='Boolean stream flag; compatibility validation is performed by the route.')
    stream_options: dict[str, Any] | None = None
    background: bool | None = None
    metadata: dict[str, Any] | None = None
    max_output_tokens: int | None = None
    max_tool_calls: int | None = None
    parallel_tool_calls: bool | None = None
    reasoning: dict[str, Any] | None = None
    text: dict[str, Any] | None = None
    temperature: float | None = None
    top_p: float | None = None
    truncation: str | None = None
    user: str | None = None

    def to_compat_payload(self) -> dict[str, Any]:
        return self.model_dump(mode='python', exclude_unset=True)


class OpenAIResponseInputTokensRequest(OpenAIResponseRequest):
    pass


class OpenAIResponseCompactRequest(OpenAIResponseRequest):
    pass


class OpenAIFileCitationAnnotation(BaseModel):
    model_config = ConfigDict(extra='forbid')

    type: Literal['file_citation']
    index: int = Field(ge=0)
    file_id: str = Field(min_length=1)
    filename: str = Field(min_length=1)

    @field_validator('file_id', 'filename')
    @classmethod
    def _non_blank_citation_string(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('must be a non-empty string')
        return value


class OpenAIMessageFileCitation(BaseModel):
    model_config = ConfigDict(extra='forbid')

    file_id: str = Field(min_length=1)

    @field_validator('file_id')
    @classmethod
    def _non_blank_file_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('must be a non-empty string')
        return value


class OpenAIMessageFileCitationAnnotation(BaseModel):
    model_config = ConfigDict(extra='forbid')

    type: Literal['file_citation']
    start_index: int = Field(ge=0)
    end_index: int = Field(ge=0)
    text: str = Field(min_length=1)
    file_citation: OpenAIMessageFileCitation

    @model_validator(mode='after')
    def _span_matches_text(self) -> OpenAIMessageFileCitationAnnotation:
        if self.end_index != self.start_index + len(self.text):
            raise ValueError('end_index must equal start_index plus citation text length')
        return self


class OpenAIVectorStoreSearchContent(BaseModel):
    model_config = ConfigDict(extra='allow')

    type: Literal['text']
    text: str = ''
    annotations: list[OpenAIFileCitationAnnotation] = Field(default_factory=list)


class OpenAIVectorStoreSearchCitation(BaseModel):
    model_config = ConfigDict(extra='allow')

    type: str | None = None
    index: int | None = None
    file_id: str | None = None
    filename: str | None = None
    chunk_id: str | None = None
    document_id: str | None = None
    title: str | None = None
    url: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    heading_path: list[str] | None = None
    score: float | None = None
    marker: str | None = None
    start_index: int | None = Field(default=None, ge=0)
    end_index: int | None = Field(default=None, ge=0)
    model_source_id: str | None = None
    model_marker: str | None = None
    annotation: OpenAIFileCitationAnnotation | None = None
    message_annotation: OpenAIMessageFileCitationAnnotation | None = None


class OpenAIVectorStoreSearchResult(BaseModel):
    model_config = ConfigDict(extra='allow')

    file_id: str | None = None
    filename: str | None = None
    score: float | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)
    content: list[OpenAIVectorStoreSearchContent | dict[str, Any]] = Field(default_factory=list)
    annotations: list[OpenAIFileCitationAnnotation] = Field(default_factory=list)
    citation: OpenAIVectorStoreSearchCitation | dict[str, Any] | None = None
    citations: list[OpenAIVectorStoreSearchCitation | dict[str, Any]] = Field(default_factory=list)
    output_guard: dict[str, Any] | None = None


class OpenAIVectorStoreSearchResultsPage(BaseModel):
    model_config = ConfigDict(extra='allow')

    object: str = 'vector_store.search_results.page'
    search_query: str | list[str] | None = None
    search_lens: dict[str, Any] | None = None
    data: list[OpenAIVectorStoreSearchResult] = Field(default_factory=list)
    citations: list[OpenAIVectorStoreSearchCitation | dict[str, Any]] = Field(default_factory=list)
    has_more: bool = False
    next_page: str | None = None


class VectorStoreSearchLens(BaseModel):
    model_config = ConfigDict(extra='allow')

    id: str
    label: str
    description: str
    kind: Literal['semantic', 'graph']
    status: Literal['available', 'disabled', 'empty', 'planned']
    requires_graph: bool = False
    graph_profile_id: str | None = None
    relation_types: list[str] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    coverage: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class VectorStoreSearchLensesResponse(BaseModel):
    object: str = 'vector_store.search_lenses'
    vector_store_id: str
    default_lens: str = 'semantic'
    data: list[VectorStoreSearchLens] = Field(default_factory=list)


class ExpertGraphLens(BaseModel):
    model_config = ConfigDict(extra='forbid')

    id: str
    label: str
    description: str
    graph_profile_id: str | None = None
    relation_types: list[str] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    caveats: list[str] = Field(default_factory=list)


class ExpertVectorStoreBinding(BaseModel):
    model_config = ConfigDict(extra='forbid')

    vector_store_id: str
    name: str
    corpus_kind: str | None = None
    graph_lenses: list[ExpertGraphLens] = Field(default_factory=list)


class ExpertGraphLensPolicy(BaseModel):
    model_config = ConfigDict(extra='forbid')

    allow_automatic_selection: bool = True
    allowed_lens_ids: list[str] = Field(default_factory=list)


class ExpertCitationPolicy(BaseModel):
    model_config = ConfigDict(extra='forbid')

    required: bool = True
    authority: Literal['retrieved_corpus_only'] = 'retrieved_corpus_only'
    preserve_source_urls: bool = True
    preserve_graph_relationships: bool = True
    memory_is_authority: Literal[False] = False


class ExpertModelPolicy(BaseModel):
    model_config = ConfigDict(extra='forbid')

    policy_id: str
    gateway: Literal['model_gateway'] = 'model_gateway'
    preferred_model_profile_id: str | None = None
    fallback_model_profile_ids: list[str] = Field(default_factory=list)
    allow_fallback: bool = True


class ExpertChatMessage(BaseModel):
    model_config = ConfigDict(extra='forbid')

    role: Literal['system', 'user', 'assistant']
    content: str = Field(min_length=1)

    @field_validator('content')
    @classmethod
    def _non_blank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('content must be a non-empty string')
        return value


class ExpertChatCompletionRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    messages: list[ExpertChatMessage] = Field(min_length=1)
    model_policy: ExpertModelPolicy
    security_level: int = Field(default=1, ge=0, le=5)
    max_output_tokens: int = Field(default=1200, ge=1, le=32768)
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)


class ExpertChatUsage(BaseModel):
    model_config = ConfigDict(extra='forbid')

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class ExpertChatAttempt(BaseModel):
    model_config = ConfigDict(extra='forbid')

    model_profile_id: str
    provider: str
    model: str
    status: Literal['unavailable', 'failed', 'succeeded']
    latency_ms: int = Field(default=0, ge=0)
    error_code: str | None = None


class ExpertChatFallback(BaseModel):
    model_config = ConfigDict(extra='forbid')

    occurred: bool = False
    from_model_profile_id: str | None = None
    reason: Literal['preferred_provider_unavailable', 'preferred_provider_failed'] | None = None
    attempts: list[ExpertChatAttempt] = Field(default_factory=list)


class ExpertChatCompletionResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')

    content: str = Field(min_length=1)
    policy_id: str
    requested_model_profile_id: str
    model_profile_id: str
    provider: str
    model: str
    latency_ms: int = Field(ge=0)
    usage: ExpertChatUsage
    finish_reason: str | None = None
    fallback: ExpertChatFallback = Field(default_factory=ExpertChatFallback)


class ExpertToolLimits(BaseModel):
    model_config = ConfigDict(extra='forbid')

    max_retrieval_runs: int = Field(ge=1, le=20)
    max_results_per_run: int = Field(ge=1, le=50)
    max_graph_expansions: int = Field(ge=0, le=20)
    max_context_tokens: int = Field(ge=1)


ExpertCorpus = Literal[
    'statutes',
    'court_decisions',
    'municipal_code',
    'administrative_regulations',
    'legislative_materials',
    'meeting_records',
    'other',
]
EXPERT_CORPUS_KINDS = frozenset(get_args(ExpertCorpus))


class ExpertProfile(BaseModel):
    model_config = ConfigDict(extra='forbid')

    id: str
    object: Literal['expert.profile'] = 'expert.profile'
    label: str
    description: str
    system_prompt: str
    # WAVE-125: caller-defined jurisdiction key (for example `ks:city:topeka`)
    # and the corpus family the expert answers for. Both are declared by the
    # expert registry / WAVE-124 package and are informational for routing;
    # they never widen visibility.
    jurisdiction_key: str | None = None
    corpus: ExpertCorpus | None = None
    vector_stores: list[ExpertVectorStoreBinding] = Field(min_length=1)
    graph_lens_policy: ExpertGraphLensPolicy
    citation_policy: ExpertCitationPolicy
    caveats: list[str] = Field(default_factory=list)
    model_policy: ExpertModelPolicy
    tool_limits: ExpertToolLimits


class ExpertProfileListResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')

    object: Literal['expert.profile.list'] = 'expert.profile.list'
    data: list[ExpertProfile] = Field(default_factory=list)
    first_id: str | None = None
    last_id: str | None = None
    has_more: Literal[False] = False


class ExpertMessage(BaseModel):
    model_config = ConfigDict(extra='forbid')

    id: str
    session_id: str
    role: Literal['system', 'user', 'assistant', 'tool']
    content: Any
    sequence_no: int = Field(ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class ExpertToolCall(BaseModel):
    model_config = ConfigDict(extra='forbid')

    id: str
    session_id: str
    message_id: str | None = None
    tool_name: str
    status: Literal['pending', 'running', 'completed', 'failed'] = 'completed'
    input: dict[str, Any] = Field(default_factory=dict)
    output: Any | None = None
    error: str | None = None
    sequence_no: int = Field(ge=0)
    created_at: datetime | None = None
    completed_at: datetime | None = None


class ExpertRetrievalRun(BaseModel):
    model_config = ConfigDict(extra='forbid')

    id: str
    session_id: str
    message_id: str | None = None
    tool_call_id: str | None = None
    sequence_no: int = Field(ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class ExpertFeedbackRecord(BaseModel):
    model_config = ConfigDict(extra='forbid')

    id: str
    session_id: str
    message_id: str | None = None
    feedback_type: str
    rating: int | None = None
    comment: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


ExpertMemoryType = Literal['retrieval_strategy', 'answer_style', 'preference']
ExpertFeedbackType = Literal['helpful', 'unhelpful', 'correction', 'preference', 'rating', 'other']
EXPERT_FEEDBACK_TYPES = frozenset(get_args(ExpertFeedbackType))


class ExpertMemoryCandidateInput(BaseModel):
    model_config = ConfigDict(extra='forbid')

    memory_type: ExpertMemoryType
    instruction: str = Field(min_length=1, max_length=2_000)
    confidence: float = Field(ge=0.0, le=1.0)

    @field_validator('instruction')
    @classmethod
    def _normalize_memory_instruction(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError('instruction must be a non-empty string')
        return normalized


class ExpertMemoryPolicy(BaseModel):
    model_config = ConfigDict(extra='forbid')

    enabled: bool = True
    allowed_memory_types: list[ExpertMemoryType] = Field(
        default_factory=lambda: ['retrieval_strategy', 'answer_style', 'preference'],
        min_length=1,
    )
    minimum_promotion_confidence: float = Field(default=0.75, ge=0.0, le=1.0)
    max_candidates_per_turn: int = Field(default=3, ge=1, le=10)
    promotion_requires_explicit_opt_in: Literal[True] = True
    memory_is_citation_authority: Literal[False] = False


class ExpertTurnRecord(BaseModel):
    model_config = ConfigDict(extra='forbid')

    session_id: str = Field(min_length=1)
    expert_id: str = Field(min_length=1)
    source_message_id: str | None = None
    source_feedback_id: str | None = None
    memory_candidates: list[ExpertMemoryCandidateInput] = Field(default_factory=list, max_length=10)


class ExpertMemoryEvent(BaseModel):
    model_config = ConfigDict(extra='forbid')

    id: str
    session_id: str
    source_message_id: str | None = None
    source_feedback_id: str | None = None
    event_type: ExpertMemoryType
    status: Literal['candidate', 'promoted', 'rejected', 'deleted'] = 'candidate'
    payload: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    created_at: datetime | None = None
    promoted_at: datetime | None = None
    deleted_at: datetime | None = None


class ExpertFeedbackRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    session_id: str = Field(min_length=1)
    message_id: str | None = None
    external_user_id: str | None = Field(default=None, max_length=255)
    conversation_id: str | None = Field(default=None, max_length=255)
    feedback_type: ExpertFeedbackType
    rating: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = Field(default=None, max_length=8_000)
    memory_candidates: list[ExpertMemoryCandidateInput] = Field(default_factory=list, max_length=3)

    @field_validator('session_id', 'message_id', 'external_user_id', 'conversation_id', 'comment')
    @classmethod
    def _normalize_optional_feedback_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode='after')
    def _require_feedback_content(self):
        if self.rating is None and self.comment is None and not self.memory_candidates:
            raise ValueError('feedback requires a rating, comment, or memory candidate')
        if self.feedback_type == 'rating' and self.rating is None:
            raise ValueError('rating feedback requires rating')
        return self


class ExpertFeedbackResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')

    expert_id: str
    session_id: str
    feedback: ExpertFeedbackRecord
    memory_candidates: list[ExpertMemoryEvent] = Field(default_factory=list)


class ExpertMemoryScopeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    external_user_id: str | None = Field(default=None, max_length=255)
    conversation_id: str | None = Field(default=None, max_length=255)

    @field_validator('external_user_id', 'conversation_id')
    @classmethod
    def _normalize_optional_memory_scope(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ExpertMemoryPromotionRequest(ExpertMemoryScopeRequest):
    confirm: Literal[True]


class ExpertMemoryListResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')

    object: Literal['expert.memory_event.list'] = 'expert.memory_event.list'
    expert_id: str
    session_id: str
    data: list[ExpertMemoryEvent] = Field(default_factory=list)


class ExpertMemoryDeletedResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')

    id: str
    object: Literal['expert.memory_event.deleted'] = 'expert.memory_event.deleted'
    expert_id: str
    session_id: str
    deleted: Literal[True] = True


class ExpertSessionFork(BaseModel):
    model_config = ConfigDict(extra='forbid')

    id: str
    parent_session_id: str
    child_session_id: str
    label: str | None = None
    created_at: datetime | None = None


class ExpertSession(BaseModel):
    model_config = ConfigDict(extra='forbid')

    id: str
    object: Literal['expert.session'] = 'expert.session'
    session_key: str
    expert_id: str
    api_key_id: str | None = None
    user_id: str | None = None
    external_user_id: str | None = None
    conversation_id: str | None = None
    label: str | None = None
    parent_session_id: str | None = None
    status: Literal['active', 'archived', 'deleted'] = 'active'
    metadata: dict[str, Any] = Field(default_factory=dict)
    messages: list[ExpertMessage] = Field(default_factory=list)
    tool_calls: list[ExpertToolCall] = Field(default_factory=list)
    retrieval_runs: list[ExpertRetrievalRun] = Field(default_factory=list)
    memory_events: list[ExpertMemoryEvent] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_active_at: datetime | None = None


class ExpertMessageRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    _expert_id: str | None = PrivateAttr(default=None)

    message: str = Field(min_length=1, max_length=32_000)
    session_id: str | None = None
    external_user_id: str | None = Field(default=None, max_length=255)
    conversation_id: str | None = Field(default=None, max_length=255)
    session_label: str | None = Field(default=None, max_length=255)
    lens: str | None = Field(default=None, max_length=128)
    lens_inputs: dict[str, Any] | None = None

    @field_validator('session_id', 'external_user_id', 'conversation_id', 'session_label', 'lens')
    @classmethod
    def _normalize_optional_expert_message_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator('message')
    @classmethod
    def _non_blank_expert_message(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError('message must be a non-empty string')
        return normalized

    @property
    def expert_id(self) -> str | None:
        return self._expert_id

    def bind_expert_id(self, expert_id: str) -> ExpertMessageRequest:
        normalized = str(expert_id or '').strip()
        if not normalized:
            raise ValueError('expert_id is required')
        bound = self.model_copy(deep=True)
        bound._expert_id = normalized
        return bound


class ExpertCitation(BaseModel):
    model_config = ConfigDict(extra='forbid')

    file_id: str | None = None
    filename: str | None = None
    chunk_id: str | None = None
    document_id: str | None = None
    title: str | None = None
    url: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    heading_path: list[str] = Field(default_factory=list)
    score: float | None = None
    marker: str | None = None
    annotation: dict[str, Any] | None = None
    message_annotation: OpenAIMessageFileCitationAnnotation | None = None
    graph_relationships: list[dict[str, Any]] = Field(default_factory=list)


class ExpertRetrievalTraceRun(BaseModel):
    model_config = ConfigDict(extra='forbid')

    retrieval_run_id: str | None = None
    query: str
    vector_store_id: str
    lens_id: str
    requested_lens_id: str | None = None
    lens_selection_source: Literal['explicit', 'inferred', 'default'] = 'default'
    graph_status: str | None = None
    result_ids: list[str] = Field(default_factory=list)
    selected_context_result_ids: list[str] = Field(default_factory=list)
    citation_count: int = Field(default=0, ge=0)


class ExpertRetrievalTrace(BaseModel):
    model_config = ConfigDict(extra='forbid')

    status: Literal['not_run', 'completed', 'partial', 'failed']
    runs: list[ExpertRetrievalTraceRun] = Field(default_factory=list)


class ExpertModelMetadata(BaseModel):
    model_config = ConfigDict(extra='forbid')

    policy_id: str
    requested_model_profile_id: str
    model_profile_id: str
    provider: str
    model: str
    latency_ms: int = Field(ge=0)
    usage: ExpertChatUsage
    finish_reason: str | None = None
    fallback: ExpertChatFallback


class ExpertMessageResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')

    expert_id: str
    session_id: str
    parent_session_id: str | None = None
    answer: str = Field(min_length=1)
    citations: list[ExpertCitation] = Field(default_factory=list)
    retrieval_trace: ExpertRetrievalTrace
    model_metadata: ExpertModelMetadata
    caveats: list[str] = Field(default_factory=list)
    follow_up_suggestions: list[str] = Field(default_factory=list)


class ExpertSessionForkRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    label: str | None = Field(default=None, max_length=255)
    external_user_id: str | None = Field(default=None, max_length=255)
    conversation_id: str | None = Field(default=None, max_length=255)

    @field_validator('label', 'external_user_id', 'conversation_id')
    @classmethod
    def _normalize_optional_fork_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ExpertSessionForkResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')

    expert_id: str
    session_id: str
    parent_session_id: str
    external_user_id: str | None = None
    conversation_id: str | None = None
    label: str | None = None


class VectorStoreGraphNode(BaseModel):
    model_config = ConfigDict(extra='allow')

    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    key: str | None = None
    label: str | None = None
    attributes: dict[str, Any] | None = None
    properties: dict[str, Any] | None = None
    provenance: list[dict[str, Any]] | dict[str, Any] | None = None


class VectorStoreGraphEdge(BaseModel):
    model_config = ConfigDict(extra='allow')

    id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    attributes: dict[str, Any] | None = None
    properties: dict[str, Any] | None = None
    provenance: dict[str, Any] | list[dict[str, Any]] | None = None


class VectorStoreGraphLoadRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    nodes: list[VectorStoreGraphNode] = Field(default_factory=list)
    edges: list[VectorStoreGraphEdge] = Field(default_factory=list)
    replace: bool = True
    dry_run: bool = False


class VectorStoreGraphLoadResponse(BaseModel):
    model_config = ConfigDict(extra='allow')

    object: str = 'vector_store.graph_load'
    vector_store_id: str
    status: Literal['loaded', 'dry_run']
    dry_run: bool = False
    replaced: bool = True
    nodes: int = 0
    edges: int = 0
    loaded_nodes: int = 0
    loaded_edges: int = 0
    skipped_edges: int = 0


class OpenAIResponseFileSearchResult(BaseModel):
    model_config = ConfigDict(extra='allow')

    file_id: str | None = None
    filename: str | None = None
    score: float | None = None
    text: str | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class OpenAIResponseFileSearchCallItem(BaseModel):
    model_config = ConfigDict(extra='allow')

    type: Literal['file_search_call']
    id: str | None = None
    status: str | None = None
    queries: list[str] = Field(default_factory=list)
    results: list[OpenAIResponseFileSearchResult] | None = None
    search_results: list[OpenAIResponseFileSearchResult] | None = None


class OpenAIResponseOutputTextContent(BaseModel):
    model_config = ConfigDict(extra='allow')

    type: Literal['output_text']
    text: str = ''
    annotations: list[OpenAIFileCitationAnnotation] = Field(default_factory=list)


class OpenAIResponseMessageItem(BaseModel):
    model_config = ConfigDict(extra='allow')

    type: Literal['message']
    id: str | None = None
    status: str | None = None
    role: str | None = None
    content: list[OpenAIResponseOutputTextContent | dict[str, Any]] = Field(default_factory=list)


class OpenAINativeCitation(BaseModel):
    model_config = ConfigDict(extra='allow')

    annotation: OpenAIFileCitationAnnotation | None = None
    message_annotation: OpenAIMessageFileCitationAnnotation | None = None
    marker: str | None = None
    start_index: int | None = Field(default=None, ge=0)
    end_index: int | None = Field(default=None, ge=0)
    model_source_id: str | None = None
    model_marker: str | None = None


class OpenAIResponseUsage(BaseModel):
    model_config = ConfigDict(extra='allow')

    input_tokens: int | None = None
    input_tokens_details: dict[str, Any] | None = None
    output_tokens: int | None = None
    output_tokens_details: dict[str, Any] | None = None
    total_tokens: int | None = None


class OpenAIResponseObject(BaseModel):
    model_config = ConfigDict(extra='allow')

    id: str
    object: str = 'response'
    created_at: int | None = None
    status: str | None = None
    completed_at: int | None = None
    background: bool | None = None
    error: Any = None
    incomplete_details: Any = None
    instructions: str | None = None
    max_output_tokens: int | None = None
    max_tool_calls: int | None = None
    model: str | None = None
    output: list[OpenAIResponseFileSearchCallItem | OpenAIResponseMessageItem | dict[str, Any]] = Field(default_factory=list)
    parallel_tool_calls: bool | None = None
    previous_response_id: str | None = None
    reasoning: dict[str, Any] | None = None
    service_tier: str | None = None
    store: bool | None = None
    temperature: float | None = None
    text: dict[str, Any] | None = None
    tool_choice: Any = None
    tools: list[dict[str, Any]] = Field(default_factory=list)
    top_logprobs: int | None = None
    top_p: float | None = None
    truncation: str | None = None
    usage: OpenAIResponseUsage | dict[str, Any] | None = None
    user: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    citations: list[OpenAINativeCitation] = Field(default_factory=list)
    output_guard: dict[str, Any] | None = None


class OpenAIResponseCreatedEvent(BaseModel):
    model_config = ConfigDict(extra='allow')

    type: Literal['response.created']
    sequence_number: int | None = Field(default=None, ge=0)
    response: OpenAIResponseObject


class OpenAIResponseInProgressEvent(BaseModel):
    model_config = ConfigDict(extra='allow')

    type: Literal['response.in_progress']
    sequence_number: int | None = Field(default=None, ge=0)
    response: OpenAIResponseObject


class OpenAIResponseOutputItemAddedEvent(BaseModel):
    model_config = ConfigDict(extra='allow')

    type: Literal['response.output_item.added']
    sequence_number: int | None = Field(default=None, ge=0)
    output_index: int = Field(ge=0)
    item: OpenAIResponseFileSearchCallItem | OpenAIResponseMessageItem | dict[str, Any]


class OpenAIResponseFileSearchCallInProgressEvent(BaseModel):
    model_config = ConfigDict(extra='allow')

    type: Literal['response.file_search_call.in_progress']
    sequence_number: int | None = Field(default=None, ge=0)
    item_id: str
    output_index: int = Field(ge=0)


class OpenAIResponseFileSearchCallSearchingEvent(BaseModel):
    model_config = ConfigDict(extra='allow')

    type: Literal['response.file_search_call.searching']
    sequence_number: int | None = Field(default=None, ge=0)
    item_id: str
    output_index: int = Field(ge=0)


class OpenAIResponseFileSearchCallCompletedEvent(BaseModel):
    model_config = ConfigDict(extra='allow')

    type: Literal['response.file_search_call.completed']
    sequence_number: int | None = Field(default=None, ge=0)
    item_id: str
    output_index: int = Field(ge=0)


class OpenAIResponseContentPartAddedEvent(BaseModel):
    model_config = ConfigDict(extra='allow')

    type: Literal['response.content_part.added']
    sequence_number: int | None = Field(default=None, ge=0)
    item_id: str
    output_index: int = Field(ge=0)
    content_index: int = Field(ge=0)
    part: OpenAIResponseOutputTextContent | dict[str, Any]


class OpenAIResponseOutputTextDeltaEvent(BaseModel):
    model_config = ConfigDict(extra='allow')

    type: Literal['response.output_text.delta']
    sequence_number: int | None = Field(default=None, ge=0)
    item_id: str
    output_index: int = Field(ge=0)
    content_index: int = Field(ge=0)
    delta: str
    obfuscation: str | None = None


class OpenAIResponseOutputTextAnnotationAddedEvent(BaseModel):
    model_config = ConfigDict(extra='allow')

    type: Literal['response.output_text.annotation.added']
    sequence_number: int | None = Field(default=None, ge=0)
    item_id: str
    output_index: int = Field(ge=0)
    content_index: int = Field(ge=0)
    annotation_index: int = Field(ge=0)
    annotation: OpenAIFileCitationAnnotation


class OpenAIResponseOutputTextDoneEvent(BaseModel):
    model_config = ConfigDict(extra='allow')

    type: Literal['response.output_text.done']
    sequence_number: int | None = Field(default=None, ge=0)
    item_id: str
    output_index: int = Field(ge=0)
    content_index: int = Field(ge=0)
    text: str


class OpenAIResponseContentPartDoneEvent(BaseModel):
    model_config = ConfigDict(extra='allow')

    type: Literal['response.content_part.done']
    sequence_number: int | None = Field(default=None, ge=0)
    item_id: str
    output_index: int = Field(ge=0)
    content_index: int = Field(ge=0)
    part: OpenAIResponseOutputTextContent | dict[str, Any]


class OpenAIResponseOutputItemDoneEvent(BaseModel):
    model_config = ConfigDict(extra='allow')

    type: Literal['response.output_item.done']
    sequence_number: int | None = Field(default=None, ge=0)
    output_index: int = Field(ge=0)
    item: OpenAIResponseFileSearchCallItem | OpenAIResponseMessageItem | dict[str, Any]


class OpenAIResponseCompletedEvent(BaseModel):
    model_config = ConfigDict(extra='allow')

    type: Literal['response.completed']
    sequence_number: int | None = Field(default=None, ge=0)
    response: OpenAIResponseObject


class OpenAIResponseStreamEvent(RootModel[
    OpenAIResponseCreatedEvent
    | OpenAIResponseInProgressEvent
    | OpenAIResponseOutputItemAddedEvent
    | OpenAIResponseFileSearchCallInProgressEvent
    | OpenAIResponseFileSearchCallSearchingEvent
    | OpenAIResponseFileSearchCallCompletedEvent
    | OpenAIResponseContentPartAddedEvent
    | OpenAIResponseOutputTextDeltaEvent
    | OpenAIResponseOutputTextAnnotationAddedEvent
    | OpenAIResponseOutputTextDoneEvent
    | OpenAIResponseContentPartDoneEvent
    | OpenAIResponseOutputItemDoneEvent
    | OpenAIResponseCompletedEvent
]):
    pass


class OpenAIResponseInputTokensResponse(BaseModel):
    object: str = 'response.input_tokens'
    input_tokens: int


class OpenAIResponseCompactionResponse(BaseModel):
    model_config = ConfigDict(extra='allow')

    id: str
    object: str = 'response.compaction'
    created_at: int | None = None
    output: list[dict[str, Any]] = Field(default_factory=list)
    usage: OpenAIResponseUsage | dict[str, Any] | None = None


class OpenAIResponseDeletedResponse(BaseModel):
    id: str
    object: str = 'response'
    deleted: bool


class OpenAIResponseInputItemsPage(BaseModel):
    object: str = 'list'
    data: list[dict[str, Any]] = Field(default_factory=list)
    first_id: str | None = None
    last_id: str | None = None
    has_more: bool = False


class OpenAIProjectApiKey(BaseModel):
    model_config = ConfigDict(extra='allow')

    object: str = 'organization.project.api_key'
    redacted_value: str
    name: str
    created_at: int | None = None
    last_used_at: int | None = None
    id: str
    owner: dict[str, Any] = Field(default_factory=dict)


class OpenAIProjectApiKeyListResponse(BaseModel):
    model_config = ConfigDict(extra='allow')

    object: str = 'list'
    data: list[OpenAIProjectApiKey] = Field(default_factory=list)
    first_id: str | None = None
    last_id: str | None = None
    has_more: bool = False


class OpenAIProjectApiKeyDeletedResponse(BaseModel):
    model_config = ConfigDict(extra='allow')

    id: str
    object: str = 'organization.project.api_key.deleted'
    deleted: bool = True


class OpenAIAdminApiKey(BaseModel):
    model_config = ConfigDict(extra='allow')

    object: str = 'organization.admin_api_key'
    id: str
    name: str
    redacted_value: str
    created_at: int | None = None
    expires_at: int | None = None
    last_used_at: int | None = None
    owner: dict[str, Any] = Field(default_factory=dict)


class OpenAIAdminApiKeyCreateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    name: str = Field(min_length=1)
    expires_in_seconds: int | None = Field(default=None, ge=1, le=31536000)

    @field_validator('name')
    @classmethod
    def _strip_nonblank_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError('name must be a non-empty string')
        return stripped


class OpenAIAdminApiKeyCreateResponse(OpenAIAdminApiKey):
    value: str


class OpenAIAdminApiKeyListResponse(BaseModel):
    model_config = ConfigDict(extra='allow')

    object: str = 'list'
    data: list[OpenAIAdminApiKey] = Field(default_factory=list)
    first_id: str | None = None
    last_id: str | None = None
    has_more: bool = False


class OpenAIAdminApiKeyDeletedResponse(BaseModel):
    model_config = ConfigDict(extra='allow')

    id: str
    object: str = 'organization.admin_api_key.deleted'
    deleted: bool = True


class ContextPackRequest(SearchRequest):
    max_context_tokens: int = 6000
    require_citations: bool = True

class ContextCitation(BaseModel):
    chunk_id: str
    document_id: str
    file_id: str | None = None
    title: str | None = None
    filename: str | None = None
    url: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    heading_path: list[str] = Field(default_factory=list)
    annotation: dict[str, Any] | None = None
    message_annotation: OpenAIMessageFileCitationAnnotation | None = None
    marker: str | None = None
    model_source_id: str | None = None
    model_marker: str | None = None
    model_locator: str | None = None
    context_relation: str | None = None
    source_chunk_id: str | None = None
    neighbor_offset: int | None = None
    parent_heading_path: list[str] = Field(default_factory=list)


# WAVE-133 offline foundation. These are internal shape checks, not the KS-650
# producer contract, publication decisions, or API response/request extensions.
# The historical graph loader and ContextCitation deliberately do not use them.
class _FiscalOfflineModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True, revalidate_instances='always')


def _fiscal_opaque_text(value: str) -> str:
    if not value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError('fiscal reference must be nonblank and contain no control characters')
    return value


FiscalOpaqueText = Annotated[str, Field(min_length=1, max_length=256), AfterValidator(_fiscal_opaque_text)]
FiscalSha256 = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]


def _fiscal_description(value: str) -> str:
    if not value.strip():
        raise ValueError('fiscal description must not be blank')
    return value


FiscalDescription = Annotated[str, Field(min_length=1, max_length=2048), AfterValidator(_fiscal_description)]


def _fiscal_json_object(value: str) -> str:
    """Preserve opaque upstream keys in a small immutable, canonical JSON value."""
    import json
    import math

    if len(value.encode('utf-8')) > 16384:
        raise ValueError('fiscal opaque JSON exceeds 16384 bytes')

    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError('fiscal opaque JSON contains duplicate keys')
            result[key] = item
        return result

    def invalid_constant(_):
        raise ValueError('fiscal opaque JSON requires finite numbers')

    try:
        parsed = json.loads(value, object_pairs_hook=pairs, parse_constant=invalid_constant)
    except (RecursionError, OverflowError) as exc:
        raise ValueError('fiscal opaque JSON is too deeply nested') from exc
    if not isinstance(parsed, dict):
        raise ValueError('fiscal opaque JSON must be an object')
    pending = [(parsed, 0)]
    count = 0
    while pending:
        item, depth = pending.pop()
        count += 1
        if depth > 8 or count > 1024:
            raise ValueError('fiscal opaque JSON exceeds depth or item limit')
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError('fiscal opaque JSON requires finite numbers')
        if isinstance(item, dict):
            pending.extend((child, depth + 1) for child in item.values())
        elif isinstance(item, list):
            pending.extend((child, depth + 1) for child in item)
    return json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


FiscalOpaqueJsonObject = Annotated[str, Field(max_length=16384), AfterValidator(_fiscal_json_object)]


def _fiscal_tuple(value):
    # Permit JSON arrays while refusing generators, sets and coercive iterables.
    if type(value) not in (tuple, list):
        raise ValueError('fiscal collection must be an array or tuple')
    return tuple(value)


class FiscalCanonicalReference(_FiscalOfflineModel):
    """Opaque supplied upstream identity/revision; never derived from a locator."""
    type: FiscalOpaqueText
    id: FiscalOpaqueText
    revision_or_hash: FiscalOpaqueText


class FiscalProjectionScope(_FiscalOfflineModel):
    tenant_id: FiscalOpaqueText
    business_instance_id: FiscalOpaqueText
    vector_store_id: Annotated[str, Field(pattern=r'^vs_[A-Za-z0-9_-]{1,124}$')]


class FiscalStructuredRecordLocator(_FiscalOfflineModel):
    # A logical CSV data record, excluding its header; not a physical line/page.
    kind: Literal['csv_record'] = 'csv_record'
    data_record_1based: Annotated[int, Field(ge=1, le=100000)]
    header_records: Literal[1] = 1
    # Optional parser diagnostic, not the logical record identity or a page.
    # A physical line consumes at least one byte in the verifier's <=16 MiB CSV.
    # Keep this local bound independent of the artifact module (which imports us).
    physical_line_end_1based: Annotated[int, Field(ge=1, le=16 * 1024 * 1024)] | None = None
    selected_columns: Annotated[tuple[FiscalOpaqueText, ...], BeforeValidator(_fiscal_tuple), Field(max_length=256)] = ()

    @field_validator('header_records', mode='before')
    @classmethod
    def _strict_header_count(cls, value):
        if type(value) is not int:
            raise ValueError('header_records must be an integer')
        return value

    @field_validator('selected_columns')
    @classmethod
    def _distinct_columns(cls, value):
        if len(value) != len(set(value)):
            raise ValueError('selected columns must be distinct')
        return value

    @model_validator(mode='after')
    def _physical_line_bound(self):
        if (self.physical_line_end_1based is not None and
                self.physical_line_end_1based < self.data_record_1based + self.header_records):
            raise ValueError('physical line end cannot precede the data record plus header')
        return self


class _FiscalSourceEvidence(_FiscalOfflineModel):
    source_revision_id: FiscalOpaqueText
    source_content_hash_sha256: FiscalSha256
    # Unknown parsed/extraction identity stays unknown. A later eligible adapter
    # must enforce the actual KS-650 prerequisites before this can be served.
    extraction_revision_id: FiscalOpaqueText | None = None
    extraction_content_hash_sha256: FiscalSha256 | None = None
    citation_url: Annotated[str, Field(min_length=1, max_length=2048)] | None = None

    @model_validator(mode='after')
    def _paired_extraction(self):
        if (self.extraction_revision_id is None) != (self.extraction_content_hash_sha256 is None):
            raise ValueError('extraction revision and hash must be supplied together')
        return self

    @field_validator('citation_url')
    @classmethod
    def _public_url_shape(cls, value):
        from urllib.parse import urlsplit
        if value is not None:
            parsed = urlsplit(value)
            if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or
                    parsed.username is not None or parsed.password is not None or
                    any(char.isspace() or ord(char) < 32 for char in value)):
                raise ValueError('citation URL must be an HTTP(S) URL without credentials')
        return value


class FiscalStructuredRecordEvidence(_FiscalSourceEvidence):
    evidence_kind: Literal['structured_record'] = 'structured_record'
    locator: FiscalStructuredRecordLocator
    # Existing audit digest: canonical {headers: [...], values: [...]} JSON.
    raw_record_sha256: FiscalSha256
    observation_id: FiscalOpaqueText | None = None
    parser_revision: FiscalOpaqueText | None = None


class FiscalDocumentSpanEvidence(_FiscalSourceEvidence):
    evidence_kind: Literal['document_span'] = 'document_span'
    source_span_id: FiscalOpaqueText
    span_type: FiscalOpaqueText
    # Exact upstream SourceSpan.locator keys are not a new ExAIS taxonomy.
    locator_json: FiscalOpaqueJsonObject
    content_hash_sha256: FiscalSha256
    document_id: FiscalOpaqueText | None = None
    chunk_id: FiscalOpaqueText | None = None

    @model_validator(mode='after')
    def _document_binding_shape(self):
        if self.locator_json == '{}':
            raise ValueError('document span requires a nonempty exact locator')
        if self.chunk_id is not None and self.document_id is None:
            raise ValueError('a chunk binding requires its document identity')
        return self


FiscalSourceEvidence = Annotated[
    FiscalStructuredRecordEvidence | FiscalDocumentSpanEvidence,
    Field(discriminator='evidence_kind'),
]


class FiscalEvidenceCitation(_FiscalOfflineModel):
    """Native evidence shape, distinct from ContextCitation; not service-ready."""
    canonical_reference: FiscalCanonicalReference
    evidence: FiscalSourceEvidence


class FiscalProjectionNode(_FiscalOfflineModel):
    projection_id: Annotated[str, Field(pattern=r'^fiscal2:node:[0-9a-f]{64}$')]
    canonical_reference: FiscalCanonicalReference
    description: FiscalDescription | None = None
    # Opaque supplied canonical values, including null subunit/effective dates.
    structured_fields_json: FiscalOpaqueJsonObject = '{}'
    evidence: Annotated[tuple[FiscalSourceEvidence, ...], BeforeValidator(_fiscal_tuple), Field(min_length=1, max_length=20)]


class FiscalProjectionEdge(_FiscalOfflineModel):
    projection_id: Annotated[str, Field(pattern=r'^fiscal2:edge:[0-9a-f]{64}$')]
    canonical_reference: FiscalCanonicalReference
    relationship_type: FiscalOpaqueText
    source_node_id: Annotated[str, Field(pattern=r'^fiscal2:node:[0-9a-f]{64}$')]
    target_node_id: Annotated[str, Field(pattern=r'^fiscal2:node:[0-9a-f]{64}$')]
    # An explicit assertion only. Membership in a joint run never generates edges.
    context_json: FiscalOpaqueJsonObject = '{}'
    evidence: Annotated[tuple[FiscalSourceEvidence, ...], BeforeValidator(_fiscal_tuple), Field(min_length=1, max_length=20)]


class FiscalProjectionCounts(_FiscalOfflineModel):
    nodes: Annotated[int, Field(ge=0, le=256000)]
    edges: Annotated[int, Field(ge=0, le=512000)]
    descriptions: Annotated[int, Field(ge=0, le=256000)]

    @model_validator(mode='after')
    def _descriptor_count(self):
        if self.descriptions > self.nodes:
            raise ValueError('description count cannot exceed node count')
        return self


class FiscalProjectionBatch(_FiscalOfflineModel):
    schema_version: Literal['exais.fiscal-projection.offline.v1'] = 'exais.fiscal-projection.offline.v1'
    scope: FiscalProjectionScope
    partition_id: FiscalOpaqueText
    expected_counts: FiscalProjectionCounts
    content_hash: FiscalSha256
    nodes: Annotated[tuple[FiscalProjectionNode, ...], BeforeValidator(_fiscal_tuple), Field(max_length=1000)]
    edges: Annotated[tuple[FiscalProjectionEdge, ...], BeforeValidator(_fiscal_tuple), Field(max_length=2000)]


class FiscalProjectionPartition(_FiscalOfflineModel):
    partition_id: FiscalOpaqueText
    content_hash: FiscalSha256
    expected_counts: FiscalProjectionCounts


class FiscalProjectionManifest(_FiscalOfflineModel):
    schema_version: Literal['exais.fiscal-projection-manifest.offline.v1'] = 'exais.fiscal-projection-manifest.offline.v1'
    manifest_id: FiscalOpaqueText
    scope: FiscalProjectionScope
    snapshot_reference: FiscalCanonicalReference
    source_revision_set_hash_sha256: FiscalSha256
    derivation_run_ids: Annotated[tuple[FiscalOpaqueText, ...], BeforeValidator(_fiscal_tuple), Field(max_length=256)] = ()
    profile_ids: Annotated[tuple[FiscalOpaqueText, ...], BeforeValidator(_fiscal_tuple), Field(max_length=32)] = ()
    partitions: Annotated[tuple[FiscalProjectionPartition, ...], BeforeValidator(_fiscal_tuple), Field(min_length=1, max_length=256)]
    total_expected_counts: FiscalProjectionCounts
    content_hash: FiscalSha256

    @field_validator('derivation_run_ids', 'profile_ids')
    @classmethod
    def _distinct_refs(cls, value):
        if len(value) != len(set(value)):
            raise ValueError('manifest references must be distinct')
        return value


class FiscalEntityResult(_FiscalOfflineModel):
    """Internal native entity representation; intentionally not a ChunkRecord."""
    canonical_reference: FiscalCanonicalReference
    description: FiscalDescription | None = None
    structured_fields_json: FiscalOpaqueJsonObject = '{}'
    evidence: Annotated[tuple[FiscalEvidenceCitation, ...], BeforeValidator(_fiscal_tuple), Field(min_length=1, max_length=20)]
    snapshot_reference: FiscalCanonicalReference
    manifest_id: FiscalOpaqueText
    score: Annotated[float, Field(allow_inf_nan=False)] | None = None

    @model_validator(mode='after')
    def _citation_subjects(self):
        if any(citation.canonical_reference != self.canonical_reference for citation in self.evidence):
            raise ValueError('entity citation canonical subject does not match its result')
        return self


class ContextPackResponse(BaseModel):
    query: str
    context: str
    citations: list[ContextCitation]
    chunks: list[ChunkRecord]
    token_estimate: int
    audit_event_id: str | None = None

class RetrievalAnswerRequest(ContextPackRequest):
    max_answer_sources: int = Field(default=5, ge=1, le=20)
    answer_style: Literal['extractive'] = 'extractive'

class RetrievalAnswerResponse(BaseModel):
    query: str
    answer: str
    citations: list[ContextCitation]
    chunks: list[ChunkRecord]
    context: str
    answer_style: str = 'extractive'
    token_estimate: int
    audit_event_id: str | None = None
    output_guard: dict[str, Any] | None = None


_INLINE_SECRET_PREFIXES = ("sk-", "svs_live_", "bearer ", "basic ", "hf_", "rp_")
_SECRET_CONFIG_KEY_PARTS = ("secret", "api_key", "token", "password", "authorization", "credential")
_SECRET_CONFIG_FLAG_KEYS = {"live_credential_proof"}


def _is_endpoint_secret_reference(value: str) -> bool:
    if parse_secret_reference(value) is not None:
        return True
    return value.startswith("secret://") and len(value) > len("secret://") and not any(ch.isspace() for ch in value)


def _validate_secret_reference_value(key: str, value: Any) -> Any:
    if value is None or value == "":
        return value
    if not isinstance(value, str):
        raise ValueError(f"{key} must use a secret reference string")
    normalized = value.strip()
    lowered = normalized.lower()
    if _is_endpoint_secret_reference(normalized):
        return normalized
    if any(ch.isspace() for ch in normalized) or "=" in normalized:
        raise ValueError(f"{key} must use a secret reference, not an inline secret value")
    if lowered.startswith(_INLINE_SECRET_PREFIXES):
        raise ValueError(f"{key} must use a secret reference, not an inline secret value")
    raise ValueError(f"{key} must use a supported secret reference")


def _validate_config_secret_references(value: Any, path: str = "config") -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            nested_path = f"{path}.{key}"
            key_text = str(key).lower()
            if key_text in _SECRET_CONFIG_FLAG_KEYS:
                continue
            if any(part in key_text for part in _SECRET_CONFIG_KEY_PARTS) and not isinstance(nested, (dict, list)):
                _validate_secret_reference_value(nested_path, nested)
            else:
                _validate_config_secret_references(nested, nested_path)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _validate_config_secret_references(item, f"{path}[{index}]")

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
    model: str | None = None
    provider: str | None = None
    security_level: int = 1
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
    supports: list[str] = Field(default_factory=list)
    privacy: str = 'external_api'
    security_max_level: int = 3
    status: str = 'active'
    health_status: str = 'unknown'
    p95_latency_ms: int | None = Field(default=None, ge=0)
    region: str | None = None
    model_revision: str | None = None
    auth_secret_ref: str | None = None
    last_health_check_at: int | None = None
    routing_state: str = 'unknown'
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator('security_max_level')
    @classmethod
    def _security_max_level_in_range(cls, value: int) -> int:
        if value < 0 or value > 5:
            raise ValueError('security_max_level must be between 0 and 5')
        return value

    @field_validator('auth_secret_ref')
    @classmethod
    def _auth_secret_ref_is_reference(cls, value: str | None) -> str | None:
        return _validate_secret_reference_value('auth_secret_ref', value)

    @field_validator('config')
    @classmethod
    def _config_uses_secret_references(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_config_secret_references(value)
        return value


class ModelEndpointPatchRequest(BaseModel):
    model_config = ConfigDict(extra='allow')

    name: str | None = None
    provider: str | None = None
    kind: Literal['embedding', 'reranker', 'tokenizer', 'multimodal'] | None = None
    base_url: str | None = None
    model: str | None = None
    dimensions: int | None = None
    supports: list[str] | None = None
    privacy: str | None = None
    security_max_level: int | None = None
    status: str | None = None
    health_status: str | None = None
    p95_latency_ms: int | None = None
    region: str | None = None
    model_revision: str | None = None
    auth_secret_ref: str | None = None
    last_health_check_at: int | None = None
    routing_state: str | None = None
    config: dict[str, Any] | None = None

class ModelEndpointResponse(ModelEndpointRequest):
    id: str
    created_at: int | None = None
    updated_at: int | None = None


class ModelEndpointListResponse(BaseModel):
    object: str = 'list'
    data: list[ModelEndpointResponse] = Field(default_factory=list)
    first_id: str | None = None
    last_id: str | None = None
    has_more: bool = False

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
    estimated_input_tokens: int | None = None
    estimated_cost_usd: float | None = None
    cost_currency: str | None = None
    cost_unit: str | None = None
    cost_per_1m_tokens_usd: float | None = None
    cost_reason: str | None = None

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
    execution_mode: Literal['deterministic', 'live', 'live_retrieval'] = 'deterministic'
    model_profile_ids: list[str]
    queries: list[dict[str, Any]] = Field(default_factory=list)
    top_k: int = Field(default=10, ge=1, le=100)
    golden_set_id: str | None = None
    vector_store_id: str | None = None
    knowledge_base_id: str | None = None
    retrieval_profile_id: str | None = None
    metrics: list[str] = Field(default_factory=list)
    selection_policy: dict[str, Any] = Field(default_factory=dict)

class BakeoffRunResponse(BaseModel):
    id: str
    status: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    results: list[dict[str, Any]] = Field(default_factory=list)


class BakeoffRunSummaryResponse(BaseModel):
    model_config = ConfigDict(extra='allow')

    id: str
    name: str
    mode: str
    model_profile_ids: list[str] = Field(default_factory=list)
    status: str
    metrics: dict[str, Any] = Field(default_factory=dict)
    created_at: int | None = None
    completed_at: int | None = None


class BakeoffRunListResponse(BaseModel):
    object: str = 'list'
    data: list[BakeoffRunSummaryResponse] = Field(default_factory=list)
    first_id: str | None = None
    last_id: str | None = None
    has_more: bool = False

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


class AdminSessionResponse(BaseModel):
    model_config = ConfigDict(extra='allow')

    object: str = 'admin.session'
    authenticated: bool
    tenant_id: str
    business_instance_id: str
    user_id: str | None = None
    api_key_id: str | None = None
    scopes: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    max_security_level: int


class UsageEventResponse(BaseModel):
    model_config = ConfigDict(extra='allow')

    id: str | None = None
    event_type: str
    quantity: int | float
    unit: str
    provider: str | None = None
    model: str | None = None
    cost_estimate_usd: float | None = None
    user_id: str | None = None
    api_key_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: int | None = None


class UsageEventListResponse(BaseModel):
    object: str = 'list'
    data: list[UsageEventResponse] = Field(default_factory=list)
    first_id: str | None = None
    last_id: str | None = None
    has_more: bool = False


UsageSummaryGroupBy = Literal['user', 'api_key']


class UsageSummaryRow(BaseModel):
    model_config = ConfigDict(extra='forbid')

    object: Literal['usage.summary.row'] = 'usage.summary.row'
    group_by: UsageSummaryGroupBy
    group_id: str | None = None
    external_id: str | None = None
    event_count: int
    quantity: float
    cost_estimate_usd: float | None = None


class UsageSummaryResponse(BaseModel):
    model_config = ConfigDict(extra='forbid', populate_by_name=True)

    object: Literal['usage.summary'] = 'usage.summary'
    group_by: UsageSummaryGroupBy
    from_ts: int | None = Field(default=None, alias='from')
    to_ts: int | None = Field(default=None, alias='to')
    data: list[UsageSummaryRow] = Field(default_factory=list)


class AdminUserCreateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    external_id: str = Field(min_length=1, max_length=255)
    email: str | None = Field(default=None, max_length=320)
    display_name: str | None = Field(default=None, max_length=255)

    @field_validator('external_id')
    @classmethod
    def _non_blank_external_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError('external_id must be a non-empty string')
        return normalized

    @field_validator('email', 'display_name')
    @classmethod
    def _normalize_optional_user_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class AdminUserResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')

    id: str
    object: Literal['user'] = 'user'
    external_id: str | None = None
    email: str | None = None
    display_name: str | None = None
    status: str
    business_instance_id: str | None = None
    created_at: int | None = None
    deactivated_at: int | None = None


class AdminUserListResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')

    object: Literal['list'] = 'list'
    data: list[AdminUserResponse] = Field(default_factory=list)
    first_id: str | None = None
    last_id: str | None = None
    has_more: bool = False


class AdminUserDeactivateResponse(BaseModel):
    model_config = ConfigDict(extra='forbid')

    id: str
    object: Literal['user.deactivated'] = 'user.deactivated'
    deactivated: bool = True
    revoked_api_key_ids: list[str] = Field(default_factory=list)
    data: AdminUserResponse


class AuditEventResponse(BaseModel):
    model_config = ConfigDict(extra='allow')

    id: str
    event_type: str
    action: str
    resource_type: str
    resource_id: str | None = None
    security_level: int | None = None
    allowed: bool
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: int | None = None


class AuditEventListResponse(BaseModel):
    object: str = 'list'
    data: list[AuditEventResponse] = Field(default_factory=list)
    first_id: str | None = None
    last_id: str | None = None
    has_more: bool = False


class TenantResponse(BaseModel):
    id: str
    name: str
    slug: str


class InstanceApiKeyResponse(BaseModel):
    model_config = ConfigDict(extra='allow')

    id: str
    label: str
    scopes: list[str] = Field(default_factory=list)
    max_security_level: int
    api_key: str | None = None
    user_id: str | None = None
    status: str | None = None
    created_at: int | None = None
    last_used_at: int | None = None
    expires_at: int | None = None


class InstanceApiKeyListResponse(BaseModel):
    object: str = 'list'
    data: list[InstanceApiKeyResponse] = Field(default_factory=list)
    first_id: str | None = None
    last_id: str | None = None
    has_more: bool = False


class InstanceApiKeyDeletedResponse(BaseModel):
    id: str
    object: str = 'api_key.deleted'
    deleted: bool = True
    data: InstanceApiKeyResponse

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
