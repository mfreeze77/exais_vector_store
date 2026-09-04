from __future__ import annotations
from hashlib import sha256
import json
import os
import re
import time
from typing import Annotated, Any
import uuid
from fastapi import Depends, FastAPI, HTTPException, Response, UploadFile, File, Form, Header, Body, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session
from sqlalchemy import text
from svs_common.config import get_settings, validate_production_guardrails
from svs_common.db import jsonb_param, get_session, set_rls_context
from svs_common.sql import jsonb_text
from svs_common.security import build_retrieval_scope, chunk_allowed_by_scope, principal_from_dev_headers
from svs_common.schemas import (
    AdminSessionResponse, AuditEventListResponse, BakeoffRunListResponse, HealthResponse,
    AdminUserCreateRequest, AdminUserDeactivateResponse, AdminUserListResponse, AdminUserResponse,
    ExpertCorpus, UsageSummaryGroupBy, UsageSummaryResponse, UsageSummaryRow,
    IngestionJobDetail, IngestionJobListResponse, IngestionJobResponse, InstanceApiKeyDeletedResponse,
    InstanceApiKeyListResponse, InstanceApiKeyResponse, ModelEndpointListResponse, ModelEndpointPatchRequest,
    ModelRegistryResponse, OpenAIFileContentResponse, OpenAIVectorStoreFileAttachRequest,
    OpenAIVectorStoreFileBatchCreateRequest, OpenAIVectorStoreFileUpdateRequest, PrometheusMetricsResponse,
    ReadinessResponse, RetrievalProfilesResponse, TenantResponse, UsageEventListResponse,
    VectorizationModesResponse,
    ExpertMessageRequest, ExpertMessageResponse, ExpertProfile, ExpertProfileListResponse,
    ExpertSessionForkRequest, ExpertSessionForkResponse,
    ExpertFeedbackRequest, ExpertFeedbackResponse, ExpertMemoryDeletedResponse, ExpertMemoryEvent,
    ExpertMemoryListResponse, ExpertMemoryPromotionRequest, ExpertTurnRecord,
    ChunkRecord, Principal, VectorStoreCreateRequest, SearchRequest, SearchResponse, ContextPackRequest, ContextPackResponse,
    RetrievalAnswerRequest, RetrievalAnswerResponse, DocumentIngestRequest,
    VectorStoreDeletedResponse, VectorStoreListResponse, VectorStoreResponse,
    IngestionPlanResponse, IngestionPreviewRequest, ModelEndpointRequest, ModelEndpointResponse,
    BakeoffRunRequest, BakeoffRunResponse, MaintenanceResult, ReindexRequest, OpenAIFile, OpenAIFileDeletedResponse,
    OpenAIFileListResponse, OpenAIVectorStoreFile, OpenAIVectorStoreFileBatch,
    OpenAIVectorStoreFileBatchFilesPage, OpenAIVectorStoreFileContentResponse,
    OpenAIVectorStoreFileDeletedResponse, OpenAIVectorStoreFileListResponse,
    OpenAIVectorStoreSearchRequest, OpenAIVectorStoreSearchResultsPage,
    VectorStoreGraphLoadRequest, VectorStoreGraphLoadResponse,
    VectorStoreSearchLensesResponse,
    VectorStoreUpdateRequest,
    OpenAIResponseCompactRequest, OpenAIResponseCompactionResponse, OpenAIResponseDeletedResponse,
    OpenAIResponseInputItemsPage, OpenAIResponseInputTokensRequest, OpenAIResponseInputTokensResponse,
    OpenAIAdminApiKey, OpenAIAdminApiKeyCreateRequest, OpenAIAdminApiKeyCreateResponse,
    OpenAIAdminApiKeyDeletedResponse, OpenAIAdminApiKeyListResponse,
    OpenAIProjectApiKey, OpenAIProjectApiKeyDeletedResponse, OpenAIProjectApiKeyListResponse,
    NullableVectorStoreCreateRequest, NullableVectorStoreUpdateRequest,
    OpenAIResponseObject, OpenAIResponseRequest, OpenAIResponseStreamEvent, validate_openai_chunking_strategy,
)
from svs_common.openai_compat import (
    apply_openai_ranking_options,
    extract_responses_input_text,
    ensure_openai_response_citation_integrity,
    merge_chunk_results,
    OpenAICompatError,
    openai_responses_file_search_response,
    openai_response_sse_events,
    openai_search_options_to_search_request_kwargs,
    response_with_file_search_include,
    responses_compact_response,
    responses_continuation_query,
    responses_file_search_tools,
    responses_include_search_results,
    responses_input_token_count,
    responses_input_items,
    responses_input_items_page,
    responses_previous_context_text,
    validate_responses_file_search_tool_choice,
    vector_store_search_results_page,
    vector_store_search_next_page_offset,
    vector_store_search_page_window,
)
from svs_common.openai_metadata import validate_openai_file_attributes
from svs_common.expert_profiles import (
    ExpertProfileNotFoundError,
    list_expert_profiles,
    resolve_expert_profile,
)
from svs_common.expert_engine import (
    ExpertCitationIntegrityError,
    ExpertRetrievalPlanningError,
    configure_expert_search_executor,
    run_expert_turn,
)
from svs_common.expert_llm import ExpertChatGatewayError
from svs_common.expert_sessions import (
    DEFAULT_EXPERT_MEMORY_POLICY,
    ExpertSessionNotFound,
    delete_expert_memory_event,
    extract_candidate_memory_events,
    fork_expert_session,
    get_expert_feedback_record,
    get_expert_session,
    list_expert_memory_events,
    promote_expert_memory_event,
    record_expert_feedback,
    record_expert_memory_event,
    record_expert_turn_accounting,
)
from svs_common.users import (
    create_or_get_user,
    deactivate_user,
    get_user,
    list_users,
)
from svs_common.security import ExpertInteractionSensitiveDataError
from svs_common.cell_graph import CellGraphProfile, cell_graph_profile_for_store
from svs_common.grant_graph import GRANT_CORPUS_KIND, expand_grant_graph, validate_grant_graph
from svs_common.query_planner import KANSAS_CIVICS_LEGAL_PROFILE_ID, merge_query_filters, plan_query
from svs_common.search_lenses import (
    DEFAULT_SEARCH_LENS_ID,
    KSCOURTS_CORPUS_KIND,
    TOPEKA_CORPUS_KIND,
    TOPEKA_GRAPH_HANDLER_ID,
    corpus_kind_for_vector_store,
    normalize_search_lens_id,
    resolve_search_lens,
    search_lens_relation_types,
    search_lenses_for_vector_store,
    search_query_with_lens_inputs,
)
from svs_common.vector_store_repo import (
    VectorStoreRepository,
    VectorStoreUnavailableError,
    refresh_vector_store_activity,
    require_active_vector_store,
)
from svs_common.ingestion import IngestionService
from svs_common.retrieval import RetrievalService
from svs_common.model_registry import vectorization_modes, model_registry, retrieval_profiles
from svs_common.provider_probe import ENDPOINT_METADATA_FIELDS, endpoint_response_payload, normalize_endpoint_payload
from svs_common.ids import new_id
from svs_common.auth import (
    resolve_api_key_principal,
    create_api_key,
    ensure_scope,
    get_api_key,
    list_api_keys,
    validate_delegated_scopes,
    validate_delegated_security_level,
    openai_admin_api_key_create_response,
    openai_admin_api_key_from_metadata,
    openai_project_api_key_from_metadata,
    revoke_api_key,
)
from svs_common.request_controls import (
    stable_hash,
    check_idempotency,
    store_idempotency,
    enforce_rate_limit,
    enforce_resource_rate_limit,
)
from svs_common.vectorization_router import build_ingestion_plan, persist_ingestion_plan
from svs_common.maintenance import MaintenanceService
from svs_common.bakeoff import BakeoffService
from svs_common.index_cleanup import enqueue_purge_stale_vectors
from svs_common.marker_client import (
    MarkerRunpodClient,
    MarkerRunpodError,
    extract_markdown,
    is_marker_pdf_upload,
    markdown_filename_for_pdf,
    marker_attribute_summary,
    pdf_source_id,
    sanitize_stem,
)
from svs_common.object_store import ObjectStore, ObjectStoreError
from svs_common.fleet import FleetVersionReport, build_fleet_version_report

settings = get_settings()
settings.validate_runtime_guards()


def get_request_principal(
    authorization: str | None = Header(default=None),
    x_svs_tenant_id: str | None = Header(default=None),
    x_svs_business_instance_id: str | None = Header(default=None),
    x_svs_user_id: str | None = Header(default=None),
    x_svs_groups: str | None = Header(default=None),
    x_svs_roles: str | None = Header(default=None),
    x_svs_max_security_level: int | None = Header(default=None),
    db: Session = Depends(get_session),
) -> Principal:
    if authorization:
        return resolve_api_key_principal(db, authorization)
    if settings.svs_dev_mode:
        return principal_from_dev_headers(x_svs_tenant_id, x_svs_business_instance_id, x_svs_user_id, x_svs_groups, x_svs_roles, x_svs_max_security_level)
    raise HTTPException(status_code=401, detail='Missing bearer token')


def db_for_principal(db: Session = Depends(get_session), principal: Principal = Depends(get_request_principal)) -> Session:
    set_rls_context(db, principal)
    return db


app = FastAPI(title='exai_vector_store API', version=settings.svs_product_version)


def _openai_response_stream_event_schema_ref() -> dict[str, Any]:
    return {'schema': {'$ref': '#/components/schemas/OpenAIResponseStreamEvent'}}


def _install_openai_response_stream_openapi_contract(openapi_schema: dict[str, Any]) -> None:
    stream_event_schema = OpenAIResponseStreamEvent.model_json_schema(ref_template='#/components/schemas/{model}')
    stream_event_defs = stream_event_schema.pop('$defs', {})
    schemas = openapi_schema.setdefault('components', {}).setdefault('schemas', {})
    for name, schema in stream_event_defs.items():
        schemas.setdefault(name, schema)
    schemas['OpenAIResponseStreamEvent'] = stream_event_schema

    for path, method in (('/v1/responses', 'post'), ('/v1/responses/{response_id}', 'get')):
        response = openapi_schema['paths'][path][method]['responses']['200']
        content = response.setdefault('content', {})
        content['text/event-stream'] = _openai_response_stream_event_schema_ref()


OPENAPI_NAMED_REQUEST_MODELS: dict[tuple[str, str], type[Any]] = {
    ('/api/v1/model-endpoints/{endpoint_id}', 'patch'): ModelEndpointPatchRequest,
    ('/v1/vector_stores', 'post'): NullableVectorStoreCreateRequest,
    ('/v1/vector_stores/{vector_store_id}', 'post'): NullableVectorStoreUpdateRequest,
    ('/v1/vector_stores/{vector_store_id}', 'patch'): NullableVectorStoreUpdateRequest,
    ('/v1/vector_stores/{vector_store_id}/files', 'post'): OpenAIVectorStoreFileAttachRequest,
    ('/v1/vector_stores/{vector_store_id}/files/{file_id}', 'post'): OpenAIVectorStoreFileUpdateRequest,
    ('/v1/vector_stores/{vector_store_id}/files/{file_id}', 'patch'): OpenAIVectorStoreFileUpdateRequest,
    ('/v1/vector_stores/{vector_store_id}/file_batches', 'post'): OpenAIVectorStoreFileBatchCreateRequest,
}


OPENAPI_RAW_TEXT_RESPONSE_MODELS: dict[tuple[str, str], type[Any]] = {
    ('/metrics', 'get'): PrometheusMetricsResponse,
    ('/v1/files/{file_id}/content', 'get'): OpenAIFileContentResponse,
}


def _install_openapi_model_schema(openapi_schema: dict[str, Any], model: type[Any]) -> dict[str, str]:
    schema = model.model_json_schema(ref_template='#/components/schemas/{model}')
    definitions = schema.pop('$defs', {})
    schemas = openapi_schema.setdefault('components', {}).setdefault('schemas', {})
    for name, definition in definitions.items():
        schemas[name] = definition
    schemas[model.__name__] = schema
    return {'$ref': f'#/components/schemas/{model.__name__}'}


def _install_named_route_openapi_contracts(openapi_schema: dict[str, Any]) -> None:
    for (path, method), model in OPENAPI_NAMED_REQUEST_MODELS.items():
        operation = openapi_schema['paths'][path][method]
        request_content = operation['requestBody']['content']['application/json']
        request_content['schema'] = _install_openapi_model_schema(openapi_schema, model)

    for (path, method), model in OPENAPI_RAW_TEXT_RESPONSE_MODELS.items():
        operation = openapi_schema['paths'][path][method]
        response_content = operation['responses']['200']['content']['text/plain']
        response_content['schema'] = _install_openapi_model_schema(openapi_schema, model)


def custom_openapi() -> dict[str, Any]:
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    _install_openai_response_stream_openapi_contract(openapi_schema)
    _install_named_route_openapi_contracts(openapi_schema)
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

@app.on_event('startup')
def startup_guardrails():
    validate_production_guardrails(settings)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=['GET', 'POST', 'PATCH', 'DELETE', 'OPTIONS'],
    allow_headers=['Authorization', 'Content-Type', 'Idempotency-Key', 'X-SVS-Tenant-Id', 'X-SVS-Business-Instance-Id', 'X-SVS-User-Id', 'X-SVS-Groups', 'X-SVS-Roles', 'X-SVS-Max-Security-Level'],
)
vs_repo, ingestion, retrieval, maintenance, bakeoff = VectorStoreRepository(), IngestionService(), RetrievalService(), MaintenanceService(), BakeoffService()

ADMIN_UI_SESSION_SCOPES = [
    'admin:read',
    'api_keys:read',
    'api_keys:write',
    'documents:write',
    'retrieval:read',
    'vector_stores:read',
    'vector_stores:write',
]


def should_enqueue_ingest(req: DocumentIngestRequest) -> bool:
    raw_len = len((req.content or '').encode('utf-8'))
    if req.attributes.get('force_sync') is True:
        return False
    if req.attributes.get('force_async') is True:
        return True
    return raw_len > settings.svs_ingest_inline_max_bytes


def _source_pdf_object_key(principal: Principal, filename: str | None, pdf_bytes: bytes) -> str:
    safe_name = f"{sanitize_stem(filename, 'uploaded-pdf')}.pdf"
    return (
        f"tenants/{principal.tenant_id}/business/{principal.business_instance_id}/"
        f"source-pdfs/{pdf_source_id(pdf_bytes)}/{safe_name}"
    )


async def marker_pdf_upload_request(
    *,
    file: UploadFile,
    content_bytes: bytes,
    title: str | None,
    mode: str,
    vector_store_id: str | None,
    knowledge_base_id: str | None,
    security_level: int,
    principal: Principal,
    source_uri: str | None = None,
    source_identity: str | None = None,
    attributes: dict[str, Any] | None = None,
    classification: str = 'tenant_private',
) -> DocumentIngestRequest:
    job_ids: list[str] = []
    try:
        output = await MarkerRunpodClient().process_pdf_bytes(
            filename=file.filename or 'uploaded.pdf',
            pdf_bytes=content_bytes,
            job_id_callback=job_ids.append,
        )
    except MarkerRunpodError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if output is None:
        raise HTTPException(status_code=502, detail='Marker RunPod PDF conversion failed')
    try:
        markdown = extract_markdown(output)
    except MarkerRunpodError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    source_key = _source_pdf_object_key(principal, file.filename, content_bytes)
    try:
        ObjectStore().put_bytes(source_key, content_bytes, file.content_type or 'application/pdf')
    except ObjectStoreError as exc:
        raise HTTPException(status_code=503, detail='Source PDF object-store write failed') from exc

    attrs = dict(attributes or {})
    attrs.update(marker_attribute_summary(
        original_filename=file.filename,
        pdf_bytes=content_bytes,
        output=output,
        job_id=job_ids[-1] if job_ids else None,
        source_object_key=source_key,
    ))
    return DocumentIngestRequest(
        vector_store_id=vector_store_id,
        knowledge_base_id=knowledge_base_id,
        title=title or file.filename or 'uploaded PDF',
        filename=markdown_filename_for_pdf(file.filename),
        mime_type='text/markdown',
        content=markdown,
        mode='pdf_markdown_external_v1',
        source_uri=source_uri or f'object://{source_key}',
        source_identity=source_identity,
        attributes=attrs,
        security_level=security_level,
        classification=classification,
        source_trust='external_pdf_parser',
    )


def _document_upload_attributes(attributes_json: str | None) -> dict[str, Any]:
    if attributes_json is None or not attributes_json.strip():
        return {}
    try:
        value = json.loads(attributes_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail='attributes_json must be valid JSON') from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=422, detail='attributes_json must contain a JSON object')
    return value


def _vector_store_unavailable_http_exception(exc: VectorStoreUnavailableError) -> HTTPException:
    detail = 'Vector store not found' if exc.reason == 'not_found' else 'Vector store not found or expired'
    return HTTPException(status_code=404, detail=detail)


def _ensure_vector_store_available_or_404(db: Session, principal: Principal, vector_store_id: str) -> None:
    try:
        require_active_vector_store(db, principal, vector_store_id)
    except VectorStoreUnavailableError as exc:
        raise _vector_store_unavailable_http_exception(exc) from exc


def _refresh_vector_store_activity_or_404(db: Session, principal: Principal, vector_store_id: str, *, usage_bytes_delta: int = 0) -> None:
    try:
        if refresh_vector_store_activity(db, principal, vector_store_id, usage_bytes_delta=usage_bytes_delta):
            return
        require_active_vector_store(db, principal, vector_store_id)
    except VectorStoreUnavailableError as exc:
        raise _vector_store_unavailable_http_exception(exc) from exc
    raise HTTPException(status_code=404, detail='Vector store not found or expired')


async def ingest_or_enqueue(req: DocumentIngestRequest, principal: Principal, db: Session):
    if req.vector_store_id:
        _refresh_vector_store_activity_or_404(db, principal, req.vector_store_id)
    try:
        if should_enqueue_ingest(req):
            result = ingestion.enqueue(db, principal, req)
        else:
            result = await ingestion.ingest_now(db, principal, req)
    except VectorStoreUnavailableError as exc:
        raise _vector_store_unavailable_http_exception(exc) from exc
    db.commit()
    return result


def _list_response(data: list[Any], has_more: bool = False) -> dict[str, Any]:
    def item_id(x):
        return x.get('id') if isinstance(x, dict) else getattr(x, 'id', None)
    return {'object': 'list', 'data': data, 'first_id': item_id(data[0]) if data else None, 'last_id': item_id(data[-1]) if data else None, 'has_more': has_more}


def _openai_idempotency_fingerprint(route: str, request_payload: dict[str, Any]) -> str:
    return stable_hash({'route': route, 'request': request_payload})


def _check_openai_idempotency(
    db: Session,
    principal: Principal,
    idempotency_key: str | None,
    *,
    route: str,
    request_payload: dict[str, Any],
) -> tuple[str, dict[str, Any] | None]:
    fingerprint = _openai_idempotency_fingerprint(route, request_payload)
    effective_key = idempotency_key if isinstance(idempotency_key, str) else None
    return fingerprint, check_idempotency(db, principal, effective_key, fingerprint)


def _store_openai_idempotency(
    db: Session,
    principal: Principal,
    idempotency_key: str | None,
    *,
    fingerprint: str,
    response: dict[str, Any],
) -> None:
    effective_key = idempotency_key if isinstance(idempotency_key, str) else None
    store_idempotency(db, principal, effective_key, fingerprint, response)


OPENAI_FILE_ID_ATTRIBUTE = '_openai_file_id'
OPENAI_FILE_PURPOSE_ATTRIBUTE = '_openai_purpose'
OPENAI_FILE_BYTES_ATTRIBUTE = '_openai_bytes'
OPENAI_FILE_MIME_TYPE_ATTRIBUTE = '_openai_mime_type'
VECTOR_STORE_FILE_CHUNKING_STRATEGY_ATTRIBUTE = '_openai_chunking_strategy'
VECTOR_STORE_FILE_INTERNAL_ATTRIBUTES = {'attached_from_file_id', '_file_batch_id', VECTOR_STORE_FILE_CHUNKING_STRATEGY_ATTRIBUTE}
VECTOR_STORE_FILE_STATUSES = {'in_progress', 'completed', 'failed', 'cancelled'}
OPENAI_FILE_BATCH_MAX_FILES = 2000
ZERO_FILE_BATCH_COUNTS = {'in_progress': 0, 'completed': 0, 'failed': 0, 'cancelled': 0, 'total': 0}
VECTOR_STORE_FILE_ADD_RATE_LIMIT_BUCKET = 'vector_store_file_adds'


def _new_openai_file_id() -> str:
    return f'file-{uuid.uuid4().hex[:24]}'


def _openai_file_attributes(row: Any) -> dict[str, Any]:
    return dict(row.get('file_attributes') or {})


def _enforce_vector_store_file_add_rate_limit(db: Session, principal: Principal, vector_store_id: str) -> None:
    enforce_resource_rate_limit(
        db,
        principal,
        resource_id=vector_store_id,
        bucket=VECTOR_STORE_FILE_ADD_RATE_LIMIT_BUCKET,
        limit_per_minute=settings.svs_vector_store_file_add_rate_limit_per_minute,
        resource_label='vector store file additions for',
    )


def _openai_file_id(row: Any) -> str:
    attrs = _openai_file_attributes(row)
    return str(attrs.get(OPENAI_FILE_ID_ATTRIBUTE) or row['id'])


def _openai_file_object_from_row(row: Any) -> dict[str, Any]:
    attrs = _openai_file_attributes(row)
    payload = {
        'id': _openai_file_id(row),
        'object': 'file',
        'bytes': int(attrs.get(OPENAI_FILE_BYTES_ATTRIBUTE) or row.get('bytes') or 0),
        'created_at': row['created_at'],
        'filename': row['filename'],
        'purpose': attrs.get(OPENAI_FILE_PURPOSE_ATTRIBUTE) or 'assistants',
    }
    if row.get('expires_at') is not None:
        payload['expires_at'] = row['expires_at']
    return payload


def _looks_like_utf16_text(raw: bytes) -> bool:
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        return True
    sample = raw[:200]
    if len(sample) < 4:
        return False
    even_nulls = sample[0::2].count(0)
    odd_nulls = sample[1::2].count(0)
    even_total = max(len(sample[0::2]), 1)
    odd_total = max(len(sample[1::2]), 1)
    return (even_nulls / even_total) >= 0.3 or (odd_nulls / odd_total) >= 0.3


def _decode_openai_text_upload(raw: bytes) -> str:
    try:
        return raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        pass
    if _looks_like_utf16_text(raw):
        try:
            return raw.decode('utf-16')
        except UnicodeDecodeError:
            pass
    raise HTTPException(status_code=415, detail='OpenAI-compatible file upload currently supports UTF-8, UTF-16, or ASCII text files, or configured PDF conversion')


def _openai_file_upload_expiration_seconds(anchor: str | None, seconds: Any) -> int | None:
    if anchor is None and seconds is None:
        return None
    if anchor != 'created_at':
        raise HTTPException(status_code=422, detail='expires_after.anchor must be created_at for file uploads')
    if seconds is None or isinstance(seconds, bool):
        raise HTTPException(status_code=422, detail='expires_after.seconds must be a positive integer')
    try:
        normalized_seconds = int(seconds)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail='expires_after.seconds must be a positive integer') from None
    if normalized_seconds <= 0:
        raise HTTPException(status_code=422, detail='expires_after.seconds must be a positive integer')
    return normalized_seconds


def _persist_openai_file_expiration(
    db: Session,
    principal: Principal,
    *,
    document_id: str,
    seconds: int | None,
) -> None:
    if seconds is None:
        return
    db.execute(text("""
        UPDATE documents
        SET expires_at = created_at + (:seconds * interval '1 second')
        WHERE id=:document_id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
    """), {
        'seconds': seconds,
        'document_id': document_id,
        'tenant_id': principal.tenant_id,
        'biz_id': principal.business_instance_id,
    })


def _public_vector_store_file_attributes(attrs: dict[str, Any] | None) -> dict[str, Any]:
    return {
        key: value
        for key, value in dict(attrs or {}).items()
        if key not in VECTOR_STORE_FILE_INTERNAL_ATTRIBUTES
    }


def _validated_vector_store_file_attributes(raw: Any | None, *, context: str) -> dict[str, Any]:
    try:
        return validate_openai_file_attributes(
            raw,
            context=context,
            reserved_keys=frozenset(VECTOR_STORE_FILE_INTERNAL_ATTRIBUTES),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _openai_attributes_payload(raw: dict[str, Any]) -> Any:
    return raw.get('attributes') if 'attributes' in raw else raw.get('metadata')


def _openai_file_select_sql(where_clause: str = '', suffix: str = '') -> str:
    return f'''
        SELECT d.id, d.knowledge_base_id, d.vector_store_id, d.title, d.filename, d.mime_type, d.source_uri,
               d.security_level, d.classification, d.allowed_groups, d.allowed_roles, d.source_trust, d.status,
               d.created_at AS created_at_ts,
               extract(epoch from d.created_at)::bigint AS created_at,
               extract(epoch from d.expires_at)::bigint AS expires_at,
               coalesce(dv.metadata #>> '{{attributes,_openai_file_id}}', d.id::text) AS public_file_id,
               coalesce(sum(octet_length(c.text)), 0)::bigint AS bytes,
               dv.id AS document_version_id,
               dv.object_key,
               dv.metadata->'attributes' AS file_attributes
        FROM documents d
        JOIN document_versions dv
          ON dv.id=d.current_version_id
         AND dv.document_id=d.id
         AND dv.tenant_id=d.tenant_id
         AND dv.business_instance_id=d.business_instance_id
        LEFT JOIN chunks c
          ON c.document_id=d.id
         AND c.document_version_id=d.current_version_id
         AND c.tenant_id=d.tenant_id
         AND c.business_instance_id=d.business_instance_id
         AND c.active=true
        WHERE d.tenant_id=:tenant_id AND d.business_instance_id=:biz_id
          AND d.status='active'
          {where_clause}
        GROUP BY d.id, d.knowledge_base_id, d.vector_store_id, d.title, d.filename, d.mime_type, d.source_uri,
                 d.security_level, d.classification, d.allowed_groups, d.allowed_roles, d.source_trust, d.status,
                 d.created_at, d.expires_at, dv.id, dv.object_key, dv.metadata
        {suffix}
    '''


def _get_openai_file_row(db: Session, principal: Principal, file_id: str):
    return db.execute(text(_openai_file_select_sql('''
          AND (
            d.id=:file_id
            OR dv.metadata #>> '{attributes,_openai_file_id}' = :file_id
          )
    ''', '''
        ORDER BY CASE WHEN d.id=:file_id THEN 0 ELSE 1 END, d.created_at DESC
        LIMIT 1
    ''')), {'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'file_id': file_id}).mappings().first()


def _resolve_document_row_for_file_id(db: Session, principal: Principal, file_id: str):
    row = _get_openai_file_row(db, principal, file_id)
    if not row:
        raise HTTPException(status_code=404, detail=f'File not found: {file_id}')
    return row


def _openai_vector_store_file_payload(row: Any) -> dict[str, Any]:
    raw_attrs = dict(row.get('attributes') or {})
    attrs = _public_vector_store_file_attributes(row.get('attributes'))
    public_file_id = row.get('public_file_id') or row.get('document_id') or row['id']
    payload = {
        'id': public_file_id,
        'object': 'vector_store.file',
        'vector_store_id': row['vector_store_id'],
        'document_id': row.get('document_id'),
        'vector_store_file_id': row['id'],
        'status': row['status'],
        'attributes': attrs,
        'usage_bytes': row.get('usage_bytes') or 0,
        'created_at': row.get('created_at'),
        'completed_at': row.get('completed_at'),
        'last_error': row.get('last_error'),
    }
    if raw_attrs.get(VECTOR_STORE_FILE_CHUNKING_STRATEGY_ATTRIBUTE) is not None:
        payload['chunking_strategy'] = raw_attrs[VECTOR_STORE_FILE_CHUNKING_STRATEGY_ATTRIBUTE]
    return payload


def _openai_file_batch_counts(file_counts: dict[str, Any] | None) -> dict[str, int]:
    counts = dict(file_counts or {})
    return {key: int(counts.get(key) or 0) for key in ZERO_FILE_BATCH_COUNTS}


def _openai_file_batch_payload(row: Any) -> dict[str, Any]:
    payload = {
        'id': row['id'],
        'object': 'vector_store.file_batch',
        'vector_store_id': row['vector_store_id'],
        'status': row['status'],
        'file_counts': _openai_file_batch_counts(row.get('file_counts')),
        'created_at': row.get('created_at'),
    }
    if row.get('completed_at') is not None:
        payload['completed_at'] = row['completed_at']
    return payload


def _vector_store_file_patch_attributes(row: Any, patch: dict[str, Any]) -> dict[str, Any]:
    attrs = _validated_vector_store_file_attributes(
        _openai_attributes_payload(patch),
        context='vector store file attributes',
    )
    existing = dict(row.get('attributes') or {})
    for key in VECTOR_STORE_FILE_INTERNAL_ATTRIBUTES:
        if key in existing and key not in attrs:
            attrs[key] = existing[key]
    return attrs


def _vector_store_file_attach_attributes(raw: dict[str, Any] | None, inherited: dict[str, Any] | None = None) -> dict[str, Any]:
    raw = raw or {}
    attrs = dict(inherited or {})
    attrs.update(_validated_vector_store_file_attributes(
        _openai_attributes_payload(raw),
        context='vector store file attributes',
    ))
    if raw.get('chunking_strategy') is not None:
        try:
            chunking_strategy = validate_openai_chunking_strategy(
                raw['chunking_strategy'],
                context='vector store file chunking_strategy',
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        attrs[VECTOR_STORE_FILE_CHUNKING_STRATEGY_ATTRIBUTE] = chunking_strategy
    return attrs


def _openai_file_batch_inline_file(raw: Any) -> Any:
    if not isinstance(raw, dict):
        return raw
    if 'attributes' not in raw and 'metadata' not in raw and raw.get('chunking_strategy') is None:
        return raw
    return {**raw, 'attributes': _vector_store_file_attach_attributes(raw)}


def _split_openai_file_batch_files(files: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    file_refs: list[dict[str, Any]] = []
    inline_files: list[dict[str, Any]] = []
    for raw in files:
        if isinstance(raw, dict) and raw.get('file_id'):
            file_refs.append({
                'file_id': raw['file_id'],
                'attributes': _vector_store_file_attach_attributes(raw),
            })
        else:
            inline_files.append(_openai_file_batch_inline_file(raw))
    return file_refs, inline_files


def _openai_file_batch_request_parts(payload: dict[str, Any]) -> dict[str, Any]:
    files = payload.get('files') or []
    file_ids = payload.get('file_ids') or []
    if not isinstance(files, list):
        raise HTTPException(status_code=422, detail='file batch files must be a list')
    if not isinstance(file_ids, list):
        raise HTTPException(status_code=422, detail='file batch file_ids must be a list')
    if files and file_ids:
        raise HTTPException(status_code=422, detail='file_ids and files are mutually exclusive for file batches')
    total = len(files) + len(file_ids)
    if total > OPENAI_FILE_BATCH_MAX_FILES:
        raise HTTPException(status_code=422, detail=f'file batch cannot exceed {OPENAI_FILE_BATCH_MAX_FILES} files')
    file_refs, inline_files = _split_openai_file_batch_files(files)
    return {
        'file_ids': file_ids,
        'file_id_attributes': _vector_store_file_attach_attributes(payload),
        'file_refs': file_refs,
        'inline_files': inline_files,
        'total': total,
    }


def _get_file_batch_row(db: Session, principal: Principal, vector_store_id: str, batch_id: str):
    return db.execute(text('''
        SELECT id, vector_store_id, status, file_counts,
               extract(epoch from created_at)::bigint AS created_at,
               extract(epoch from completed_at)::bigint AS completed_at
        FROM file_batches
        WHERE id=:id AND vector_store_id=:vs_id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
    '''), {'id': batch_id, 'vs_id': vector_store_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id}).mappings().first()


def _vector_store_file_row(db: Session, principal: Principal, vector_store_id: str, file_id: str):
    return db.execute(text('''
        SELECT f.id, f.vector_store_id, f.document_id, f.status, f.attributes, f.usage_bytes, f.last_error,
               extract(epoch from f.created_at)::bigint AS created_at,
               extract(epoch from f.completed_at)::bigint AS completed_at,
               coalesce(
                 f.attributes->>'attached_from_file_id',
                 dv.metadata #>> '{attributes,_openai_file_id}',
                 f.document_id,
                 f.id
               ) AS public_file_id
        FROM vector_store_files f
        LEFT JOIN documents d
          ON d.id=f.document_id
         AND d.tenant_id=f.tenant_id
         AND d.business_instance_id=f.business_instance_id
        LEFT JOIN document_versions dv
          ON dv.id=d.current_version_id
         AND dv.document_id=d.id
         AND dv.tenant_id=d.tenant_id
         AND dv.business_instance_id=d.business_instance_id
        WHERE f.vector_store_id=:vs_id
          AND f.tenant_id=:tenant_id
          AND f.business_instance_id=:biz_id
          AND (
            f.id=:file_id
            OR f.document_id=:file_id
            OR f.attributes->>'attached_from_file_id' = :file_id
            OR dv.metadata #>> '{attributes,_openai_file_id}' = :file_id
          )
        ORDER BY CASE WHEN f.id=:file_id THEN 0 ELSE 1 END, f.created_at DESC
        LIMIT 1
    '''), {'file_id': file_id, 'vs_id': vector_store_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id}).mappings().first()


def _vector_store_file_cursor_created_at(
    db: Session,
    principal: Principal,
    vector_store_id: str,
    file_id: str,
    *,
    batch_id: str | None = None,
):
    batch_clause = 'AND f.file_batch_id=:batch_id' if batch_id is not None else ''
    params = {
        'file_id': file_id,
        'vs_id': vector_store_id,
        'tenant_id': principal.tenant_id,
        'biz_id': principal.business_instance_id,
    }
    if batch_id is not None:
        params['batch_id'] = batch_id
    return db.execute(text(f'''
        SELECT f.created_at, f.id
        FROM vector_store_files f
        LEFT JOIN documents d
          ON d.id=f.document_id
         AND d.tenant_id=f.tenant_id
         AND d.business_instance_id=f.business_instance_id
        LEFT JOIN document_versions dv
          ON dv.id=d.current_version_id
         AND dv.document_id=d.id
         AND dv.tenant_id=d.tenant_id
         AND dv.business_instance_id=d.business_instance_id
        WHERE f.vector_store_id=:vs_id
          AND f.tenant_id=:tenant_id
          AND f.business_instance_id=:biz_id
          {batch_clause}
          AND (
            f.id=:file_id
            OR f.document_id=:file_id
            OR f.attributes->>'attached_from_file_id' = :file_id
            OR dv.metadata #>> '{{attributes,_openai_file_id}}' = :file_id
          )
        ORDER BY CASE WHEN f.id=:file_id THEN 0 ELSE 1 END, f.created_at DESC
        LIMIT 1
    '''), params).mappings().first()


def _list_vector_store_file_rows(
    db: Session,
    principal: Principal,
    vector_store_id: str,
    *,
    limit: int = 20,
    order: str = 'desc',
    after: str | None = None,
    before: str | None = None,
    status_filter: str | None = None,
    batch_id: str | None = None,
) -> tuple[list[Any], bool]:
    req_limit = min(max(limit, 1), 100)
    order = 'asc' if order == 'asc' else 'desc'
    params: dict[str, Any] = {
        'tenant_id': principal.tenant_id,
        'biz_id': principal.business_instance_id,
        'vs_id': vector_store_id,
        'limit': req_limit + 1,
    }
    filters = ['f.tenant_id=:tenant_id', 'f.business_instance_id=:biz_id', 'f.vector_store_id=:vs_id']
    if batch_id is not None:
        filters.append('f.file_batch_id=:batch_id')
        params['batch_id'] = batch_id
    if status_filter:
        if status_filter not in VECTOR_STORE_FILE_STATUSES:
            raise HTTPException(status_code=422, detail='Invalid vector store file status filter')
        filters.append('f.status=:status_filter')
        params['status_filter'] = status_filter
    if after:
        after_row = _vector_store_file_cursor_created_at(db, principal, vector_store_id, after, batch_id=batch_id)
        if after_row:
            after_op = '>' if order == 'asc' else '<'
            filters.append(f'(f.created_at {after_op} :after_created_at OR (f.created_at=:after_created_at AND f.id {after_op} :after_id))')
            params['after_created_at'] = after_row['created_at']
            params['after_id'] = after_row['id']
    if before:
        before_row = _vector_store_file_cursor_created_at(db, principal, vector_store_id, before, batch_id=batch_id)
        if before_row:
            before_op = '<' if order == 'asc' else '>'
            filters.append(f'(f.created_at {before_op} :before_created_at OR (f.created_at=:before_created_at AND f.id {before_op} :before_id))')
            params['before_created_at'] = before_row['created_at']
            params['before_id'] = before_row['id']
    where_clause = ' AND '.join(filters)
    rows = db.execute(text(f'''
        SELECT f.id, f.vector_store_id, f.document_id, f.status, f.attributes, f.usage_bytes, f.last_error,
               extract(epoch from f.created_at)::bigint AS created_at,
               extract(epoch from f.completed_at)::bigint AS completed_at,
               coalesce(
                 f.attributes->>'attached_from_file_id',
                 dv.metadata #>> '{{attributes,_openai_file_id}}',
                 f.document_id,
                 f.id
               ) AS public_file_id
        FROM vector_store_files f
        LEFT JOIN documents d
          ON d.id=f.document_id
         AND d.tenant_id=f.tenant_id
         AND d.business_instance_id=f.business_instance_id
        LEFT JOIN document_versions dv
          ON dv.id=d.current_version_id
         AND dv.document_id=d.id
         AND dv.tenant_id=d.tenant_id
         AND dv.business_instance_id=d.business_instance_id
        WHERE {where_clause}
        ORDER BY f.created_at {order.upper()}, f.id {order.upper()} LIMIT :limit
    '''), params).mappings().all()
    has_more = len(rows) > req_limit
    return list(rows[:req_limit]), has_more


def _link_existing_document_to_vector_store(
    db: Session,
    principal: Principal,
    vector_store_id: str,
    file_id: str,
    *,
    attributes: dict[str, Any] | None = None,
    file_batch_id: str | None = None,
) -> str:
    existing = db.execute(text('''
        SELECT id FROM vector_store_files
        WHERE tenant_id=:tenant_id AND business_instance_id=:biz_id
          AND vector_store_id=:vs_id AND document_id=:doc_id
        LIMIT 1
    '''), {'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'vs_id': vector_store_id, 'doc_id': file_id}).mappings().first()
    if existing:
        _refresh_vector_store_activity_or_404(db, principal, vector_store_id)
        return existing['id']
    doc = db.execute(text('''
        SELECT d.id, coalesce(sum(octet_length(c.text)), 0)::bigint AS usage_bytes
        FROM documents d
        LEFT JOIN chunks c
          ON c.document_id=d.id
         AND c.tenant_id=d.tenant_id
         AND c.business_instance_id=d.business_instance_id
         AND c.active=true
        WHERE d.id=:doc_id AND d.tenant_id=:tenant_id AND d.business_instance_id=:biz_id
        GROUP BY d.id
    '''), {'doc_id': file_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id}).mappings().first()
    if not doc:
        raise HTTPException(status_code=404, detail=f'File not found: {file_id}')
    attrs = dict(attributes or {})
    attrs.setdefault('attached_from_file_id', file_id)
    vsf_id = new_id('vsf')
    db.execute(jsonb_text('''
        INSERT INTO vector_store_files(id, tenant_id, business_instance_id, vector_store_id, document_id, file_batch_id, status, attributes, usage_bytes, completed_at)
        VALUES (:id, :tenant_id, :biz_id, :vs_id, :doc_id, :batch_id, 'completed', CAST(:attrs AS jsonb), :usage_bytes, now())
    ''', 'attrs'), {
        'id': vsf_id,
        'tenant_id': principal.tenant_id,
        'biz_id': principal.business_instance_id,
        'vs_id': vector_store_id,
        'doc_id': file_id,
        'batch_id': file_batch_id,
        'attrs': jsonb_param(attrs),
        'usage_bytes': int(doc['usage_bytes'] or 0),
    })
    _refresh_vector_store_activity_or_404(
        db,
        principal,
        vector_store_id,
        usage_bytes_delta=int(doc['usage_bytes'] or 0),
    )
    return vsf_id


async def _attach_existing_document_ids_to_vector_store(
    db: Session,
    principal: Principal,
    vector_store_id: str,
    file_ids: list[str],
    *,
    attributes: dict[str, Any] | None = None,
    file_batch_id: str | None = None,
) -> list[str]:
    _ensure_vector_store_available_or_404(db, principal, vector_store_id)
    attached_ids: list[str] = []
    for file_id in file_ids:
        doc = _resolve_document_row_for_file_id(db, principal, file_id)
        link_attrs = dict(attributes or {})
        link_attrs.setdefault('attached_from_file_id', file_id)
        if doc['vector_store_id'] == vector_store_id:
            attached_ids.append(_link_existing_document_to_vector_store(
                db,
                principal,
                vector_store_id,
                doc['id'],
                attributes=link_attrs,
                file_batch_id=file_batch_id,
            ))
            continue
        chunk_rows = db.execute(text('''
            SELECT text FROM chunks
            WHERE document_id=:doc_id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
              AND active=true AND security_level <= :max_lvl
            ORDER BY ordinal ASC
        '''), {'doc_id': doc['id'], 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'max_lvl': principal.max_security_level}).mappings().all()
        content = '\n\n'.join(r['text'] for r in chunk_rows if r['text'])
        if not content:
            raise HTTPException(status_code=409, detail=f'File has no readable indexed content to attach: {file_id}')
        attrs = link_attrs
        if file_batch_id:
            attrs['_file_batch_id'] = file_batch_id
        req = DocumentIngestRequest(
            vector_store_id=vector_store_id,
            knowledge_base_id=doc['knowledge_base_id'],
            title=doc['title'],
            filename=doc['filename'],
            mime_type=doc['mime_type'] or 'text/markdown',
            content=content,
            mode='markdown_docs_v1',
            source_uri=f"exais-document://{file_id}",
            attributes=attrs,
            security_level=doc['security_level'],
            classification=doc['classification'],
            allowed_groups=list(doc['allowed_groups'] or []),
            allowed_roles=list(doc['allowed_roles'] or []),
            source_trust=doc['source_trust'] or 'user_upload',
        )
        result = await ingestion.ingest_now(db, principal, req)
        if not result.vector_store_file_id:
            raise HTTPException(status_code=500, detail=f'File attach did not create a vector store file: {file_id}')
        attached_ids.append(result.vector_store_file_id)
    return attached_ids


@app.get('/healthz', response_model=HealthResponse, response_model_exclude_unset=True)
def healthz():
    return {'ok': True, 'service': 'svs-api', 'version': settings.svs_product_version, 'sparse_backend': settings.svs_sparse_backend, 'dense_backend': settings.svs_dense_backend}


def readiness_payload(db: Session, qdrant_adapter) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    try:
        db.execute(text('SELECT 1'))
        checks['db'] = True
    except Exception:
        checks['db'] = False
    if settings.svs_dense_backend == 'qdrant' and settings.svs_index_strict:
        qdrant_ok, _ = qdrant_adapter.healthcheck()
        checks['qdrant'] = qdrant_ok
    ready = all(checks.values())
    return {'ready': ready, **checks}


@app.get('/readyz', response_model=ReadinessResponse, response_model_exclude_unset=True)
def readyz(response: Response, db: Session = Depends(get_session)):
    payload = readiness_payload(db, retrieval.qdrant)
    if not payload['ready']:
        response.status_code = 503
    return payload


OBSERVABILITY_METRIC_SQL: tuple[tuple[str, str], ...] = (
    ('svs_ingestion_jobs_queued', "SELECT count(*) FROM ingestion_jobs WHERE status='queued'"),
    ('svs_ingestion_jobs_running', "SELECT count(*) FROM ingestion_jobs WHERE status='running'"),
    ('svs_ingestion_jobs_failed', "SELECT count(*) FROM ingestion_jobs WHERE status='failed'"),
    (
        'svs_ingestion_jobs_oldest_queued_age_seconds',
        "SELECT coalesce(extract(epoch FROM (now() - min(created_at))), 0) FROM ingestion_jobs WHERE status='queued'",
    ),
    (
        'svs_worker_jobs_running',
        "SELECT count(*) FROM ingestion_jobs WHERE status='running' AND locked_by IS NOT NULL",
    ),
    ('svs_worker_jobs_completed_total', "SELECT count(*) FROM ingestion_jobs WHERE status='completed'"),
    ('svs_worker_jobs_failed_total', "SELECT count(*) FROM ingestion_jobs WHERE status='failed'"),
    (
        'svs_worker_last_completed_timestamp_seconds',
        "SELECT coalesce(max(extract(epoch FROM completed_at)), 0) FROM ingestion_jobs WHERE status='completed'",
    ),
    ('svs_vector_stores_active', "SELECT count(*) FROM vector_stores WHERE status IN ('active','completed')"),
    (
        'svs_chunks_index_pending',
        "SELECT count(*) FROM chunks WHERE dense_index_status <> 'indexed' OR sparse_index_status <> 'indexed'",
    ),
    ('svs_chunks_dense_index_pending', "SELECT count(*) FROM chunks WHERE dense_index_status <> 'indexed'"),
    ('svs_chunks_sparse_index_pending', "SELECT count(*) FROM chunks WHERE sparse_index_status <> 'indexed'"),
    (
        'svs_chunks_indexed_total',
        "SELECT count(*) FROM chunks WHERE dense_index_status='indexed' AND sparse_index_status='indexed'",
    ),
    (
        'svs_object_store_documents_tracked_total',
        "SELECT count(*) FROM document_versions WHERE object_key IS NOT NULL OR parsed_object_key IS NOT NULL",
    ),
    (
        'svs_object_store_bytes_tracked',
        "SELECT coalesce(sum(usage_bytes), 0) FROM vector_store_files WHERE status <> 'cancelled'",
    ),
    ('svs_storage_vector_store_usage_bytes', "SELECT coalesce(sum(usage_bytes), 0) FROM vector_stores"),
    ('svs_security_audit_events_denied_total', "SELECT count(*) FROM audit_events WHERE allowed=false"),
    (
        'svs_security_acl_denied_retrieval_total',
        "SELECT count(*) FROM audit_events WHERE event_type='retrieval' AND allowed=false",
    ),
    (
        'svs_usage_cost_estimate_usd_total',
        "SELECT coalesce(sum(cost_estimate_usd), 0) FROM usage_events WHERE cost_estimate_usd IS NOT NULL",
    ),
    (
        'svs_cost_events_with_estimate_total',
        "SELECT count(*) FROM usage_events WHERE cost_estimate_usd IS NOT NULL",
    ),
    ('svs_usage_retrieval_queries_total', "SELECT count(*) FROM usage_events WHERE event_type='retrieval.query'"),
    (
        'svs_backup_bundle_success_total',
        "SELECT count(*) FROM backup_bundles WHERE status IN ('completed','succeeded','success')",
    ),
    ('svs_backup_bundle_failed_total', "SELECT count(*) FROM backup_bundles WHERE status IN ('failed','error')"),
    (
        'svs_backup_bundle_last_success_timestamp_seconds',
        "SELECT coalesce(max(extract(epoch FROM completed_at)), 0) FROM backup_bundles WHERE completed_at IS NOT NULL AND status IN ('completed','succeeded','success')",
    ),
    (
        'svs_backup_freshness_age_seconds',
        "SELECT coalesce(extract(epoch FROM (now() - max(completed_at))), 0) FROM backup_bundles WHERE completed_at IS NOT NULL AND status IN ('completed','succeeded','success')",
    ),
    (
        'svs_backup_manifest_available_total',
        "SELECT count(*) FROM backup_bundles WHERE manifest <> '{}'::jsonb",
    ),
    (
        'svs_backup_manifest_artifacts_total',
        "SELECT coalesce(sum(jsonb_array_length(CASE WHEN jsonb_typeof(manifest->'artifacts')='array' THEN manifest->'artifacts' ELSE '[]'::jsonb END)), 0) FROM backup_bundles",
    ),
)


def _prometheus_label_value(value: Any) -> str:
    return str(value).replace('\\', '\\\\').replace('\n', '\\n').replace('"', '\\"')


def _prometheus_metric_value(value: Any) -> str:
    try:
        numeric = float(value or 0)
    except (TypeError, ValueError):
        numeric = 0.0
    if numeric.is_integer():
        return str(int(numeric))
    return f'{numeric:.10g}'


def _prometheus_metric_line(name: str, value: Any, labels: dict[str, Any] | None = None) -> str:
    if labels:
        label_text = ','.join(f'{key}="{_prometheus_label_value(labels[key])}"' for key in sorted(labels))
        return f'{name}{{{label_text}}} {_prometheus_metric_value(value)}'
    return f'{name} {_prometheus_metric_value(value)}'


def _metric_scalar(db: Session, sql: str) -> Any:
    try:
        return db.execute(text(sql)).scalar() or 0
    except Exception:
        return 0


@app.get('/metrics', response_class=PlainTextResponse, response_model=PrometheusMetricsResponse)
def metrics(db: Session = Depends(get_session)):
    lines = [
        _prometheus_metric_line('svs_api_build_info', 1, {'version': settings.svs_product_version}),
        _prometheus_metric_line(
            'svs_api_index_strict_enabled',
            1 if settings.svs_index_strict else 0,
            {'dense_backend': settings.svs_dense_backend, 'sparse_backend': settings.svs_sparse_backend},
        ),
    ]
    for name, sql in OBSERVABILITY_METRIC_SQL:
        lines.append(_prometheus_metric_line(name, _metric_scalar(db, sql)))
    return '\n'.join(lines) + '\n'


@app.post('/v1/files', response_model=OpenAIFile, response_model_exclude_unset=True)
async def create_openai_file(
    file: UploadFile = File(...),
    purpose: str = Form(...),
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    expires_after_anchor: Annotated[str | None, Form(alias='expires_after[anchor]')] = None,
    expires_after_seconds: Annotated[int | str | None, Form(alias='expires_after[seconds]')] = None,
):
    ensure_scope(principal, 'documents:write')
    enforce_rate_limit(db, principal, 'files.create')
    raw = await file.read()
    expiration_seconds = _openai_file_upload_expiration_seconds(expires_after_anchor, expires_after_seconds)
    idempotency_fingerprint, cached = _check_openai_idempotency(
        db,
        principal,
        idempotency_key,
        route='POST /v1/files',
        request_payload={
            'filename': file.filename,
            'content_type': file.content_type,
            'purpose': purpose,
            'expires_after': {'anchor': expires_after_anchor, 'seconds': expiration_seconds} if expiration_seconds is not None else None,
            'bytes': len(raw),
            'sha256': sha256(raw).hexdigest(),
        },
    )
    if cached:
        return cached
    file_id = _new_openai_file_id()
    attrs = {
        OPENAI_FILE_ID_ATTRIBUTE: file_id,
        OPENAI_FILE_PURPOSE_ATTRIBUTE: purpose,
        OPENAI_FILE_BYTES_ATTRIBUTE: len(raw),
        OPENAI_FILE_MIME_TYPE_ATTRIBUTE: file.content_type or 'application/octet-stream',
    }
    upload_security_level = 1 if principal.max_security_level >= 1 else principal.max_security_level
    if is_marker_pdf_upload(file.filename, file.content_type, 'auto_detect_v1'):
        req = await marker_pdf_upload_request(
            file=file,
            content_bytes=raw,
            title=file.filename or file_id,
            mode='auto_detect_v1',
            vector_store_id=None,
            knowledge_base_id=None,
            security_level=upload_security_level,
            principal=principal,
        )
        req.attributes.update(attrs)
    else:
        content = _decode_openai_text_upload(raw)
        req = DocumentIngestRequest(
            vector_store_id=None,
            knowledge_base_id=None,
            title=file.filename or file_id,
            filename=file.filename or f'{file_id}.txt',
            mime_type=file.content_type or 'text/plain',
            content=content,
            mode='auto_detect_v1',
            source_uri=f'openai-file://{file_id}',
            attributes=attrs,
            security_level=upload_security_level,
            source_trust='openai_file_upload',
        )
    result = await ingestion.ingest_now(db, principal, req)
    if not result.document_id:
        raise HTTPException(status_code=500, detail='File upload did not create a document')
    _persist_openai_file_expiration(db, principal, document_id=result.document_id, seconds=expiration_seconds)
    row = _get_openai_file_row(db, principal, file_id)
    if not row:
        raise HTTPException(status_code=500, detail='Uploaded file could not be retrieved')
    payload = _openai_file_object_from_row(row)
    _store_openai_idempotency(db, principal, idempotency_key, fingerprint=idempotency_fingerprint, response=payload)
    db.commit()
    return payload


@app.get('/v1/files', response_model=OpenAIFileListResponse, response_model_exclude_unset=True)
def list_openai_files(
    purpose: str | None = None,
    limit: int = 10000,
    order: str = Query(default='desc', pattern='^(asc|desc)$'),
    after: str | None = None,
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
):
    ensure_scope(principal, ['documents:read', 'documents:write', 'retrieval:read'], any_of=True)
    enforce_rate_limit(db, principal, 'files.list')
    req_limit = min(max(limit, 1), 10000)
    order = 'asc' if order == 'asc' else 'desc'
    params: dict[str, Any] = {'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'limit': req_limit + 1}
    filters = ["AND dv.metadata #>> '{attributes,_openai_file_id}' IS NOT NULL"]
    if purpose:
        filters.append("AND dv.metadata #>> '{attributes,_openai_purpose}' = :purpose")
        params['purpose'] = purpose
    if after:
        after_row = _get_openai_file_row(db, principal, after)
        if after_row:
            after_op = '>' if order == 'asc' else '<'
            filters.append(
                f"AND (d.created_at {after_op} :after_created_at "
                f"OR (d.created_at=:after_created_at AND coalesce(dv.metadata #>> '{{attributes,_openai_file_id}}', d.id::text) {after_op} :after_file_id))"
            )
            params['after_created_at'] = after_row['created_at_ts']
            params['after_file_id'] = after_row.get('public_file_id') or _openai_file_id(after_row)
    rows = db.execute(text(_openai_file_select_sql(
        '\n          '.join(filters),
        f'ORDER BY d.created_at {order.upper()}, public_file_id {order.upper()} LIMIT :limit',
    )), params).mappings().all()
    has_more = len(rows) > req_limit
    rows = rows[:req_limit]
    return _list_response([_openai_file_object_from_row(r) for r in rows], has_more)


@app.get('/v1/files/{file_id}', response_model=OpenAIFile, response_model_exclude_unset=True)
def get_openai_file(file_id: str, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, ['documents:read', 'documents:write', 'retrieval:read'], any_of=True)
    enforce_rate_limit(db, principal, 'files.retrieve')
    row = _resolve_document_row_for_file_id(db, principal, file_id)
    return _openai_file_object_from_row(row)


@app.get('/v1/files/{file_id}/content', response_class=PlainTextResponse, response_model=OpenAIFileContentResponse)
def get_openai_file_content(file_id: str, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, ['documents:read', 'documents:write', 'retrieval:read'], any_of=True)
    enforce_rate_limit(db, principal, 'files.content')
    row = _resolve_document_row_for_file_id(db, principal, file_id)
    content = ObjectStore().get_text(row['object_key']) if row['object_key'] else ''
    if not content:
        chunks = db.execute(text('''
            SELECT text FROM chunks
            WHERE document_id=:doc_id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
              AND active=true AND security_level <= :max_lvl
            ORDER BY ordinal ASC
        '''), {'doc_id': row['id'], 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'max_lvl': principal.max_security_level}).mappings().all()
        content = '\n\n'.join(r['text'] for r in chunks if r['text'])
    if not content:
        raise HTTPException(status_code=404, detail='No readable content found for file')
    return PlainTextResponse(content, media_type='text/plain')


@app.delete('/v1/files/{file_id}', response_model=OpenAIFileDeletedResponse, response_model_exclude_unset=True)
def delete_openai_file(
    file_id: str,
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
):
    ensure_scope(principal, 'documents:write')
    enforce_rate_limit(db, principal, 'files.delete')
    idempotency_fingerprint, cached = _check_openai_idempotency(
        db,
        principal,
        idempotency_key,
        route='DELETE /v1/files/{file_id}',
        request_payload={'file_id': file_id},
    )
    if cached:
        return cached
    row = _resolve_document_row_for_file_id(db, principal, file_id)
    public_file_id = _openai_file_id(row)
    affected_rows = db.execute(text('''
        SELECT DISTINCT document_id
        FROM vector_store_files
        WHERE tenant_id=:tenant_id AND business_instance_id=:biz_id
          AND document_id IS NOT NULL
          AND (
            document_id=:doc_id
            OR attributes->>'attached_from_file_id' = :public_file_id
          )
    '''), {'doc_id': row['id'], 'public_file_id': public_file_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id}).mappings().all()
    affected_doc_ids = sorted({row['id'], *(r['document_id'] for r in affected_rows if r['document_id'])})
    db.execute(text('''
        UPDATE vector_store_files
        SET status='cancelled'
        WHERE tenant_id=:tenant_id AND business_instance_id=:biz_id
          AND (
            document_id = ANY(:doc_ids)
            OR attributes->>'attached_from_file_id' = :public_file_id
          )
    '''), {'doc_ids': affected_doc_ids, 'public_file_id': public_file_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id})
    db.execute(text('''
        UPDATE documents
        SET status='deleted'
        WHERE id = ANY(:doc_ids) AND tenant_id=:tenant_id AND business_instance_id=:biz_id
    '''), {'doc_ids': affected_doc_ids, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id})
    db.execute(text("SELECT set_config('svs.system_worker', 'true', true)"))
    db.execute(text('''
        UPDATE chunks
        SET active=false, deleted_at=now(), dense_index_status='delete_queued', sparse_index_status='delete_queued'
        WHERE document_id = ANY(:doc_ids) AND tenant_id=:tenant_id AND business_instance_id=:biz_id
    '''), {'doc_ids': affected_doc_ids, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id})
    for doc_id in affected_doc_ids:
        enqueue_purge_stale_vectors(db, principal, document_id=doc_id, reason='openai_file_deleted')
    response = {'id': public_file_id, 'object': 'file', 'deleted': True}
    _store_openai_idempotency(db, principal, idempotency_key, fingerprint=idempotency_fingerprint, response=response)
    db.commit()
    return response


@app.get('/api/v1/vectorization/modes', response_model=VectorizationModesResponse)
def list_modes():
    return {'modes': vectorization_modes()}


@app.get('/api/v1/models/registry', response_model=ModelRegistryResponse)
def list_models():
    return model_registry()


@app.get('/api/v1/retrieval/profiles', response_model=RetrievalProfilesResponse)
def list_profiles():
    return {'profiles': retrieval_profiles()}


@app.get('/v1/experts', response_model=ExpertProfileListResponse)
def list_experts(
    jurisdiction_key: str | None = None,
    corpus: ExpertCorpus | None = None,
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
):
    ensure_scope(principal, 'retrieval:read')
    enforce_rate_limit(db, principal, 'experts.list')
    # WAVE-125: filters narrow the already-visible set; they never widen it.
    return list_expert_profiles(db, principal, jurisdiction_key=jurisdiction_key, corpus=corpus)


@app.get('/v1/experts/{expert_id}', response_model=ExpertProfile)
def get_expert_profile(
    expert_id: str,
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
):
    ensure_scope(principal, 'retrieval:read')
    enforce_rate_limit(db, principal, 'experts.retrieve')
    try:
        return resolve_expert_profile(db, principal, expert_id)
    except ExpertProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail='Expert profile not found') from exc


def _expert_idempotency_fingerprint(
    route: str,
    principal: Principal,
    expert_id: str,
    payload: dict[str, Any],
) -> str:
    return stable_hash({
        'route': route,
        'expert_id': expert_id,
        'api_key_id': principal.api_key_id,
        'user_id': principal.user_id,
        'request': payload,
    })


def _ensure_external_user_binding(principal: Principal, external_user_id: str | None) -> None:
    """WAVE-125: a user-bound key may only speak for its own external_id.

    When the principal's bound user has an ``external_id`` and the caller also
    supplies ``external_user_id``, the two must agree. Keys without a bound
    external_id (cell keys) keep the caller-side correlation id as-is.
    """
    bound = (principal.external_id or '').strip()
    supplied = (external_user_id or '').strip()
    if bound and supplied and bound != supplied:
        raise HTTPException(
            status_code=403,
            detail={
                'error': 'external_user_id_mismatch',
                'message': 'external_user_id does not match the user bound to this API key',
            },
        )


def _require_scoped_expert_session(
    db: Session,
    principal: Principal,
    *,
    expert_id: str,
    session_id: str,
    external_user_id: str | None,
    conversation_id: str | None,
):
    _ensure_external_user_binding(principal, external_user_id)
    session = get_expert_session(db, principal, session_id)
    if (
        session is None
        or session.expert_id != expert_id
        or (session.external_user_id or None) != (external_user_id or None)
        or (session.conversation_id or None) != (conversation_id or None)
    ):
        raise ExpertSessionNotFound('expert session not found')
    return session


@app.post('/v1/experts/{expert_id}/messages', response_model=ExpertMessageResponse)
async def post_expert_message(
    expert_id: str,
    req: ExpertMessageRequest,
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
):
    ensure_scope(principal, 'retrieval:read')
    enforce_rate_limit(db, principal, 'experts.messages.create')
    _ensure_external_user_binding(principal, req.external_user_id)
    bound_req = req.bind_expert_id(expert_id)
    fingerprint = _expert_idempotency_fingerprint(
        'experts.messages.create',
        principal,
        expert_id,
        req.model_dump(mode='json'),
    )
    cached = check_idempotency(db, principal, idempotency_key, fingerprint)
    if cached is not None:
        return ExpertMessageResponse.model_validate(cached)
    try:
        response = await run_expert_turn(db, principal, bound_req)
    except ExpertProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail='Expert profile not found') from exc
    except ExpertSessionNotFound as exc:
        raise HTTPException(status_code=404, detail='Expert session not found') from exc
    except ExpertRetrievalPlanningError as exc:
        db.commit()
        raise HTTPException(status_code=422, detail='Expert retrieval plan is unavailable') from exc
    except ExpertCitationIntegrityError as exc:
        db.commit()
        raise HTTPException(status_code=502, detail='Expert answer failed citation integrity validation') from exc
    except ExpertChatGatewayError as exc:
        db.commit()
        raise HTTPException(status_code=503, detail='Expert model service unavailable') from exc
    record_expert_turn_accounting(
        db,
        principal,
        response,
        external_user_id=req.external_user_id,
        conversation_id=req.conversation_id,
    )
    payload = response.model_dump(mode='json')
    store_idempotency(db, principal, idempotency_key, fingerprint, payload)
    db.commit()
    return response


@app.post(
    '/v1/experts/{expert_id}/sessions/{session_id}/fork',
    response_model=ExpertSessionForkResponse,
)
def fork_expert_session_route(
    expert_id: str,
    session_id: str,
    req: ExpertSessionForkRequest,
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
):
    ensure_scope(principal, 'retrieval:read')
    enforce_rate_limit(db, principal, 'experts.sessions.fork')
    _ensure_external_user_binding(principal, req.external_user_id)
    fingerprint = _expert_idempotency_fingerprint(
        'experts.sessions.fork',
        principal,
        expert_id,
        {'session_id': session_id, **req.model_dump(mode='json')},
    )
    cached = check_idempotency(db, principal, idempotency_key, fingerprint)
    if cached is not None:
        return ExpertSessionForkResponse.model_validate(cached)
    try:
        resolve_expert_profile(db, principal, expert_id)
        parent = get_expert_session(db, principal, session_id)
        if (
            parent is None
            or parent.expert_id != expert_id
            or (parent.external_user_id or None) != req.external_user_id
            or (parent.conversation_id or None) != req.conversation_id
        ):
            raise ExpertSessionNotFound('expert session not found')
        child = fork_expert_session(db, principal, session_id, label=req.label)
    except ExpertProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail='Expert profile not found') from exc
    except ExpertSessionNotFound as exc:
        raise HTTPException(status_code=404, detail='Expert session not found') from exc
    response = ExpertSessionForkResponse(
        expert_id=child.expert_id,
        session_id=child.id,
        parent_session_id=session_id,
        external_user_id=child.external_user_id,
        conversation_id=child.conversation_id,
        label=child.label,
    )
    payload = response.model_dump(mode='json')
    store_idempotency(db, principal, idempotency_key, fingerprint, payload)
    db.commit()
    return response


@app.post('/v1/experts/{expert_id}/feedback', response_model=ExpertFeedbackResponse)
def post_expert_feedback(
    expert_id: str,
    req: ExpertFeedbackRequest,
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
):
    ensure_scope(principal, 'retrieval:read')
    enforce_rate_limit(db, principal, 'experts.feedback.create')
    fingerprint = _expert_idempotency_fingerprint(
        'experts.feedback.create',
        principal,
        expert_id,
        req.model_dump(mode='json'),
    )
    cached = check_idempotency(db, principal, idempotency_key, fingerprint)
    if cached is not None:
        return ExpertFeedbackResponse.model_validate(cached)
    try:
        resolve_expert_profile(db, principal, expert_id)
        _require_scoped_expert_session(
            db,
            principal,
            expert_id=expert_id,
            session_id=req.session_id,
            external_user_id=req.external_user_id,
            conversation_id=req.conversation_id,
        )
        candidates = extract_candidate_memory_events(
            ExpertTurnRecord(
                session_id=req.session_id,
                expert_id=expert_id,
                source_message_id=req.message_id,
                memory_candidates=req.memory_candidates,
            ),
            DEFAULT_EXPERT_MEMORY_POLICY,
        )
        feedback_id = record_expert_feedback(
            db,
            principal,
            req.session_id,
            message_id=req.message_id,
            feedback_type=req.feedback_type,
            rating=req.rating,
            comment=req.comment,
            payload={'memory_candidate_count': len(req.memory_candidates)},
        )
        candidates = [
            candidate.model_copy(update={'source_feedback_id': feedback_id})
            for candidate in candidates
        ]
        for candidate in candidates:
            record_expert_memory_event(
                db,
                principal,
                req.session_id,
                event_id=candidate.id,
                event_type=candidate.event_type,
                payload=candidate.payload,
                confidence=candidate.confidence,
                source_message_id=candidate.source_message_id,
                source_feedback_id=candidate.source_feedback_id,
            )
        feedback = get_expert_feedback_record(db, principal, req.session_id, feedback_id)
        if feedback is None:
            raise ExpertSessionNotFound('expert feedback not found')
    except ExpertProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail='Expert profile not found') from exc
    except ExpertSessionNotFound as exc:
        raise HTTPException(status_code=404, detail='Expert session or message not found') from exc
    except (ExpertInteractionSensitiveDataError, ValueError) as exc:
        raise HTTPException(status_code=422, detail='Expert feedback failed governance validation') from exc
    response = ExpertFeedbackResponse(
        expert_id=expert_id,
        session_id=req.session_id,
        feedback=feedback,
        memory_candidates=candidates,
    )
    payload = response.model_dump(mode='json')
    store_idempotency(db, principal, idempotency_key, fingerprint, payload)
    db.commit()
    return response


@app.get(
    '/v1/experts/{expert_id}/sessions/{session_id}/memory',
    response_model=ExpertMemoryListResponse,
)
def get_expert_memory(
    expert_id: str,
    session_id: str,
    external_user_id: str | None = Query(default=None, max_length=255),
    conversation_id: str | None = Query(default=None, max_length=255),
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
):
    ensure_scope(principal, 'retrieval:read')
    enforce_rate_limit(db, principal, 'experts.memory.list')
    try:
        resolve_expert_profile(db, principal, expert_id)
        _require_scoped_expert_session(
            db,
            principal,
            expert_id=expert_id,
            session_id=session_id,
            external_user_id=external_user_id,
            conversation_id=conversation_id,
        )
        events = list_expert_memory_events(db, principal, session_id)
    except ExpertProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail='Expert profile not found') from exc
    except ExpertSessionNotFound as exc:
        raise HTTPException(status_code=404, detail='Expert session not found') from exc
    return ExpertMemoryListResponse(expert_id=expert_id, session_id=session_id, data=events)


@app.post(
    '/v1/experts/{expert_id}/sessions/{session_id}/memory/{memory_event_id}/promote',
    response_model=ExpertMemoryEvent,
)
def promote_expert_memory(
    expert_id: str,
    session_id: str,
    memory_event_id: str,
    req: ExpertMemoryPromotionRequest,
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
):
    ensure_scope(principal, 'retrieval:read')
    enforce_rate_limit(db, principal, 'experts.memory.promote')
    fingerprint = _expert_idempotency_fingerprint(
        'experts.memory.promote',
        principal,
        expert_id,
        {'session_id': session_id, 'memory_event_id': memory_event_id, **req.model_dump(mode='json')},
    )
    cached = check_idempotency(db, principal, idempotency_key, fingerprint)
    if cached is not None:
        return ExpertMemoryEvent.model_validate(cached)
    try:
        resolve_expert_profile(db, principal, expert_id)
        _require_scoped_expert_session(
            db,
            principal,
            expert_id=expert_id,
            session_id=session_id,
            external_user_id=req.external_user_id,
            conversation_id=req.conversation_id,
        )
        event = promote_expert_memory_event(
            db,
            principal,
            session_id,
            memory_event_id,
            policy=DEFAULT_EXPERT_MEMORY_POLICY,
            explicit_opt_in=req.confirm,
        )
    except ExpertProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail='Expert profile not found') from exc
    except ExpertSessionNotFound as exc:
        raise HTTPException(status_code=404, detail='Expert session or memory event not found') from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail='Expert memory failed promotion policy') from exc
    payload = event.model_dump(mode='json')
    store_idempotency(db, principal, idempotency_key, fingerprint, payload)
    db.commit()
    return event


@app.delete(
    '/v1/experts/{expert_id}/sessions/{session_id}/memory/{memory_event_id}',
    response_model=ExpertMemoryDeletedResponse,
)
def delete_expert_memory(
    expert_id: str,
    session_id: str,
    memory_event_id: str,
    external_user_id: str | None = Query(default=None, max_length=255),
    conversation_id: str | None = Query(default=None, max_length=255),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
):
    ensure_scope(principal, 'retrieval:read')
    enforce_rate_limit(db, principal, 'experts.memory.delete')
    fingerprint = _expert_idempotency_fingerprint(
        'experts.memory.delete',
        principal,
        expert_id,
        {
            'session_id': session_id,
            'memory_event_id': memory_event_id,
            'external_user_id': external_user_id,
            'conversation_id': conversation_id,
        },
    )
    cached = check_idempotency(db, principal, idempotency_key, fingerprint)
    if cached is not None:
        return ExpertMemoryDeletedResponse.model_validate(cached)
    try:
        resolve_expert_profile(db, principal, expert_id)
        _require_scoped_expert_session(
            db,
            principal,
            expert_id=expert_id,
            session_id=session_id,
            external_user_id=external_user_id,
            conversation_id=conversation_id,
        )
        delete_expert_memory_event(db, principal, session_id, memory_event_id)
    except ExpertProfileNotFoundError as exc:
        raise HTTPException(status_code=404, detail='Expert profile not found') from exc
    except ExpertSessionNotFound as exc:
        raise HTTPException(status_code=404, detail='Expert session or memory event not found') from exc
    response = ExpertMemoryDeletedResponse(
        id=memory_event_id,
        expert_id=expert_id,
        session_id=session_id,
    )
    payload = response.model_dump(mode='json')
    store_idempotency(db, principal, idempotency_key, fingerprint, payload)
    db.commit()
    return response


@app.post('/api/v1/ingestion/preview', response_model=IngestionPlanResponse)
def ingestion_preview(req: IngestionPreviewRequest, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, ['documents:write', 'retrieval:read'], any_of=True)
    enforce_rate_limit(db, principal, 'ingestion.preview')
    plan = build_ingestion_plan(principal, req)
    if req.persist:
        plan = persist_ingestion_plan(db, principal, req, plan)
        db.commit()
    return plan


@app.post('/api/v1/documents/ingest', response_model=IngestionJobResponse)
async def ingest_document(req: DocumentIngestRequest, idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'), principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'documents:write')
    enforce_rate_limit(db, principal, 'documents.ingest')
    fp = stable_hash(req.model_dump())
    if cached := check_idempotency(db, principal, idempotency_key, fp):
        return cached
    result = await ingest_or_enqueue(req, principal, db)
    payload = result.model_dump()
    set_rls_context(db, principal)
    store_idempotency(db, principal, idempotency_key, fp, payload)
    db.commit()
    return payload


@app.post('/api/v1/documents/upload', response_model=IngestionJobResponse)
async def upload_document(file: UploadFile = File(...), title: str | None = Form(default=None), mode: str = Form(default='auto_detect_v1'), vector_store_id: str | None = Form(default=None), knowledge_base_id: str | None = Form(default=None), security_level: int = Form(default=1), classification: str = Form(default='tenant_private'), source_uri: str | None = Form(default=None), source_identity: str | None = Form(default=None), attributes_json: str | None = Form(default=None), idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'), principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'documents:write')
    enforce_rate_limit(db, principal, 'documents.upload')
    content_bytes = await file.read()
    if len(content_bytes) > settings.svs_request_body_limit_bytes:
        raise HTTPException(status_code=413, detail='Uploaded document exceeds configured body limit')
    attributes = _document_upload_attributes(attributes_json)
    fingerprint = stable_hash({
        'filename': file.filename,
        'content_type': file.content_type,
        'content_sha256': sha256(content_bytes).hexdigest(),
        'title': title,
        'mode': mode,
        'vector_store_id': vector_store_id,
        'knowledge_base_id': knowledge_base_id,
        'security_level': security_level,
        'classification': classification,
        'source_uri': source_uri,
        'source_identity': source_identity,
        'attributes': attributes,
    })
    if cached := check_idempotency(db, principal, idempotency_key, fingerprint):
        return cached
    if is_marker_pdf_upload(file.filename, file.content_type, mode):
        req = await marker_pdf_upload_request(
            file=file,
            content_bytes=content_bytes,
            title=title,
            mode=mode,
            vector_store_id=vector_store_id,
            knowledge_base_id=knowledge_base_id,
            security_level=security_level,
            principal=principal,
            source_uri=source_uri,
            source_identity=source_identity,
            attributes=attributes,
            classification=classification,
        )
    else:
        content = content_bytes.decode('utf-8', errors='replace')
        req = DocumentIngestRequest(vector_store_id=vector_store_id, knowledge_base_id=knowledge_base_id, title=title or file.filename or 'uploaded document', filename=file.filename, mime_type=file.content_type, content=content, mode=mode, source_uri=source_uri, source_identity=source_identity, attributes=attributes, security_level=security_level, classification=classification)
    result = await ingest_or_enqueue(req, principal, db)
    payload = result.model_dump()
    set_rls_context(db, principal)
    store_idempotency(db, principal, idempotency_key, fingerprint, payload)
    db.commit()
    return payload


@app.get('/api/v1/jobs', response_model=IngestionJobListResponse, response_model_exclude_unset=True)
def list_jobs(limit: int = 20, status: str | None = None, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, ['documents:write', 'admin:read'], any_of=True)
    enforce_rate_limit(db, principal, 'jobs.read')
    params = {'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'limit': min(max(limit, 1), 100)}
    extra = ''
    if status:
        extra = 'AND status=:status'
        params['status'] = status
    rows = db.execute(text(f'''
        SELECT id, job_type, status, attempts, max_attempts, last_error, payload,
               extract(epoch from created_at)::bigint created_at, extract(epoch from updated_at)::bigint updated_at,
               extract(epoch from completed_at)::bigint completed_at
        FROM ingestion_jobs
        WHERE tenant_id=:tenant_id AND business_instance_id=:biz_id {extra}
        ORDER BY created_at DESC LIMIT :limit
    '''), params).mappings().all()
    data = [dict(r) for r in rows]
    return _list_response(data, has_more=len(data) == params['limit'])


@app.get('/api/v1/jobs/{job_id}', response_model=IngestionJobDetail, response_model_exclude_unset=True)
def get_job(job_id: str, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, ['documents:write', 'admin:read'], any_of=True)
    row = db.execute(text('''
        SELECT id, job_type, status, attempts, max_attempts, last_error, payload,
               extract(epoch from created_at)::bigint created_at, extract(epoch from updated_at)::bigint updated_at,
               extract(epoch from completed_at)::bigint completed_at
        FROM ingestion_jobs WHERE id=:id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
    '''), {'id': job_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail='Job not found')
    return dict(row)


@app.post('/api/v1/jobs/{job_id}/retry', response_model=IngestionJobResponse, response_model_exclude_unset=True)
def retry_job(job_id: str, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'documents:write')
    result = db.execute(text('''
        UPDATE ingestion_jobs SET status='queued', locked_by=NULL, locked_at=NULL, last_error=NULL, updated_at=now()
        WHERE id=:id AND tenant_id=:tenant_id AND business_instance_id=:biz_id AND status IN ('failed','cancelled')
    '''), {'id': job_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id})
    db.commit()
    if not result.rowcount:
        raise HTTPException(status_code=404, detail='Retryable failed/cancelled job not found')
    return {'id': job_id, 'status': 'queued'}


@app.post('/api/v1/retrieval/search', response_model=SearchResponse)
async def search(req: SearchRequest, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'retrieval:read')
    enforce_rate_limit(db, principal, 'retrieval.search')
    if req.vector_store_id:
        _refresh_vector_store_activity_or_404(db, principal, req.vector_store_id)
    result = await retrieval.search(db, principal, req)
    db.commit()
    return result


@app.post('/api/v1/retrieval/context-pack', response_model=ContextPackResponse)
async def context_pack(req: ContextPackRequest, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'retrieval:read')
    enforce_rate_limit(db, principal, 'retrieval.context_pack')
    if req.vector_store_id:
        _refresh_vector_store_activity_or_404(db, principal, req.vector_store_id)
    result = await retrieval.context_pack(db, principal, req)
    db.commit()
    return result


@app.post('/api/v1/retrieval/answer', response_model=RetrievalAnswerResponse)
async def retrieval_answer(req: RetrievalAnswerRequest, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'retrieval:read')
    enforce_rate_limit(db, principal, 'retrieval.answer')
    if req.vector_store_id:
        _refresh_vector_store_activity_or_404(db, principal, req.vector_store_id)
    result = await retrieval.answer(db, principal, req)
    db.commit()
    return result


@app.post('/api/v1/model-endpoints', response_model=ModelEndpointResponse)
def create_model_endpoint(req: ModelEndpointRequest, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'models:write')
    endpoint_id = new_id('mdl')
    payload = normalize_endpoint_payload(req.model_dump())
    db.execute(jsonb_text('''
        INSERT INTO model_endpoints(id, tenant_id, business_instance_id, name, provider, kind, base_url, model, dimensions,
          privacy, security_max_level, status, config)
        VALUES (:id, :tenant_id, :biz_id, :name, :provider, :kind, :base_url, :model, :dimensions, :privacy, :security_max_level, :status, CAST(:config AS jsonb))
    ''', 'config'), {**payload, 'id': endpoint_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'config': jsonb_param(payload['config'])})
    db.commit()
    return ModelEndpointResponse(**endpoint_response_payload({**payload, 'id': endpoint_id}))


@app.get('/api/v1/model-endpoints', response_model=ModelEndpointListResponse, response_model_exclude_unset=True)
def list_model_endpoints(principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, ['models:read', 'models:write'], any_of=True)
    rows = db.execute(text('''
        SELECT id, name, provider, kind, base_url, model, dimensions, privacy, security_max_level, status, config,
               extract(epoch from created_at)::bigint created_at, extract(epoch from updated_at)::bigint updated_at
        FROM model_endpoints WHERE tenant_id=:tenant_id AND business_instance_id=:biz_id ORDER BY created_at DESC
    '''), {'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id}).mappings().all()
    return _list_response([endpoint_response_payload(dict(r)) for r in rows])


@app.patch('/api/v1/model-endpoints/{endpoint_id}', response_model=ModelEndpointResponse)
def update_model_endpoint(endpoint_id: str, patch: dict[str, Any] = Body(default_factory=dict), principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'models:write')
    patch = dict(patch or {})
    metadata_patch = {k: patch.pop(k) for k in list(patch) if k in ENDPOINT_METADATA_FIELDS}
    if metadata_patch or 'config' in patch:
        existing = db.execute(
            text('SELECT id, name, provider, kind, base_url, model, dimensions, privacy, security_max_level, status, config FROM model_endpoints WHERE id=:id AND tenant_id=:tenant_id AND business_instance_id=:biz_id'),
            {'id': endpoint_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id},
        ).mappings().first()
        if not existing:
            raise HTTPException(status_code=404, detail='Model endpoint not found')
        merged_config = dict((patch.get('config') if 'config' in patch else existing['config']) or {})
        for key, value in metadata_patch.items():
            if value is not None:
                merged_config[key] = value
        normalized = normalize_endpoint_payload({'status': patch.get('status', existing['status']), 'config': merged_config})
        patch['config'] = normalized['config']
        if 'status' not in patch and normalized.get('status') and normalized['status'] != existing['status']:
            patch['status'] = normalized['status']
        try:
            ModelEndpointRequest.model_validate(endpoint_response_payload({**dict(existing), **patch}))
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors(include_context=False)) from exc
    allowed = {'name', 'provider', 'kind', 'base_url', 'model', 'dimensions', 'privacy', 'security_max_level', 'status', 'config'}
    fields, params = [], {'id': endpoint_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id}
    for k, v in patch.items():
        if k in allowed:
            fields.append('config=CAST(:config AS jsonb)' if k == 'config' else f'{k}=:{k}')
            params[k] = jsonb_param(v) if k == 'config' else v
    if fields:
        stmt = f"UPDATE model_endpoints SET {', '.join(fields)}, updated_at=now() WHERE id=:id AND tenant_id=:tenant_id AND business_instance_id=:biz_id"
        db.execute(jsonb_text(stmt, 'config') if 'config' in params else text(stmt), params)
    row = db.execute(text('SELECT * FROM model_endpoints WHERE id=:id AND tenant_id=:tenant_id AND business_instance_id=:biz_id'), params).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail='Model endpoint not found')
    db.commit()
    return ModelEndpointResponse(**endpoint_response_payload(dict(row)))


@app.post('/api/v1/bakeoffs', response_model=BakeoffRunResponse)
def create_bakeoff(req: BakeoffRunRequest, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, ['evals:write', 'models:write'], any_of=True)
    result = bakeoff.create_run(db, principal, req)
    db.commit()
    return result


@app.get('/api/v1/bakeoffs', response_model=BakeoffRunListResponse, response_model_exclude_unset=True)
def list_bakeoffs(limit: int = 20, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, ['evals:read', 'evals:write', 'models:write'], any_of=True)
    data, has_more = bakeoff.list_runs(db, principal, limit=limit)
    return _list_response(data, has_more)


@app.get('/api/v1/bakeoffs/{run_id}', response_model=BakeoffRunResponse)
def get_bakeoff(run_id: str, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, ['evals:read', 'evals:write', 'models:write'], any_of=True)
    result = bakeoff.get_run(db, principal, run_id)
    if not result:
        raise HTTPException(status_code=404, detail='Bakeoff run not found')
    return result


@app.post('/api/v1/maintenance/expire-vector-stores', response_model=MaintenanceResult)
def expire_vector_stores(principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'maintenance:write')
    result = maintenance.sweep_expired_vector_stores(db, principal)
    db.commit()
    return result


@app.post('/api/v1/maintenance/reindex', response_model=MaintenanceResult)
async def reindex(req: ReindexRequest, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'maintenance:write')
    result = await maintenance.reindex_chunks(db, principal, req)
    db.commit()
    return result


@app.get('/api/v1/admin/session', response_model=AdminSessionResponse)
def admin_session(principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, ADMIN_UI_SESSION_SCOPES, any_of=True)
    return {
        'object': 'admin.session',
        'authenticated': True,
        'tenant_id': principal.tenant_id,
        'business_instance_id': principal.business_instance_id,
        'user_id': principal.user_id,
        'api_key_id': principal.api_key_id,
        'scopes': list(principal.scopes or []),
        'roles': list(principal.roles or []),
        'groups': list(principal.groups or []),
        'max_security_level': principal.max_security_level,
    }


@app.get('/api/v1/admin/fleet/versions', response_model=FleetVersionReport)
def admin_fleet_versions(
    business_instance_id: str | None = Query(default=None),
    deployment_limit: int = Query(default=25, ge=1, le=200),
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
):
    ensure_scope(principal, ['admin:read', 'fleet:read'], any_of=True)
    business_rows = db.execute(text('''
        SELECT id, name, slug, deployment_mode, isolation_level, config, status,
               extract(epoch from created_at)::bigint created_at
        FROM business_instances
        WHERE tenant_id=:tenant_id
        ORDER BY name ASC, id ASC
    '''), {'tenant_id': principal.tenant_id}).mappings().all()
    visible_business_ids = {row['id'] for row in business_rows}
    selected_business_id = business_instance_id or principal.business_instance_id
    if business_instance_id and business_instance_id not in visible_business_ids:
        raise HTTPException(status_code=404, detail='Business instance not visible')
    deployment_rows = db.execute(text('''
        SELECT id, instance_id, business_instance_id, from_version, to_version, image_digests,
               status, extract(epoch from started_at)::bigint started_at,
               extract(epoch from completed_at)::bigint completed_at, manifest,
               extract(epoch from created_at)::bigint created_at
        FROM instance_deployments
        WHERE tenant_id=:tenant_id
          AND (CAST(:selected_business_id AS text) IS NULL
               OR business_instance_id=:selected_business_id
               OR business_instance_id IS NULL)
        ORDER BY coalesce(completed_at, started_at, created_at) DESC, id DESC
        LIMIT :limit
    '''), {
        'tenant_id': principal.tenant_id,
        'selected_business_id': selected_business_id or None,
        'limit': deployment_limit,
    }).mappings().all()
    return build_fleet_version_report(
        tenant_id=principal.tenant_id,
        product_version=settings.svs_product_version,
        business_rows=business_rows,
        deployment_rows=deployment_rows,
        selected_business_instance_id=selected_business_id,
    )


def _caller_user_bound(principal: Principal) -> bool:
    """True for a key bound to a caller-provisioned user (one with an external_id).

    Cell/bootstrap admin keys may also carry a user_id, but only WAVE-125
    caller-provisioned users have an external_id, so that is the discriminator.
    Migration 004 makes it structural: CHECK (business_instance_id IS NULL OR
    external_id IS NOT NULL) on users.
    """
    return bool(principal.external_id)


def _force_user_bound_usage_scope(principal: Principal, user_id: str | None) -> str | None:
    """QC: a user-bound key may only read its own usage, never another user's."""
    if not _caller_user_bound(principal):
        return user_id
    if user_id is not None and user_id != principal.user_id:
        raise HTTPException(
            status_code=403,
            detail={'error': 'user_bound_usage_scope', 'message': 'a user-bound key can only read its own usage'},
        )
    return principal.user_id


@app.get('/api/v1/admin/usage', response_model=UsageEventListResponse, response_model_exclude_unset=True)
def usage(
    limit: int = 100,
    user_id: str | None = None,
    api_key_id: str | None = None,
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
):
    ensure_scope(principal, ['admin:read', 'usage:read'], any_of=True)
    user_id = _force_user_bound_usage_scope(principal, user_id)
    params: dict[str, Any] = {'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'limit': min(max(limit, 1), 500)}
    filters = ''
    if user_id is not None:
        filters += ' AND user_id=:user_id'
        params['user_id'] = user_id
    if api_key_id is not None:
        filters += ' AND api_key_id=:api_key_id'
        params['api_key_id'] = api_key_id
    rows = db.execute(text('''
        SELECT id, event_type, quantity, unit, provider, model, cost_estimate_usd, user_id, api_key_id, metadata,
               extract(epoch from created_at)::bigint created_at
        FROM usage_events WHERE tenant_id=:tenant_id AND business_instance_id=:biz_id
        ''' + filters + '''
        ORDER BY created_at DESC LIMIT :limit
    '''), params).mappings().all()
    return _list_response([dict(r) for r in rows])


def _usage_window_bounds(from_ts: int | None, to_ts: int | None) -> tuple[int | None, int | None]:
    if from_ts is not None and to_ts is not None and to_ts <= from_ts:
        raise HTTPException(status_code=422, detail='to must be greater than from')
    return from_ts, to_ts


@app.get('/api/v1/admin/usage/summary', response_model=UsageSummaryResponse, response_model_by_alias=True)
def usage_summary(
    group_by: UsageSummaryGroupBy = Query(default='user'),
    from_ts: int | None = Query(default=None, alias='from', ge=0),
    to_ts: int | None = Query(default=None, alias='to', ge=0),
    limit: int = Query(default=200, ge=1, le=1000),
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
):
    """WAVE-125: quantity and estimated cost per user or per API key for a window."""
    ensure_scope(principal, ['admin:read', 'usage:read'], any_of=True)
    enforce_rate_limit(db, principal, 'admin.usage.summary')
    from_ts, to_ts = _usage_window_bounds(from_ts, to_ts)
    forced_user_id = _force_user_bound_usage_scope(principal, None)
    forced_clause = ' AND ue.user_id=:forced_user_id' if forced_user_id is not None else ''
    group_column = 'ue.user_id' if group_by == 'user' else 'ue.api_key_id'
    external_id_select = 'max(u.external_id) AS external_id,' if group_by == 'user' else 'NULL::text AS external_id,'
    external_id_join = 'LEFT JOIN users u ON u.id=ue.user_id AND u.tenant_id=ue.tenant_id' if group_by == 'user' else ''
    rows = db.execute(text(f'''
        SELECT {group_column} AS group_id,
               {external_id_select}
               count(*)::bigint AS event_count,
               coalesce(sum(ue.quantity), 0) AS quantity,
               sum(ue.cost_estimate_usd) AS cost_estimate_usd
        FROM usage_events ue
        {external_id_join}
        WHERE ue.tenant_id=:tenant_id AND ue.business_instance_id=:biz_id{forced_clause}
          AND (CAST(:from_ts AS bigint) IS NULL OR ue.created_at >= to_timestamp(CAST(:from_ts AS double precision)))
          AND (CAST(:to_ts AS bigint) IS NULL OR ue.created_at < to_timestamp(CAST(:to_ts AS double precision)))
        GROUP BY {group_column}
        ORDER BY quantity DESC, group_id ASC NULLS LAST
        LIMIT :limit
    '''), {
        'tenant_id': principal.tenant_id,
        'biz_id': principal.business_instance_id,
        'from_ts': from_ts,
        'to_ts': to_ts,
        'limit': limit,
        'forced_user_id': forced_user_id,
    }).mappings().all()
    data = [
        UsageSummaryRow(
            group_by=group_by,
            group_id=row['group_id'],
            external_id=row.get('external_id'),
            event_count=int(row['event_count'] or 0),
            quantity=float(row['quantity'] or 0),
            cost_estimate_usd=float(row['cost_estimate_usd']) if row.get('cost_estimate_usd') is not None else None,
        )
        for row in rows
    ]
    return UsageSummaryResponse(group_by=group_by, from_ts=from_ts, to_ts=to_ts, data=data)


@app.get('/api/v1/admin/audit-events', response_model=AuditEventListResponse, response_model_exclude_unset=True)
def audit_events(limit: int = 100, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, ['admin:read', 'audit:read'], any_of=True)
    rows = db.execute(text('''
        SELECT id, event_type, action, resource_type, resource_id, security_level, allowed, metadata, extract(epoch from created_at)::bigint created_at
        FROM audit_events WHERE tenant_id=:tenant_id AND business_instance_id=:biz_id
        ORDER BY created_at DESC LIMIT :limit
    '''), {'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'limit': min(max(limit, 1), 500)}).mappings().all()
    return _list_response([dict(r) for r in rows])


@app.post('/api/v1/admin/tenants', response_model=TenantResponse)
def create_tenant(name: str, slug: str, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'admin:write')
    tenant_id = new_id('ten')
    db.execute(text("SELECT set_config('svs.tenant_id', :tenant_id, true)"), {'tenant_id': tenant_id})
    db.execute(text('INSERT INTO tenants(id, name, slug) VALUES (:id, :name, :slug)'), {'id': tenant_id, 'name': name, 'slug': slug})
    db.commit()
    return {'id': tenant_id, 'name': name, 'slug': slug}


USERS_WRITE_SCOPES = ['users:write', 'api_keys:write']
USERS_READ_SCOPES = ['users:read', 'users:write', 'api_keys:read', 'api_keys:write']
DEFAULT_INSTANCE_API_KEY_SCOPES = 'retrieval:read,documents:write,vector_stores:write,vector_stores:read'
DEFAULT_USER_BOUND_API_KEY_SCOPES = 'retrieval:read'


@app.post('/api/v1/admin/users', response_model=AdminUserResponse)
def create_admin_user(
    req: AdminUserCreateRequest,
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
):
    """WAVE-125: provision (idempotently, by external_id) a caller-side user."""
    ensure_scope(principal, USERS_WRITE_SCOPES, any_of=True)
    enforce_rate_limit(db, principal, 'admin.users.create')
    user, _created = create_or_get_user(
        db,
        principal,
        external_id=req.external_id,
        email=req.email,
        display_name=req.display_name,
    )
    db.commit()
    return user


@app.get('/api/v1/admin/users', response_model=AdminUserListResponse)
def list_admin_users(
    limit: int = 20,
    after: str | None = None,
    external_id: str | None = None,
    status: str | None = None,
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
):
    ensure_scope(principal, USERS_READ_SCOPES, any_of=True)
    enforce_rate_limit(db, principal, 'admin.users.list')
    if status is not None and status not in ('active', 'deactivated'):
        raise HTTPException(status_code=422, detail='status must be active or deactivated')
    data, has_more = list_users(db, principal, limit=limit, after=after, external_id=external_id, status_filter=status)
    return _list_response(data, has_more)


@app.post('/api/v1/admin/users/{user_id}/deactivate', response_model=AdminUserDeactivateResponse)
def deactivate_admin_user(
    user_id: str,
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
):
    """Deactivate a user, revoke its active keys, block new sessions; keep history."""
    ensure_scope(principal, USERS_WRITE_SCOPES, any_of=True)
    enforce_rate_limit(db, principal, 'admin.users.deactivate')
    result = deactivate_user(db, principal, user_id)
    if result is None:
        raise HTTPException(status_code=404, detail='User not found')
    user, revoked_ids = result
    db.commit()
    return {'id': user_id, 'object': 'user.deactivated', 'deactivated': True, 'revoked_api_key_ids': revoked_ids, 'data': user}


def _require_bindable_user(db: Session, principal: Principal, user_id: str) -> dict[str, Any]:
    """WAVE-125: the target user must exist in the caller instance and be active."""
    user = get_user(db, principal, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail='User not found')
    if user['status'] != 'active':
        raise HTTPException(status_code=409, detail='User is deactivated')
    return user


@app.post('/api/v1/admin/api-keys', response_model=InstanceApiKeyResponse, response_model_exclude_unset=True)
def create_instance_api_key(
    label: str = 'default',
    scopes: str | None = None,
    max_security_level: int | None = None,
    expires_at: int | None = None,
    user_id: str | None = None,
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
):
    ensure_scope(principal, 'api_keys:write')
    enforce_rate_limit(db, principal, 'admin.api_keys.create')
    if scopes is None:
        scopes = DEFAULT_USER_BOUND_API_KEY_SCOPES if user_id else DEFAULT_INSTANCE_API_KEY_SCOPES
    # QC: delegation rules apply to every key creation, bound or not. A principal
    # can never mint scopes or a level it does not hold; user-bound keys are
    # further restricted to the USER_BOUND_ALLOWED_SCOPES allow-list.
    scope_list = validate_delegated_scopes(
        principal,
        [s.strip() for s in scopes.split(',') if s.strip()],
        user_bound=bool(user_id),
    )
    effective_level = validate_delegated_security_level(principal, max_security_level)
    if user_id:
        _require_bindable_user(db, principal, user_id)
        result = create_api_key(db, principal, label, scope_list, effective_level, expires_at, user_id=user_id)
    else:
        result = create_api_key(db, principal, label, scope_list, effective_level, expires_at)
    db.commit()
    return result


@app.get('/api/v1/admin/api-keys', response_model=InstanceApiKeyListResponse, response_model_exclude_unset=True)
def list_instance_api_keys(
    limit: int = 20,
    after: str | None = None,
    user_id: str | None = None,
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
):
    ensure_scope(principal, ['api_keys:read', 'api_keys:write'], any_of=True)
    enforce_rate_limit(db, principal, 'admin.api_keys.list')
    filters = {'user_id': user_id} if user_id else {}
    data, has_more = list_api_keys(db, principal, limit, after=after, **filters)
    return _list_response(data, has_more)


@app.delete('/api/v1/admin/api-keys/{api_key_id}', response_model=InstanceApiKeyDeletedResponse, response_model_exclude_unset=True)
def revoke_instance_api_key(api_key_id: str, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'api_keys:write')
    enforce_rate_limit(db, principal, 'admin.api_keys.revoke')
    payload = revoke_api_key(db, principal, api_key_id)
    if not payload:
        raise HTTPException(status_code=404, detail='API key not found')
    db.commit()
    return {'id': api_key_id, 'object': 'api_key.deleted', 'deleted': True, 'data': payload}


@app.post('/v1/organization/admin_api_keys', response_model=OpenAIAdminApiKeyCreateResponse, response_model_exclude_unset=True)
def create_admin_api_key(
    payload: OpenAIAdminApiKeyCreateRequest,
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
):
    ensure_scope(principal, 'api_keys:write')
    enforce_rate_limit(db, principal, 'admin.api_keys.create')
    created_at = int(time.time())
    expires_at = created_at + payload.expires_in_seconds if payload.expires_in_seconds is not None else None
    result = create_api_key(
        db,
        principal,
        payload.name,
        list(principal.scopes or []),
        principal.max_security_level,
        expires_at,
    )
    db.commit()
    return openai_admin_api_key_create_response(result, created_at=created_at, owner_user_id=principal.user_id)


@app.get('/v1/organization/admin_api_keys', response_model=OpenAIAdminApiKeyListResponse, response_model_exclude_unset=True)
def list_admin_api_keys(
    limit: int = 20,
    after: str | None = None,
    order: Annotated[str, Query(pattern='^(asc|desc)$')] = 'asc',
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
):
    ensure_scope(principal, ['api_keys:read', 'api_keys:write'], any_of=True)
    enforce_rate_limit(db, principal, 'admin.api_keys.list')
    data, has_more = list_api_keys(db, principal, limit, after=after, status='active', order=order)
    return _list_response([
        openai_admin_api_key_from_metadata(item, owner_user_id=principal.user_id)
        for item in data
    ], has_more)


@app.get('/v1/organization/admin_api_keys/{key_id}', response_model=OpenAIAdminApiKey, response_model_exclude_unset=True)
def retrieve_admin_api_key(key_id: str, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, ['api_keys:read', 'api_keys:write'], any_of=True)
    enforce_rate_limit(db, principal, 'admin.api_keys.retrieve')
    payload = get_api_key(db, principal, key_id, status='active')
    if not payload:
        raise HTTPException(status_code=404, detail='API key not found')
    return openai_admin_api_key_from_metadata(payload, owner_user_id=principal.user_id)


@app.delete('/v1/organization/admin_api_keys/{key_id}', response_model=OpenAIAdminApiKeyDeletedResponse, response_model_exclude_unset=True)
def delete_admin_api_key(key_id: str, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'api_keys:write')
    enforce_rate_limit(db, principal, 'admin.api_keys.revoke')
    payload = revoke_api_key(db, principal, key_id)
    if not payload:
        raise HTTPException(status_code=404, detail='API key not found')
    db.commit()
    return {'id': key_id, 'object': 'organization.admin_api_key.deleted', 'deleted': True}


def _ensure_openai_project_scope(project_id: str, principal: Principal) -> None:
    if project_id != principal.business_instance_id:
        raise HTTPException(status_code=404, detail='Project not found')


@app.get('/v1/organization/projects/{project_id}/api_keys', response_model=OpenAIProjectApiKeyListResponse, response_model_exclude_unset=True)
def list_project_api_keys(project_id: str, limit: int = 20, after: str | None = None, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, ['api_keys:read', 'api_keys:write'], any_of=True)
    _ensure_openai_project_scope(project_id, principal)
    enforce_rate_limit(db, principal, 'admin.api_keys.list')
    data, has_more = list_api_keys(db, principal, limit, after=after, status='active')
    return _list_response([
        openai_project_api_key_from_metadata(item, owner_user_id=principal.user_id)
        for item in data
    ], has_more)


@app.get('/v1/organization/projects/{project_id}/api_keys/{api_key_id}', response_model=OpenAIProjectApiKey, response_model_exclude_unset=True)
def retrieve_project_api_key(project_id: str, api_key_id: str, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, ['api_keys:read', 'api_keys:write'], any_of=True)
    _ensure_openai_project_scope(project_id, principal)
    enforce_rate_limit(db, principal, 'admin.api_keys.retrieve')
    payload = get_api_key(db, principal, api_key_id, status='active')
    if not payload:
        raise HTTPException(status_code=404, detail='API key not found')
    return openai_project_api_key_from_metadata(payload, owner_user_id=principal.user_id)


@app.delete('/v1/organization/projects/{project_id}/api_keys/{api_key_id}', response_model=OpenAIProjectApiKeyDeletedResponse, response_model_exclude_unset=True)
def delete_project_api_key(project_id: str, api_key_id: str, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'api_keys:write')
    _ensure_openai_project_scope(project_id, principal)
    enforce_rate_limit(db, principal, 'admin.api_keys.revoke')
    payload = revoke_api_key(db, principal, api_key_id)
    if not payload:
        raise HTTPException(status_code=404, detail='API key not found')
    db.commit()
    return {'id': api_key_id, 'object': 'organization.project.api_key.deleted', 'deleted': True}


@app.post('/v1/vector_stores', response_model=VectorStoreResponse)
async def create_vector_store(req: VectorStoreCreateRequest | None = Body(default=None), idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'), principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    req = req or VectorStoreCreateRequest()
    ensure_scope(principal, 'vector_stores:write')
    if req.file_ids:
        ensure_scope(principal, 'documents:write')
    enforce_rate_limit(db, principal, 'vector_stores.create')
    fp = stable_hash(req.model_dump())
    if cached := check_idempotency(db, principal, idempotency_key, fp):
        return cached
    result = vs_repo.create(db, principal, req)
    if req.file_ids:
        attach_attributes = (
            _vector_store_file_attach_attributes({'chunking_strategy': req.chunking_strategy})
            if req.chunking_strategy is not None
            else None
        )
        await _attach_existing_document_ids_to_vector_store(
            db,
            principal,
            result.id,
            req.file_ids,
            attributes=attach_attributes,
        )
        result = vs_repo.get(db, principal, result.id) or result
    payload = result.model_dump()
    store_idempotency(db, principal, idempotency_key, fp, payload)
    db.commit()
    return result


@app.get('/v1/vector_stores', response_model=VectorStoreListResponse)
def list_vector_stores(limit: int = 20, after: str | None = None, before: str | None = None, order: str = Query(default='desc', pattern='^(asc|desc)$'), principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'vector_stores:read')
    enforce_rate_limit(db, principal, 'vector_stores.list')
    data, has_more = vs_repo.list(db, principal, limit, after=after, before=before, order=order)
    return _list_response(data, has_more)


@app.get('/v1/vector_stores/{vector_store_id}', response_model=VectorStoreResponse)
def get_vector_store(vector_store_id: str, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'vector_stores:read')
    enforce_rate_limit(db, principal, 'vector_stores.retrieve')
    result = vs_repo.get(db, principal, vector_store_id)
    if not result:
        raise HTTPException(status_code=404, detail='Vector store not found')
    return result


@app.get('/v1/vector_stores/{vector_store_id}/search_lenses', response_model=VectorStoreSearchLensesResponse)
def vector_store_search_lenses(vector_store_id: str, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, ['retrieval:read', 'vector_stores:read'], any_of=True)
    enforce_rate_limit(db, principal, 'vector_stores.search_lenses')
    _refresh_vector_store_activity_or_404(db, principal, vector_store_id)
    return _vector_store_search_lenses_payload(db, principal, vector_store_id)


def _graph_payload_attributes(value: Any) -> dict[str, Any]:
    attributes = getattr(value, "attributes", None)
    properties = getattr(value, "properties", None)
    if isinstance(attributes, dict):
        return dict(attributes)
    if isinstance(properties, dict):
        return dict(properties)
    return {}


def _graph_node_key(node: Any, attributes: dict[str, Any]) -> str:
    explicit = getattr(node, "key", None)
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    for key in ("node_key", "section_id", "citation", "ordinance_number", "ordinance", "source_url", "citation_url", "url"):
        value = attributes.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if value is not None and not isinstance(value, (dict, list)):
            return str(value)
    return str(node.id).strip()


def _graph_node_provenance(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [dict(value)]
    return []


def _graph_edge_provenance(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, list):
        return {"items": [dict(item) for item in value if isinstance(item, dict)]}
    return {}


def _normalized_graph_load_rows(
    req: VectorStoreGraphLoadRequest,
    principal: Principal,
    vector_store_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    node_rows: list[dict[str, Any]] = []
    node_ids: set[str] = set()
    for node in req.nodes:
        node_id = str(node.id).strip()
        node_type = str(node.type).strip()
        if not node_id:
            raise ValueError("graph node id must be non-empty")
        if not node_type:
            raise ValueError(f"graph node {node_id!r} type must be non-empty")
        attributes = _graph_payload_attributes(node)
        node_ids.add(node_id)
        node_rows.append({
            "id": node_id,
            "tenant_id": principal.tenant_id,
            "business_instance_id": principal.business_instance_id,
            "vector_store_id": vector_store_id,
            "node_type": node_type,
            "node_key": _graph_node_key(node, attributes),
            "label": str(node.label or node_id).strip() or node_id,
            "attributes": jsonb_param(attributes),
            "provenance": jsonb_param(_graph_node_provenance(node.provenance)),
        })

    edge_rows: list[dict[str, Any]] = []
    dangling_edge_ids: list[str] = []
    for edge in req.edges:
        edge_id = str(edge.id).strip()
        edge_type = str(edge.type).strip()
        source_node_id = str(edge.source).strip()
        target_node_id = str(edge.target).strip()
        if not edge_id:
            raise ValueError("graph edge id must be non-empty")
        if not edge_type:
            raise ValueError(f"graph edge {edge_id!r} type must be non-empty")
        if source_node_id not in node_ids or target_node_id not in node_ids:
            dangling_edge_ids.append(edge_id)
            continue
        edge_rows.append({
            "id": edge_id,
            "tenant_id": principal.tenant_id,
            "business_instance_id": principal.business_instance_id,
            "vector_store_id": vector_store_id,
            "edge_type": edge_type,
            "source_node_id": source_node_id,
            "target_node_id": target_node_id,
            "attributes": jsonb_param(_graph_payload_attributes(edge)),
            "provenance": jsonb_param(_graph_edge_provenance(edge.provenance)),
        })
    return node_rows, edge_rows, dangling_edge_ids


def _load_vector_store_graph(
    db: Session,
    principal: Principal,
    vector_store_id: str,
    req: VectorStoreGraphLoadRequest,
) -> dict[str, Any]:
    node_rows, edge_rows, dangling_edge_ids = _normalized_graph_load_rows(req, principal, vector_store_id)
    if dangling_edge_ids:
        raise ValueError(
            "graph load contains dangling edges: "
            + ", ".join(dangling_edge_ids[:20])
            + (f" and {len(dangling_edge_ids) - 20} more" if len(dangling_edge_ids) > 20 else "")
        )
    if req.dry_run:
        return {
            "object": "vector_store.graph_load",
            "vector_store_id": vector_store_id,
            "status": "dry_run",
            "dry_run": True,
            "replaced": bool(req.replace),
            "nodes": len(node_rows),
            "edges": len(edge_rows),
            "loaded_nodes": 0,
            "loaded_edges": 0,
            "skipped_edges": 0,
        }

    scope_params = {
        "tenant_id": principal.tenant_id,
        "biz_id": principal.business_instance_id,
        "vector_store_id": vector_store_id,
    }
    if req.replace:
        db.execute(text("""
            DELETE FROM graph_edges
            WHERE tenant_id=:tenant_id
              AND business_instance_id=:biz_id
              AND vector_store_id=:vector_store_id
        """), scope_params)
        db.execute(text("""
            DELETE FROM graph_nodes
            WHERE tenant_id=:tenant_id
              AND business_instance_id=:biz_id
              AND vector_store_id=:vector_store_id
        """), scope_params)

    if node_rows:
        db.execute(jsonb_text("""
            INSERT INTO graph_nodes (
              id, tenant_id, business_instance_id, vector_store_id,
              node_type, node_key, label, attributes, provenance
            )
            VALUES (
              :id, :tenant_id, :business_instance_id, :vector_store_id,
              :node_type, :node_key, :label, CAST(:attributes AS jsonb), CAST(:provenance AS jsonb)
            )
            ON CONFLICT (tenant_id, business_instance_id, vector_store_id, id) DO UPDATE
            SET node_type=excluded.node_type,
                node_key=excluded.node_key,
                label=excluded.label,
                attributes=excluded.attributes,
                provenance=excluded.provenance,
                updated_at=now()
        """, "attributes", "provenance"), node_rows)
    if edge_rows:
        db.execute(jsonb_text("""
            INSERT INTO graph_edges (
              id, tenant_id, business_instance_id, vector_store_id,
              edge_type, source_node_id, target_node_id, attributes, provenance
            )
            VALUES (
              :id, :tenant_id, :business_instance_id, :vector_store_id,
              :edge_type, :source_node_id, :target_node_id, CAST(:attributes AS jsonb), CAST(:provenance AS jsonb)
            )
            ON CONFLICT (tenant_id, business_instance_id, vector_store_id, id) DO UPDATE
            SET edge_type=excluded.edge_type,
                source_node_id=excluded.source_node_id,
                target_node_id=excluded.target_node_id,
                attributes=excluded.attributes,
                provenance=excluded.provenance,
                updated_at=now()
        """, "attributes", "provenance"), edge_rows)

    counts = db.execute(text("""
        SELECT
          (SELECT count(*)::int FROM graph_nodes
           WHERE tenant_id=:tenant_id AND business_instance_id=:biz_id AND vector_store_id=:vector_store_id) AS nodes,
          (SELECT count(*)::int FROM graph_edges
           WHERE tenant_id=:tenant_id AND business_instance_id=:biz_id AND vector_store_id=:vector_store_id) AS edges
    """), scope_params).mappings().first() or {}
    return {
        "object": "vector_store.graph_load",
        "vector_store_id": vector_store_id,
        "status": "loaded",
        "dry_run": False,
        "replaced": bool(req.replace),
        "nodes": int(counts.get("nodes") or 0),
        "edges": int(counts.get("edges") or 0),
        "loaded_nodes": len(node_rows),
        "loaded_edges": len(edge_rows),
        "skipped_edges": 0,
    }


@app.post('/v1/vector_stores/{vector_store_id}/graph', response_model=VectorStoreGraphLoadResponse)
def load_vector_store_graph(
    vector_store_id: str,
    req: VectorStoreGraphLoadRequest,
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
):
    ensure_scope(principal, 'vector_stores:write')
    enforce_rate_limit(db, principal, 'vector_stores.graph.load')
    _refresh_vector_store_activity_or_404(db, principal, vector_store_id)
    attrs = _vector_store_attributes_for_search(db, principal, vector_store_id)
    cell_profile = _cell_graph_profile_or_503(attrs, principal, vector_store_id)
    try:
        if corpus_kind_for_vector_store(attrs, None) == GRANT_CORPUS_KIND:
            if cell_profile is None:
                raise ValueError('Grant graph load requires an explicitly bound cell profile')
            validate_grant_graph(req, vector_store_id)
        result = _load_vector_store_graph(db, principal, vector_store_id, req)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not req.dry_run:
        db.commit()
    return result


@app.post('/v1/vector_stores/{vector_store_id}', response_model=VectorStoreResponse)
@app.patch('/v1/vector_stores/{vector_store_id}', response_model=VectorStoreResponse)
def update_vector_store(
    vector_store_id: str,
    patch: VectorStoreUpdateRequest | None = Body(default=None),
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
):
    ensure_scope(principal, 'vector_stores:write')
    enforce_rate_limit(db, principal, 'vector_stores.update')
    patch = patch or VectorStoreUpdateRequest()
    idempotency_fingerprint, cached = _check_openai_idempotency(
        db,
        principal,
        idempotency_key,
        route='POST/PATCH /v1/vector_stores/{vector_store_id}',
        request_payload={'vector_store_id': vector_store_id, 'patch': patch.model_dump()},
    )
    if cached:
        return cached
    result = vs_repo.update(db, principal, vector_store_id, patch)
    if not result:
        raise HTTPException(status_code=404, detail='Vector store not found')
    _store_openai_idempotency(db, principal, idempotency_key, fingerprint=idempotency_fingerprint, response=result.model_dump())
    db.commit()
    return result


@app.delete('/v1/vector_stores/{vector_store_id}', response_model=VectorStoreDeletedResponse)
def delete_vector_store(
    vector_store_id: str,
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
):
    ensure_scope(principal, ['vector_stores:delete', 'vector_stores:write'], any_of=True)
    enforce_rate_limit(db, principal, 'vector_stores.delete')
    idempotency_fingerprint, cached = _check_openai_idempotency(
        db,
        principal,
        idempotency_key,
        route='DELETE /v1/vector_stores/{vector_store_id}',
        request_payload={'vector_store_id': vector_store_id},
    )
    if cached:
        return cached
    deleted = vs_repo.delete(db, principal, vector_store_id)
    response = {'id': vector_store_id, 'object': 'vector_store.deleted', 'deleted': deleted}
    _store_openai_idempotency(db, principal, idempotency_key, fingerprint=idempotency_fingerprint, response=response)
    db.commit()
    return response


@app.post(
    '/v1/vector_stores/{vector_store_id}/files',
    response_model=OpenAIVectorStoreFile,
    response_model_exclude_none=True,
)
async def attach_file(
    vector_store_id: str,
    payload: dict[str, Any] = Body(...),
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
):
    ensure_scope(principal, 'documents:write')
    enforce_rate_limit(db, principal, 'vector_store_files.create')
    _enforce_vector_store_file_add_rate_limit(db, principal, vector_store_id)
    idempotency_fingerprint, cached = _check_openai_idempotency(
        db,
        principal,
        idempotency_key,
        route='POST /v1/vector_stores/{vector_store_id}/files',
        request_payload={'vector_store_id': vector_store_id, 'payload': payload},
    )
    if cached:
        return cached
    if payload.get('file_id') and 'content' not in payload:
        attrs = _vector_store_file_attach_attributes(payload)
        attached_ids = await _attach_existing_document_ids_to_vector_store(db, principal, vector_store_id, [payload['file_id']], attributes=attrs)
        row = _vector_store_file_row(db, principal, vector_store_id, attached_ids[0])
        if not row:
            raise HTTPException(status_code=500, detail='Attached file could not be retrieved')
        result = _openai_vector_store_file_payload(row)
        _store_openai_idempotency(db, principal, idempotency_key, fingerprint=idempotency_fingerprint, response=result)
        db.commit()
        return result
    try:
        req = DocumentIngestRequest.model_validate({**payload, 'vector_store_id': vector_store_id})
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    req.vector_store_id = vector_store_id
    _refresh_vector_store_activity_or_404(db, principal, vector_store_id)
    try:
        if should_enqueue_ingest(req):
            result = ingestion.enqueue(db, principal, req)
        else:
            result = await ingestion.ingest_now(db, principal, req)
    except VectorStoreUnavailableError as exc:
        raise _vector_store_unavailable_http_exception(exc) from exc
    response = {'id': result.vector_store_file_id, 'object': 'vector_store.file', 'status': result.status, 'vector_store_id': vector_store_id}
    _store_openai_idempotency(db, principal, idempotency_key, fingerprint=idempotency_fingerprint, response=response)
    db.commit()
    return response


def _legal_exact_document_diversity_enabled(query_planner_profile_id: str | None, query_plans: list[Any]) -> bool:
    if query_planner_profile_id != KANSAS_CIVICS_LEGAL_PROFILE_ID:
        return False
    for query_plan in query_plans:
        file_filters = query_plan.filters.get('file_attribute_filters') if isinstance(query_plan.filters, dict) else None
        if isinstance(file_filters, dict) and file_filters:
            return True
    return False


def _vector_store_attributes_for_search(db: Session, principal: Principal, vector_store_id: str) -> dict[str, Any]:
    row = db.execute(text('''
        SELECT attributes
        FROM vector_stores
        WHERE id=:id
          AND tenant_id=:tenant_id
          AND business_instance_id=:biz_id
          AND deleted_at IS NULL
        LIMIT 1
    '''), {'id': vector_store_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id}).mappings().first()
    return dict(row['attributes'] or {}) if row and isinstance(row.get('attributes'), dict) else {}


def _query_planner_profile_id_from_vector_store_attributes(attrs: dict[str, Any]) -> str | None:
    profile_id = os.getenv("SVS_QUERY_PLANNER_PROFILE_ID") or None
    if profile_id != KANSAS_CIVICS_LEGAL_PROFILE_ID:
        return profile_id

    if not attrs:
        return profile_id

    source_collection = str(attrs.get('source_collection') or '').strip().lower()
    corpus = str(attrs.get('corpus') or '').strip().lower()
    if source_collection == 'kscourts-decisions' or corpus in {'kscourts_decisions', 'kansas_court_decisions', 'ks_courts'}:
        return profile_id
    return None


def _query_planner_profile_id_for_vector_store(db: Session, principal: Principal, vector_store_id: str) -> str | None:
    return _query_planner_profile_id_from_vector_store_attributes(
        _vector_store_attributes_for_search(db, principal, vector_store_id)
    )


def _graph_coverage_for_vector_store(db: Session, principal: Principal, vector_store_id: str) -> dict[str, Any]:
    scope_params = {'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'vector_store_id': vector_store_id}
    corpus_row = db.execute(text('''
        SELECT
          count(DISTINCT c.document_id)::int AS documents_indexed,
          count(c.id)::int AS active_chunks
        FROM chunks c
        WHERE c.tenant_id=:tenant_id
          AND c.business_instance_id=:biz_id
          AND c.vector_store_id=:vector_store_id
          AND c.active=true
    '''), scope_params).mappings().first()
    node_rows = db.execute(text('''
        SELECT node_type, count(*)::int AS count
        FROM graph_nodes
        WHERE tenant_id=:tenant_id
          AND business_instance_id=:biz_id
          AND vector_store_id=:vector_store_id
        GROUP BY node_type
        ORDER BY node_type
    '''), scope_params).mappings().all()
    edge_rows = db.execute(text('''
        SELECT edge_type, count(*)::int AS count
        FROM graph_edges
        WHERE tenant_id=:tenant_id
          AND business_instance_id=:biz_id
          AND vector_store_id=:vector_store_id
        GROUP BY edge_type
        ORDER BY edge_type
    '''), scope_params).mappings().all()
    node_type_counts = {str(row['node_type']): int(row['count'] or 0) for row in node_rows}
    edge_type_counts = {str(row['edge_type']): int(row['count'] or 0) for row in edge_rows}
    return {
        'documents_indexed': int((corpus_row or {}).get('documents_indexed') or 0),
        'active_chunks': int((corpus_row or {}).get('active_chunks') or 0),
        'node_count': sum(node_type_counts.values()),
        'edge_count': sum(edge_type_counts.values()),
        'node_type_counts': node_type_counts,
        'edge_type_counts': edge_type_counts,
    }


def _vector_store_search_lenses_payload(
    db: Session,
    principal: Principal,
    vector_store_id: str,
    *,
    include_graph_coverage: bool = True,
) -> dict[str, Any]:
    attrs = _vector_store_attributes_for_search(db, principal, vector_store_id)
    query_planner_profile_id = _query_planner_profile_id_from_vector_store_attributes(attrs)
    cell_profile = _cell_graph_profile_or_503(attrs, principal, vector_store_id)
    graph_enabled = _graphrag_enabled_for_vector_store(attrs, query_planner_profile_id, cell_profile=cell_profile)
    graph_coverage = None
    if include_graph_coverage and graph_enabled:
        graph_coverage = _graph_coverage_for_vector_store(db, principal, vector_store_id)
    return {
        'object': 'vector_store.search_lenses',
        'vector_store_id': vector_store_id,
        'default_lens': DEFAULT_SEARCH_LENS_ID,
        'data': search_lenses_for_vector_store(
            attrs,
            query_planner_profile_id=query_planner_profile_id,
            graph_enabled=graph_enabled,
            graph_coverage=graph_coverage,
        ),
    }


def _document_diversified_chunks(chunks: list[Any]) -> list[Any]:
    buckets: dict[str, list[Any]] = {}
    document_order: list[str] = []
    for chunk in chunks:
        document_key = str(getattr(chunk, 'document_id', None) or getattr(chunk, 'id', len(document_order)))
        if document_key not in buckets:
            buckets[document_key] = []
            document_order.append(document_key)
        buckets[document_key].append(chunk)

    diversified: list[Any] = []
    depth = 0
    while True:
        added = False
        for document_key in document_order:
            bucket = buckets[document_key]
            if depth < len(bucket):
                diversified.append(bucket[depth])
                added = True
        if not added:
            return diversified
        depth += 1


KSCOURTS_GRAPHRAG_INTENT_RE = re.compile(
    r"\b(?:cited\s+by|cites?|cited|authority|authorities|related|same\s+docket|same\s+party|precedent|citation|citations)\b",
    re.I,
)
TOPEKA_GRAPHRAG_INTENT_RE = re.compile(
    r"\b(?:amend(?:ed|ment|s)?|ordinance|charter\s+ordinance|history|references?|defines?|definition|chapter|title|section|contained\s+in)\b",
    re.I,
)


def _env_truthy(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _kscourts_graphrag_enabled(query_planner_profile_id: str | None) -> bool:
    return query_planner_profile_id == KANSAS_CIVICS_LEGAL_PROFILE_ID and _env_truthy("SVS_KSCOURTS_GRAPHRAG_ENABLED")


def _topeka_graphrag_enabled() -> bool:
    return _env_truthy("SVS_TOPEKA_GRAPHRAG_ENABLED") or _env_truthy("SVS_MUNICIPAL_GRAPHRAG_ENABLED")


def _cell_graph_profile_or_503(
    attrs: dict[str, Any], principal: Principal, vector_store_id: str,
) -> CellGraphProfile | None:
    if corpus_kind_for_vector_store(attrs, None) != GRANT_CORPUS_KIND:
        return None
    try:
        return cell_graph_profile_for_store(principal, vector_store_id, attrs)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail='Cell graph profile configuration is invalid or unavailable') from exc


def _graphrag_enabled_for_vector_store(
    attrs: dict[str, Any], query_planner_profile_id: str | None,
    *, cell_profile: CellGraphProfile | None = None,
) -> bool:
    corpus_kind = corpus_kind_for_vector_store(attrs, query_planner_profile_id)
    if corpus_kind == KSCOURTS_CORPUS_KIND:
        return _kscourts_graphrag_enabled(query_planner_profile_id)
    if corpus_kind == TOPEKA_CORPUS_KIND:
        return _topeka_graphrag_enabled()
    if corpus_kind == GRANT_CORPUS_KIND:
        return bool(cell_profile and cell_profile.enabled)
    return False


def _query_has_kscourts_graphrag_intent(query: str | list[str]) -> bool:
    values = query if isinstance(query, list) else [query]
    return any(KSCOURTS_GRAPHRAG_INTENT_RE.search(value or "") for value in values)


def _query_has_topeka_graphrag_intent(query: str | list[str]) -> bool:
    values = query if isinstance(query, list) else [query]
    return any(TOPEKA_GRAPHRAG_INTENT_RE.search(value or "") for value in values)


def _graph_expansion_limit() -> int:
    raw = os.getenv("SVS_KSCOURTS_GRAPHRAG_MAX_EXPANSIONS", "3")
    try:
        return max(0, min(int(raw), 10))
    except ValueError:
        return 3


def _topeka_graph_expansion_limit() -> int:
    raw = os.getenv("SVS_TOPEKA_GRAPHRAG_MAX_EXPANSIONS", "6")
    try:
        return max(0, min(int(raw), 20))
    except ValueError:
        return 6


def _kscourts_graphrag_relation_rows(
    db: Session,
    principal: Principal,
    vector_store_id: str,
    seed_document_ids: list[str],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    if not seed_document_ids or limit <= 0:
        return []
    rows = db.execute(text("""
        WITH seed_opinions AS (
            SELECT id AS seed_node_id,
                   attributes->>'document_id' AS seed_document_id
            FROM graph_nodes
            WHERE tenant_id=:tenant_id
              AND business_instance_id=:biz_id
              AND vector_store_id=:vector_store_id
              AND node_type='opinion'
              AND attributes->>'document_id' = ANY(:seed_document_ids)
        ),
        same_related AS (
            SELECT e.id AS edge_id,
                   e.edge_type AS relation_type,
                   so.seed_document_id,
                   related.id AS related_node_id,
                   related.attributes->>'document_id' AS related_document_id,
                   e.attributes,
                   e.provenance
            FROM seed_opinions so
            JOIN graph_edges e
              ON e.tenant_id=:tenant_id
             AND e.business_instance_id=:biz_id
             AND e.vector_store_id=:vector_store_id
             AND e.edge_type IN ('same_docket', 'related_party')
             AND (e.source_node_id=so.seed_node_id OR e.target_node_id=so.seed_node_id)
            JOIN graph_nodes related
              ON related.tenant_id=e.tenant_id
             AND related.business_instance_id=e.business_instance_id
             AND related.vector_store_id=e.vector_store_id
             AND related.id = CASE
                 WHEN e.source_node_id=so.seed_node_id THEN e.target_node_id
                 ELSE e.source_node_id
               END
             AND related.node_type='opinion'
            WHERE related.attributes->>'document_id' <> so.seed_document_id
        ),
        cited_authority AS (
            SELECT cite.id AS edge_id,
                   'cited_authority' AS relation_type,
                   so.seed_document_id,
                   authority_opinion.id AS related_node_id,
                   authority_opinion.attributes->>'document_id' AS related_document_id,
                   cite.attributes,
                   cite.provenance
            FROM seed_opinions so
            JOIN graph_edges cite
              ON cite.tenant_id=:tenant_id
             AND cite.business_instance_id=:biz_id
             AND cite.vector_store_id=:vector_store_id
             AND cite.edge_type='cites_case'
             AND cite.source_node_id=so.seed_node_id
            JOIN graph_edges source_doc
              ON source_doc.tenant_id=cite.tenant_id
             AND source_doc.business_instance_id=cite.business_instance_id
             AND source_doc.vector_store_id=cite.vector_store_id
             AND source_doc.edge_type='source_document'
             AND source_doc.target_node_id=cite.target_node_id
            JOIN graph_nodes authority_opinion
              ON authority_opinion.tenant_id=source_doc.tenant_id
             AND authority_opinion.business_instance_id=source_doc.business_instance_id
             AND authority_opinion.vector_store_id=source_doc.vector_store_id
             AND authority_opinion.id=source_doc.source_node_id
             AND authority_opinion.node_type='opinion'
            WHERE authority_opinion.attributes->>'document_id' <> so.seed_document_id
        ),
        cited_by AS (
            SELECT cite.id AS edge_id,
                   'cited_by' AS relation_type,
                   so.seed_document_id,
                   citing_opinion.id AS related_node_id,
                   citing_opinion.attributes->>'document_id' AS related_document_id,
                   cite.attributes,
                   cite.provenance
            FROM seed_opinions so
            JOIN graph_edges source_doc
              ON source_doc.tenant_id=:tenant_id
             AND source_doc.business_instance_id=:biz_id
             AND source_doc.vector_store_id=:vector_store_id
             AND source_doc.edge_type='source_document'
             AND source_doc.source_node_id=so.seed_node_id
            JOIN graph_edges cite
              ON cite.tenant_id=source_doc.tenant_id
             AND cite.business_instance_id=source_doc.business_instance_id
             AND cite.vector_store_id=source_doc.vector_store_id
             AND cite.edge_type='cites_case'
             AND cite.target_node_id=source_doc.target_node_id
            JOIN graph_nodes citing_opinion
              ON citing_opinion.tenant_id=cite.tenant_id
             AND citing_opinion.business_instance_id=cite.business_instance_id
             AND citing_opinion.vector_store_id=cite.vector_store_id
             AND citing_opinion.id=cite.source_node_id
             AND citing_opinion.node_type='opinion'
            WHERE citing_opinion.attributes->>'document_id' <> so.seed_document_id
        ),
        all_relations AS (
            SELECT * FROM same_related
            UNION ALL
            SELECT * FROM cited_authority
            UNION ALL
            SELECT * FROM cited_by
        )
        SELECT DISTINCT ON (related_document_id, relation_type)
               edge_id,
               relation_type,
               seed_document_id,
               related_document_id,
               attributes,
               provenance
        FROM all_relations
        WHERE related_document_id IS NOT NULL
        ORDER BY related_document_id, relation_type, edge_id
        LIMIT :limit
    """), {
        "tenant_id": principal.tenant_id,
        "biz_id": principal.business_instance_id,
        "vector_store_id": vector_store_id,
        "seed_document_ids": seed_document_ids,
        "limit": limit,
    }).mappings().all()
    return [dict(row) for row in rows]


def _hydrate_kscourts_graphrag_chunks(
    db: Session,
    principal: Principal,
    vector_store_id: str,
    relation_rows: list[dict[str, Any]],
    existing_document_ids: set[str],
    *,
    limit: int,
) -> tuple[list[ChunkRecord], dict[str, dict[str, Any]]]:
    target_rows = [row for row in relation_rows if row["related_document_id"] not in existing_document_ids]
    if not target_rows or limit <= 0:
        return [], {}
    graph_meta_by_document_id = _kscourts_graphrag_metadata_by_document(relation_rows)
    document_ids = []
    for row in target_rows:
        document_id = str(row["related_document_id"])
        if document_id not in document_ids:
            document_ids.append(document_id)
        if len(document_ids) >= limit:
            break
    rows = db.execute(text("""
        WITH wanted(document_id, graph_rank) AS (
          SELECT document_id, graph_rank
          FROM unnest(CAST(:document_ids AS text[])) WITH ORDINALITY AS t(document_id, graph_rank)
        ),
        ranked_chunks AS (
          SELECT c.id,
                 c.document_id,
                 c.document_version_id,
                 c.ordinal,
                 c.text,
                 c.heading_path,
                 c.page_start,
                 c.page_end,
                 c.metadata,
                 c.security_level,
                 c.classification,
                 c.allowed_groups,
                 c.allowed_roles,
                 d.title,
                 d.filename,
                 d.source_uri,
                 cite.file_id,
                 wanted.graph_rank,
                 row_number() OVER (PARTITION BY c.document_id ORDER BY c.ordinal) AS chunk_rank
          FROM wanted
          JOIN chunks c
            ON c.document_id=wanted.document_id
           AND c.tenant_id=:tenant_id
           AND c.business_instance_id=:biz_id
           AND c.vector_store_id=:vector_store_id
           AND c.active=true
           AND c.security_level <= :max_security_level
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
                dv.metadata #>> '{attributes,_openai_file_id}',
                f.document_id,
                f.id
            ) AS file_id
            FROM vector_store_files f
            WHERE f.tenant_id=c.tenant_id
              AND f.business_instance_id=c.business_instance_id
              AND f.document_id=c.document_id
              AND f.vector_store_id=:vector_store_id
              AND f.status <> 'cancelled'
            ORDER BY f.created_at DESC
            LIMIT 1
          ) cite ON true
        )
        SELECT *
        FROM ranked_chunks
        WHERE chunk_rank=1
        ORDER BY graph_rank
        LIMIT :limit
    """), {
        "tenant_id": principal.tenant_id,
        "biz_id": principal.business_instance_id,
        "vector_store_id": vector_store_id,
        "max_security_level": principal.max_security_level,
        "document_ids": document_ids,
        "limit": limit,
    }).mappings().all()
    scope = build_retrieval_scope(principal)
    chunks = []
    metadata_by_chunk_id: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows, start=1):
        metadata = graph_meta_by_document_id.get(str(row["document_id"]), {})
        chunk = ChunkRecord(
            id=row["id"],
            document_id=row["document_id"],
            document_version_id=row["document_version_id"],
            file_id=row["file_id"],
            title=row["title"],
            filename=row["filename"],
            source_uri=row["source_uri"],
            ordinal=row["ordinal"],
            text=row["text"],
            heading_path=list(row["heading_path"] or []),
            page_start=row["page_start"],
            page_end=row["page_end"],
            metadata=dict(row["metadata"] or {}),
            security_level=row["security_level"],
            classification=row["classification"],
            allowed_groups=list(row["allowed_groups"] or []),
            allowed_roles=list(row["allowed_roles"] or []),
            score=max(0.01, round(0.66 - (index * 0.01), 6)),
            source="kscourts_graphrag_expansion",
        )
        if not chunk_allowed_by_scope(chunk, scope):
            continue
        chunk.citation = {"graph_expansion": metadata}
        metadata_by_chunk_id[chunk.id] = metadata
        chunks.append(chunk)
    return chunks, metadata_by_chunk_id


def _kscourts_graphrag_metadata_by_document(relation_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for row in relation_rows:
        document_id = str(row["related_document_id"])
        metadata.setdefault(document_id, {
            "profile": "kscourts_postgres_graph_v1",
            "relation_type": row["relation_type"],
            "edge_id": row["edge_id"],
            "source_document_id": row["seed_document_id"],
            "target_document_id": document_id,
            "attributes": dict(row.get("attributes") or {}),
            "provenance": dict(row.get("provenance") or {}),
        })
    return metadata


def _topeka_input_citation_values(inputs: dict[str, Any] | None) -> list[str]:
    values: list[str] = []
    for key in ("citation", "title", "chapter", "section"):
        value = (inputs or {}).get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        raw = value.strip()
        candidates = {
            raw,
            raw.replace("TMC ", "").replace("tmc ", "").strip(),
            raw.replace("TMC/", "").replace("tmc/", "").strip(),
        }
        if "/TMC/" in raw:
            candidates.add(raw.rsplit("/TMC/", 1)[-1].strip("/"))
        for candidate in candidates:
            normalized = candidate.strip().strip("/")
            if normalized:
                values.append(normalized.lower())
    return sorted(set(values))


def _topeka_input_ordinance_values(inputs: dict[str, Any] | None) -> list[str]:
    value = (inputs or {}).get("ordinance_number")
    if not isinstance(value, str) or not value.strip():
        return []
    raw = value.strip()
    candidates = {
        raw,
        re.sub(r"(?i)^ordinance\s+", "", raw).strip(),
        re.sub(r"(?i)^charter\s+ordinance\s+", "", raw).strip(),
    }
    return sorted({candidate.lower() for candidate in candidates if candidate})


def _topeka_input_term_like(inputs: dict[str, Any] | None) -> str | None:
    value = (inputs or {}).get("term")
    if not isinstance(value, str) or not value.strip():
        return None
    return f"%{value.strip().lower()}%"


def _topeka_graph_seed_rows(
    db: Session,
    principal: Principal,
    vector_store_id: str,
    chunks: list[ChunkRecord],
    inputs: dict[str, Any] | None,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    seed_rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    def append_rows(rows: list[dict[str, Any]]) -> None:
        for row in rows:
            node_id = str(row.get("id") or "")
            if not node_id or node_id in seen:
                continue
            seen.add(node_id)
            seed_rows.append(row)

    document_ids = []
    for chunk in chunks:
        if chunk.document_id and chunk.document_id not in document_ids:
            document_ids.append(chunk.document_id)
        if len(document_ids) >= 12:
            break
    scope_params = {"tenant_id": principal.tenant_id, "biz_id": principal.business_instance_id, "vector_store_id": vector_store_id}
    if document_ids:
        rows = db.execute(text("""
            WITH wanted_documents(document_id, graph_rank) AS (
              SELECT document_id, graph_rank
              FROM unnest(CAST(:document_ids AS text[])) WITH ORDINALITY AS t(document_id, graph_rank)
            )
            SELECT DISTINCT ON (n.id)
                   n.id,
                   n.node_type,
                   n.node_key,
                   n.label,
                   n.attributes,
                   wanted_documents.graph_rank,
                   wanted_documents.document_id AS matched_document_id
            FROM wanted_documents
            JOIN documents d
              ON d.id=wanted_documents.document_id
             AND d.tenant_id=:tenant_id
             AND d.business_instance_id=:biz_id
            LEFT JOIN vector_store_files f
              ON f.tenant_id=d.tenant_id
             AND f.business_instance_id=d.business_instance_id
             AND f.document_id=d.id
             AND f.vector_store_id=:vector_store_id
             AND f.status <> 'cancelled'
            JOIN graph_nodes n
              ON n.tenant_id=d.tenant_id
             AND n.business_instance_id=d.business_instance_id
             AND n.vector_store_id=:vector_store_id
             AND (
                  d.source_uri = n.attributes->>'source_url'
               OR d.source_uri = n.attributes->>'citation_url'
               OR d.source_uri = n.attributes->>'pdf_url'
               OR d.source_uri = n.attributes->>'url'
               OR f.attributes->>'source_url' = n.attributes->>'source_url'
               OR f.attributes->>'citation_url' = n.attributes->>'citation_url'
               OR f.attributes->>'pdf_url' = n.attributes->>'pdf_url'
               OR f.attributes->>'section_id' = n.id
               OR f.attributes->>'section_id' = n.attributes->>'section_id'
               OR f.attributes->>'citation' = n.attributes->>'citation'
               OR f.attributes->>'ordinance_number' = n.attributes->>'ordinance_number'
               OR f.attributes->>'ordinance_number' = n.attributes->>'ordinance'
             )
            ORDER BY n.id, wanted_documents.graph_rank
            LIMIT :limit
        """), {**scope_params, "document_ids": document_ids, "limit": limit}).mappings().all()
        append_rows([dict(row) for row in rows])

    citation_values = _topeka_input_citation_values(inputs) or ["__svs_no_citation__"]
    ordinance_values = _topeka_input_ordinance_values(inputs) or ["__svs_no_ordinance__"]
    term_like = _topeka_input_term_like(inputs)
    if citation_values != ["__svs_no_citation__"] or ordinance_values != ["__svs_no_ordinance__"] or term_like:
        rows = db.execute(text("""
            SELECT DISTINCT ON (n.id)
                   n.id,
                   n.node_type,
                   n.node_key,
                   n.label,
                   n.attributes,
                   0 AS graph_rank,
                   NULL::text AS matched_document_id
            FROM graph_nodes n
            WHERE n.tenant_id=:tenant_id
              AND n.business_instance_id=:biz_id
              AND n.vector_store_id=:vector_store_id
              AND (
                   lower(coalesce(n.node_key, '')) = ANY(CAST(:citation_values AS text[]))
                OR lower(coalesce(n.attributes->>'citation', '')) = ANY(CAST(:citation_values AS text[]))
                OR lower(coalesce(n.attributes->>'manifest_id', '')) = ANY(CAST(:citation_values AS text[]))
                OR lower(coalesce(n.attributes->>'section_id', '')) = ANY(CAST(:citation_values AS text[]))
                OR lower(coalesce(n.attributes->>'ordinance_number', '')) = ANY(CAST(:ordinance_values AS text[]))
                OR lower(coalesce(n.attributes->>'ordinance', '')) = ANY(CAST(:ordinance_values AS text[]))
                OR (CAST(:term_like AS text) IS NOT NULL AND n.node_type='definition' AND lower(n.label) LIKE CAST(:term_like AS text))
              )
            ORDER BY n.id
            LIMIT :limit
        """), {
            **scope_params,
            "citation_values": citation_values,
            "ordinance_values": ordinance_values,
            "term_like": term_like,
            "limit": limit,
        }).mappings().all()
        append_rows([dict(row) for row in rows])
    return seed_rows[:limit]


def _topeka_municipal_graph_relation_rows(
    db: Session,
    principal: Principal,
    vector_store_id: str,
    seed_node_ids: list[str],
    relation_types: tuple[str, ...],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    if not seed_node_ids or not relation_types or limit <= 0:
        return []
    rows = db.execute(text("""
        WITH RECURSIVE seed_nodes AS (
          SELECT n.id AS seed_node_id,
                 n.node_type AS seed_node_type,
                 n.node_key AS seed_node_key,
                 n.label AS seed_label,
                 n.attributes AS seed_attributes,
                 wanted.seed_rank
          FROM unnest(CAST(:seed_node_ids AS text[])) WITH ORDINALITY AS wanted(id, seed_rank)
          JOIN graph_nodes n
            ON n.id=wanted.id
           AND n.tenant_id=:tenant_id
           AND n.business_instance_id=:biz_id
           AND n.vector_store_id=:vector_store_id
        ),
        direct_relations AS (
          SELECT e.id AS edge_id,
                 e.edge_type AS relation_type,
                 e.source_node_id,
                 e.target_node_id,
                 s.seed_node_id,
                 s.seed_node_type,
                 s.seed_node_key,
                 s.seed_label,
                 s.seed_attributes,
                 CASE WHEN e.source_node_id=s.seed_node_id THEN 'outgoing' ELSE 'incoming' END AS direction,
                 related.id AS related_node_id,
                 related.node_type AS related_node_type,
                 related.node_key AS related_node_key,
                 related.label AS related_label,
                 related.attributes AS related_attributes,
                 e.attributes,
                 e.provenance,
                 s.seed_rank,
                 1::int AS graph_distance
          FROM seed_nodes s
          JOIN graph_edges e
            ON e.tenant_id=:tenant_id
           AND e.business_instance_id=:biz_id
           AND e.vector_store_id=:vector_store_id
           AND e.edge_type = ANY(CAST(:relation_types AS text[]))
           AND (e.source_node_id=s.seed_node_id OR e.target_node_id=s.seed_node_id)
          JOIN graph_nodes related
            ON related.tenant_id=e.tenant_id
           AND related.business_instance_id=e.business_instance_id
           AND related.vector_store_id=e.vector_store_id
           AND related.id = CASE
               WHEN e.source_node_id=s.seed_node_id THEN e.target_node_id
               ELSE e.source_node_id
             END
          WHERE related.id <> s.seed_node_id
        ),
        contains_walk AS (
          SELECT e.id AS edge_id,
                 e.edge_type AS relation_type,
                 e.source_node_id,
                 e.target_node_id,
                 s.seed_node_id,
                 s.seed_node_type,
                 s.seed_node_key,
                 s.seed_label,
                 s.seed_attributes,
                 'outgoing'::text AS direction,
                 related.id AS related_node_id,
                 related.node_type AS related_node_type,
                 related.node_key AS related_node_key,
                 related.label AS related_label,
                 related.attributes AS related_attributes,
                 e.attributes,
                 e.provenance,
                 s.seed_rank,
                 1::int AS graph_distance,
                 ARRAY[s.seed_node_id, related.id]::text[] AS visited_nodes
          FROM seed_nodes s
          JOIN graph_edges e
            ON e.tenant_id=:tenant_id
           AND e.business_instance_id=:biz_id
           AND e.vector_store_id=:vector_store_id
           AND e.edge_type='CONTAINS'
           AND e.source_node_id=s.seed_node_id
           AND 'CONTAINS' = ANY(CAST(:relation_types AS text[]))
          JOIN graph_nodes related
            ON related.tenant_id=e.tenant_id
           AND related.business_instance_id=e.business_instance_id
           AND related.vector_store_id=e.vector_store_id
           AND related.id=e.target_node_id
          WHERE related.id <> s.seed_node_id
          UNION ALL
          SELECT e.id AS edge_id,
                 e.edge_type AS relation_type,
                 e.source_node_id,
                 e.target_node_id,
                 cw.seed_node_id,
                 cw.seed_node_type,
                 cw.seed_node_key,
                 cw.seed_label,
                 cw.seed_attributes,
                 'descendant'::text AS direction,
                 related.id AS related_node_id,
                 related.node_type AS related_node_type,
                 related.node_key AS related_node_key,
                 related.label AS related_label,
                 related.attributes AS related_attributes,
                 e.attributes,
                 e.provenance,
                 cw.seed_rank,
                 cw.graph_distance + 1 AS graph_distance,
                 array_append(cw.visited_nodes, related.id) AS visited_nodes
          FROM contains_walk cw
          JOIN graph_edges e
            ON e.tenant_id=:tenant_id
           AND e.business_instance_id=:biz_id
           AND e.vector_store_id=:vector_store_id
           AND e.edge_type='CONTAINS'
           AND e.source_node_id=cw.related_node_id
          JOIN graph_nodes related
            ON related.tenant_id=e.tenant_id
           AND related.business_instance_id=e.business_instance_id
           AND related.vector_store_id=e.vector_store_id
           AND related.id=e.target_node_id
          WHERE cw.graph_distance < 4
            AND NOT related.id = ANY(cw.visited_nodes)
        ),
        contains_descendants AS (
          SELECT edge_id,
                 relation_type,
                 source_node_id,
                 target_node_id,
                 seed_node_id,
                 seed_node_type,
                 seed_node_key,
                 seed_label,
                 seed_attributes,
                 direction,
                 related_node_id,
                 related_node_type,
                 related_node_key,
                 related_label,
                 related_attributes,
                 attributes,
                 provenance,
                 seed_rank,
                 graph_distance
          FROM contains_walk
          WHERE graph_distance > 1
            AND related_node_type IN ('section', 'table')
        ),
        all_relations AS (
          SELECT * FROM direct_relations
          UNION ALL
          SELECT * FROM contains_descendants
        ),
        deduped_relations AS (
          SELECT DISTINCT ON (related_node_id, relation_type)
                 edge_id,
                 relation_type,
                 source_node_id,
                 target_node_id,
                 seed_node_id,
                 seed_node_type,
                 seed_node_key,
                 seed_label,
                 seed_attributes,
                 direction,
                 related_node_id,
                 related_node_type,
                 related_node_key,
                 related_label,
                 related_attributes,
                 attributes,
                 provenance,
                 seed_rank,
                 graph_distance
          FROM all_relations
          ORDER BY related_node_id, relation_type, graph_distance, seed_rank, edge_id
        )
        SELECT
               edge_id,
               relation_type,
               source_node_id,
               target_node_id,
               seed_node_id,
               seed_node_type,
               seed_node_key,
               seed_label,
               seed_attributes,
               direction,
               related_node_id,
               related_node_type,
               related_node_key,
               related_label,
               related_attributes,
               attributes,
               provenance,
               graph_distance
        FROM deduped_relations
        ORDER BY graph_distance, seed_rank, relation_type, related_node_key, edge_id
        LIMIT :limit
    """), {
        "tenant_id": principal.tenant_id,
        "biz_id": principal.business_instance_id,
        "vector_store_id": vector_store_id,
        "seed_node_ids": seed_node_ids,
        "relation_types": list(relation_types),
        "limit": limit,
    }).mappings().all()
    return [dict(row) for row in rows]


def _topeka_graph_metadata(row: dict[str, Any]) -> dict[str, Any]:
    attributes = dict(row.get("attributes") or {})
    related_attributes = dict(row.get("related_attributes") or {})
    seed_attributes = dict(row.get("seed_attributes") or {})

    def node_url(node_attributes: dict[str, Any]) -> Any:
        return (
            node_attributes.get("citation_url")
            or node_attributes.get("source_url")
            or node_attributes.get("pdf_url")
            or node_attributes.get("url")
        )

    related_node_url = node_url(related_attributes)
    seed_node_url = node_url(seed_attributes)
    edge_source_url = (
        attributes.get("observed_in_section_url")
        or attributes.get("source_url")
        or attributes.get("citation_url")
    )
    edge_target_url = attributes.get("target_url") or attributes.get("pdf_url")
    source_node_id = row.get("source_node_id")
    target_node_id = row.get("target_node_id")
    seed_node_id = row.get("seed_node_id")
    related_node_id = row.get("related_node_id")
    relationship_source_url = edge_source_url
    if related_node_id == source_node_id:
        relationship_source_url = related_node_url or relationship_source_url
    elif seed_node_id == source_node_id:
        relationship_source_url = seed_node_url or relationship_source_url
    relationship_target_url = edge_target_url
    if related_node_id == target_node_id:
        relationship_target_url = related_node_url or relationship_target_url
    elif seed_node_id == target_node_id:
        relationship_target_url = seed_node_url or relationship_target_url
    citation_url = (
        related_node_url
        or (
            relationship_target_url
            if row.get("relation_type") in {"CONTAINS", "REFERENCES", "DEFINES"}
            else None
        )
        or attributes.get("pdf_url")
        or attributes.get("citation_url")
        or relationship_target_url
        or relationship_source_url
    )
    return {
        "profile": TOPEKA_GRAPH_HANDLER_ID,
        "relation_type": row.get("relation_type"),
        "edge_id": row.get("edge_id"),
        "direction": row.get("direction"),
        "seed_node_id": row.get("seed_node_id"),
        "seed_node_type": row.get("seed_node_type"),
        "seed_node_key": row.get("seed_node_key"),
        "source_node_id": row.get("source_node_id"),
        "target_node_id": row.get("target_node_id"),
        "related_node_id": row.get("related_node_id"),
        "related_node_type": row.get("related_node_type"),
        "related_node_key": row.get("related_node_key"),
        "related_label": row.get("related_label"),
        "seed_label": row.get("seed_label"),
        "graph_distance": row.get("graph_distance"),
        "citation_url": citation_url,
        "relationship_source_url": relationship_source_url,
        "relationship_target_url": relationship_target_url,
        "attributes": attributes,
        "related_attributes": related_attributes,
        "provenance": dict(row.get("provenance") or {}),
    }


def _topeka_relation_candidate_values(relation_rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    values: dict[str, set[str]] = {
        "node_ids": set(),
        "source_uris": set(),
        "citations": set(),
        "ordinance_numbers": set(),
    }
    for row in relation_rows:
        node_id = str(row.get("related_node_id") or "").strip()
        if node_id:
            values["node_ids"].add(node_id)
        related_node_key = str(row.get("related_node_key") or "").strip()
        if related_node_key:
            if str(row.get("related_node_type") or "").strip() == "ordinance_pdf":
                values["ordinance_numbers"].add(related_node_key)
            else:
                values["citations"].add(related_node_key)
        related_label = str(row.get("related_label") or "").strip()
        if related_label and str(row.get("related_node_type") or "").strip() == "ordinance_pdf":
            values["ordinance_numbers"].add(related_label)
        for attrs in (row.get("related_attributes"), row.get("attributes")):
            if not isinstance(attrs, dict):
                continue
            for key in ("source_url", "citation_url", "pdf_url", "url", "observed_in_section_url", "target_url"):
                value = attrs.get(key)
                if isinstance(value, str) and value.strip():
                    values["source_uris"].add(value.strip())
            for key in ("citation", "target_citation"):
                value = attrs.get(key)
                if isinstance(value, str) and value.strip():
                    values["citations"].add(value.strip())
            for key in ("ordinance_number", "ordinance"):
                value = attrs.get(key)
                if isinstance(value, str) and value.strip():
                    values["ordinance_numbers"].add(value.strip())
                elif value is not None and not isinstance(value, (dict, list)):
                    values["ordinance_numbers"].add(str(value))
    return {key: sorted(value) or [f"__svs_no_{key}__"] for key, value in values.items()}


def _topeka_relation_matches_document(row: dict[str, Any], document_row: Any) -> bool:
    document_values = {
        str(document_row.get("source_uri") or ""),
        str(document_row.get("node_id") or ""),
    }
    file_attributes = dict(document_row.get("file_attributes") or {})
    for key in ("source_url", "citation_url", "pdf_url", "url", "section_id", "citation", "ordinance_number"):
        value = file_attributes.get(key)
        if value is not None:
            document_values.add(str(value))
    document_values = {value for value in document_values if value}

    related_attributes = dict(row.get("related_attributes") or {})
    relation_attributes = dict(row.get("attributes") or {})
    candidate_values = {
        str(row.get("related_node_id") or ""),
        str(row.get("related_node_key") or ""),
        str(row.get("related_label") or ""),
    }
    for attrs in (related_attributes, relation_attributes):
        for key in (
            "source_url",
            "citation_url",
            "pdf_url",
            "url",
            "observed_in_section_url",
            "target_url",
            "section_id",
            "citation",
            "target_citation",
            "ordinance_number",
            "ordinance",
        ):
            value = attrs.get(key)
            if value is not None:
                candidate_values.add(str(value))
    return bool(document_values & {value for value in candidate_values if value})


def _topeka_document_citation_url(document_row: Any) -> str | None:
    file_attributes = dict(document_row.get("file_attributes") or {})
    for key in ("citation_url", "source_url", "pdf_url", "url"):
        value = file_attributes.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    source_uri = document_row.get("source_uri")
    if isinstance(source_uri, str) and source_uri.strip():
        return source_uri.strip()
    return None


def _topeka_metadata_for_document(row: Any, relation_rows: list[dict[str, Any]]) -> dict[str, Any]:
    for relation_row in relation_rows:
        if _topeka_relation_matches_document(relation_row, row):
            metadata = _topeka_graph_metadata(relation_row)
            document_citation_url = _topeka_document_citation_url(row)
            if document_citation_url:
                metadata = {**metadata, "citation_url": document_citation_url}
            return metadata
    return {}


def _hydrate_topeka_municipal_graph_chunks(
    db: Session,
    principal: Principal,
    vector_store_id: str,
    relation_rows: list[dict[str, Any]],
    existing_document_ids: set[str],
    *,
    limit: int,
) -> tuple[list[ChunkRecord], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    if not relation_rows or limit <= 0:
        return [], {}, {}
    candidates = _topeka_relation_candidate_values(relation_rows)
    has_candidates = any(not (len(value) == 1 and value[0].startswith("__svs_no_")) for value in candidates.values())
    if not has_candidates:
        return [], {}, {}
    rows = db.execute(text("""
        WITH candidate_documents AS (
          SELECT DISTINCT ON (d.id)
                 d.id AS document_id,
                 d.title,
                 d.filename,
                 d.source_uri,
                 f.attributes AS file_attributes,
                 coalesce(
                   f.attributes->>'attached_from_file_id',
                   dv.metadata #>> '{attributes,_openai_file_id}',
                   f.document_id,
                   f.id
                 ) AS file_id,
                 CASE
                   WHEN d.source_uri = ANY(CAST(:source_uris AS text[])) THEN array_position(CAST(:source_uris AS text[]), d.source_uri)
                   WHEN f.attributes->>'source_url' = ANY(CAST(:source_uris AS text[])) THEN array_position(CAST(:source_uris AS text[]), f.attributes->>'source_url')
                   WHEN f.attributes->>'citation_url' = ANY(CAST(:source_uris AS text[])) THEN array_position(CAST(:source_uris AS text[]), f.attributes->>'citation_url')
                   WHEN f.attributes->>'pdf_url' = ANY(CAST(:source_uris AS text[])) THEN array_position(CAST(:source_uris AS text[]), f.attributes->>'pdf_url')
                   WHEN f.attributes->>'section_id' = ANY(CAST(:node_ids AS text[])) THEN array_position(CAST(:node_ids AS text[]), f.attributes->>'section_id')
                   WHEN f.attributes->>'citation' = ANY(CAST(:citations AS text[])) THEN array_position(CAST(:citations AS text[]), f.attributes->>'citation')
                   WHEN f.attributes->>'ordinance_number' = ANY(CAST(:ordinance_numbers AS text[])) THEN array_position(CAST(:ordinance_numbers AS text[]), f.attributes->>'ordinance_number')
                   ELSE 999999
                 END AS graph_rank
          FROM documents d
          JOIN vector_store_files f
            ON f.tenant_id=d.tenant_id
           AND f.business_instance_id=d.business_instance_id
           AND f.document_id=d.id
           AND f.vector_store_id=:vector_store_id
           AND f.status <> 'cancelled'
          LEFT JOIN document_versions dv
            ON dv.id=d.current_version_id
           AND dv.document_id=d.id
           AND dv.tenant_id=d.tenant_id
           AND dv.business_instance_id=d.business_instance_id
          WHERE d.tenant_id=:tenant_id
            AND d.business_instance_id=:biz_id
            AND (
                 d.source_uri = ANY(CAST(:source_uris AS text[]))
              OR f.attributes->>'source_url' = ANY(CAST(:source_uris AS text[]))
              OR f.attributes->>'citation_url' = ANY(CAST(:source_uris AS text[]))
              OR f.attributes->>'pdf_url' = ANY(CAST(:source_uris AS text[]))
              OR f.attributes->>'section_id' = ANY(CAST(:node_ids AS text[]))
              OR f.attributes->>'citation' = ANY(CAST(:citations AS text[]))
              OR f.attributes->>'ordinance_number' = ANY(CAST(:ordinance_numbers AS text[]))
            )
          ORDER BY d.id, graph_rank
        ),
        ranked_chunks AS (
          SELECT c.id,
                 c.document_id,
                 c.document_version_id,
                 c.ordinal,
                 c.text,
                 c.heading_path,
                 c.page_start,
                 c.page_end,
                 c.metadata,
                 c.security_level,
                 c.classification,
                 c.allowed_groups,
                 c.allowed_roles,
                 cd.title,
                 cd.filename,
                 cd.source_uri,
                 cd.file_id,
                 cd.file_attributes,
                 cd.graph_rank,
                 row_number() OVER (PARTITION BY c.document_id ORDER BY c.ordinal) AS chunk_rank
          FROM candidate_documents cd
          JOIN chunks c
            ON c.document_id=cd.document_id
           AND c.tenant_id=:tenant_id
           AND c.business_instance_id=:biz_id
           AND c.vector_store_id=:vector_store_id
           AND c.active=true
           AND c.security_level <= :max_security_level
        )
        SELECT *
        FROM ranked_chunks
        WHERE chunk_rank=1
        ORDER BY graph_rank, ordinal
        LIMIT :limit
    """), {
        "tenant_id": principal.tenant_id,
        "biz_id": principal.business_instance_id,
        "vector_store_id": vector_store_id,
        "max_security_level": principal.max_security_level,
        "node_ids": candidates["node_ids"],
        "source_uris": candidates["source_uris"],
        "citations": candidates["citations"],
        "ordinance_numbers": candidates["ordinance_numbers"],
        "limit": max(limit, 50),
    }).mappings().all()
    scope = build_retrieval_scope(principal)
    chunks: list[ChunkRecord] = []
    metadata_by_chunk_id: dict[str, dict[str, Any]] = {}
    metadata_by_document_id: dict[str, dict[str, Any]] = {}
    seen_documents: set[str] = set()
    for index, row in enumerate(rows, start=1):
        metadata = _topeka_metadata_for_document(row, relation_rows)
        metadata_by_document_id.setdefault(str(row["document_id"]), metadata)
        document_id = str(row["document_id"])
        if document_id in existing_document_ids or document_id in seen_documents:
            continue
        chunk = ChunkRecord(
            id=row["id"],
            document_id=document_id,
            document_version_id=row["document_version_id"],
            file_id=row["file_id"],
            title=row["title"],
            filename=row["filename"],
            source_uri=row["source_uri"],
            ordinal=row["ordinal"],
            text=row["text"],
            heading_path=list(row["heading_path"] or []),
            page_start=row["page_start"],
            page_end=row["page_end"],
            metadata=dict(row["metadata"] or {}),
            security_level=row["security_level"],
            classification=row["classification"],
            allowed_groups=list(row["allowed_groups"] or []),
            allowed_roles=list(row["allowed_roles"] or []),
            score=max(0.01, round(0.64 - (index * 0.01), 6)),
            source="topeka_municipal_graph_expansion",
        )
        if not chunk_allowed_by_scope(chunk, scope):
            continue
        chunk.citation = {"graph_expansion": metadata}
        metadata_by_chunk_id[chunk.id] = metadata
        chunks.append(chunk)
        seen_documents.add(document_id)
        if len(chunks) >= limit:
            break
    return chunks, metadata_by_chunk_id, metadata_by_document_id


def _apply_topeka_municipal_graphrag_expansion(
    db: Session,
    principal: Principal,
    vector_store_id: str,
    chunks: list[ChunkRecord],
    *,
    enabled: bool,
    query: str | list[str],
    force: bool = False,
    lens: dict[str, Any] | None = None,
    inputs: dict[str, Any] | None = None,
    relation_types: tuple[str, ...] = (),
    graph_coverage: dict[str, Any] | None = None,
    max_expansions: int | None = None,
) -> tuple[list[ChunkRecord], dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any] | None]:
    if not enabled:
        return chunks, {}, {}, None
    lens_id = (lens or {}).get("id")
    summary_base = {
        "enabled": True,
        "profile": TOPEKA_GRAPH_HANDLER_ID,
        "lens": lens_id,
        "coverage": graph_coverage or {},
        "warnings": list((lens or {}).get("warnings") or []),
    }
    if not force and not _query_has_topeka_graphrag_intent(query):
        return chunks, {}, {}, {**summary_base, "applied": False, "reason": "no_graph_intent"}
    limit = _topeka_graph_expansion_limit()
    if max_expansions is not None:
        limit = min(limit, max_expansions)
    if limit <= 0:
        return chunks, {}, {}, {**summary_base, "applied": False, "reason": "graph_expansion_limit_zero"}
    seed_rows = _topeka_graph_seed_rows(db, principal, vector_store_id, chunks, inputs, limit=24)
    seed_node_ids = [str(row["id"]) for row in seed_rows]
    if not seed_node_ids:
        return chunks, {}, {}, {**summary_base, "applied": False, "reason": "no_seed_nodes"}
    relation_rows = _topeka_municipal_graph_relation_rows(
        db,
        principal,
        vector_store_id,
        seed_node_ids,
        relation_types,
        limit=limit * 8,
    )
    graph_chunks, metadata_by_chunk_id, metadata_by_document_id = _hydrate_topeka_municipal_graph_chunks(
        db,
        principal,
        vector_store_id,
        relation_rows,
        {chunk.document_id for chunk in chunks},
        limit=limit,
    )
    expanded = _interleave_graph_expansion_chunks(chunks, graph_chunks[:limit])
    relation_type_values = sorted({str(row["relation_type"]) for row in relation_rows})
    return expanded, metadata_by_document_id, metadata_by_chunk_id, {
        **summary_base,
        "enabled": True,
        "applied": bool(relation_rows),
        "seed_node_count": len(seed_node_ids),
        "candidate_count": len(relation_rows),
        "inserted_chunk_count": len(graph_chunks),
        "relation_types": relation_type_values,
    }


def _interleave_graph_expansion_chunks(chunks: list[ChunkRecord], graph_chunks: list[ChunkRecord]) -> list[ChunkRecord]:
    if not graph_chunks:
        return chunks
    existing_ids = {chunk.id for chunk in chunks}
    additions = [chunk for chunk in graph_chunks if chunk.id not in existing_ids]
    if not additions:
        return chunks
    if not chunks:
        return additions
    return [chunks[0], *additions, *chunks[1:]]


def _annotate_openai_search_page_with_graph(
    page: dict[str, Any],
    graph_metadata_by_document_id: dict[str, dict[str, Any]],
    graph_metadata_by_chunk_id: dict[str, dict[str, Any]],
    summary: dict[str, Any],
) -> dict[str, Any]:
    annotated = 0
    for item in page.get("data") or []:
        citation = item.get("citation") if isinstance(item, dict) else None
        if not isinstance(citation, dict):
            continue
        graph_metadata = (
            graph_metadata_by_chunk_id.get(str(citation.get("chunk_id")))
            or graph_metadata_by_document_id.get(str(citation.get("document_id")))
        )
        if not graph_metadata:
            continue
        citation["graph_expansion"] = graph_metadata
        for candidate in item.get("citations") or []:
            if isinstance(candidate, dict) and candidate.get("chunk_id") == citation.get("chunk_id"):
                candidate["graph_expansion"] = graph_metadata
        annotated += 1
    for citation in page.get("citations") or []:
        if not isinstance(citation, dict):
            continue
        graph_metadata = (
            graph_metadata_by_chunk_id.get(str(citation.get("chunk_id")))
            or graph_metadata_by_document_id.get(str(citation.get("document_id")))
        )
        if graph_metadata:
            citation["graph_expansion"] = graph_metadata
    graph_summary = dict(summary)
    graph_summary["annotated_result_count"] = annotated
    page["graph_expansion"] = graph_summary
    return page


def _apply_kscourts_graphrag_expansion(
    db: Session,
    principal: Principal,
    vector_store_id: str,
    chunks: list[ChunkRecord],
    *,
    enabled: bool,
    query: str | list[str],
    force: bool = False,
    lens: dict[str, Any] | None = None,
    relation_types: tuple[str, ...] = (),
    graph_coverage: dict[str, Any] | None = None,
    max_expansions: int | None = None,
) -> tuple[list[ChunkRecord], dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any] | None]:
    if not enabled:
        return chunks, {}, {}, None
    lens_id = (lens or {}).get("id")
    summary_base = {
        "enabled": True,
        "lens": lens_id,
        "coverage": graph_coverage or {},
        "warnings": list((lens or {}).get("warnings") or []),
    }
    if not force and not _query_has_kscourts_graphrag_intent(query):
        return chunks, {}, {}, {**summary_base, "applied": False, "reason": "no_graph_intent"}
    seed_document_ids = []
    for chunk in chunks:
        if chunk.document_id not in seed_document_ids:
            seed_document_ids.append(chunk.document_id)
        if len(seed_document_ids) >= 10:
            break
    limit = _graph_expansion_limit()
    if max_expansions is not None:
        limit = min(limit, max_expansions)
    if limit <= 0:
        return chunks, {}, {}, {**summary_base, "applied": False, "reason": "graph_expansion_limit_zero"}
    if not seed_document_ids:
        return chunks, {}, {}, {**summary_base, "applied": False, "reason": "no_seed_documents"}
    relation_rows = _kscourts_graphrag_relation_rows(db, principal, vector_store_id, seed_document_ids, limit=limit * 4)
    if relation_types:
        allowed_relation_types = set(relation_types)
        relation_rows = [row for row in relation_rows if str(row.get("relation_type") or "") in allowed_relation_types]
    metadata_by_document_id = _kscourts_graphrag_metadata_by_document(relation_rows)
    graph_chunks, metadata_by_chunk_id = _hydrate_kscourts_graphrag_chunks(
        db,
        principal,
        vector_store_id,
        relation_rows,
        {chunk.document_id for chunk in chunks},
        limit=limit,
    )
    expanded = _interleave_graph_expansion_chunks(chunks, graph_chunks[:limit])
    relation_types = sorted({str(row["relation_type"]) for row in relation_rows})
    return expanded, metadata_by_document_id, metadata_by_chunk_id, {
        **summary_base,
        "enabled": True,
        "applied": bool(relation_rows),
        "candidate_count": len(relation_rows),
        "inserted_chunk_count": len(graph_chunks),
        "relation_types": relation_types,
    }


async def _openai_vector_store_search_page(
    vector_store_id: str,
    req: OpenAIVectorStoreSearchRequest,
    principal: Principal,
    db: Session,
) -> dict[str, Any]:
    _refresh_vector_store_activity_or_404(db, principal, vector_store_id)
    vector_store_attrs = _vector_store_attributes_for_search(db, principal, vector_store_id)
    query_planner_profile_id = _query_planner_profile_id_from_vector_store_attributes(vector_store_attrs)
    corpus_kind = corpus_kind_for_vector_store(vector_store_attrs, query_planner_profile_id)
    cell_profile = _cell_graph_profile_or_503(vector_store_attrs, principal, vector_store_id)
    graphrag_enabled = _graphrag_enabled_for_vector_store(vector_store_attrs, query_planner_profile_id, cell_profile=cell_profile)
    requested_lens_id = req.lens
    graph_coverage: dict[str, Any] | None = None
    search_lens: dict[str, Any] | None = None
    if requested_lens_id:
        if normalize_search_lens_id(requested_lens_id) != DEFAULT_SEARCH_LENS_ID and graphrag_enabled:
            graph_coverage = _graph_coverage_for_vector_store(db, principal, vector_store_id)
        try:
            search_lens = resolve_search_lens(
                requested_lens_id,
                vector_store_attrs,
                query_planner_profile_id=query_planner_profile_id,
                graph_enabled=graphrag_enabled,
                graph_coverage=graph_coverage,
            )
            search_lens_relation_types(search_lens["id"], req.inputs)
        except ValueError as exc:
            raise OpenAICompatError(str(exc)) from exc
    else:
        search_lens = resolve_search_lens(
            DEFAULT_SEARCH_LENS_ID,
            vector_store_attrs,
            query_planner_profile_id=query_planner_profile_id,
            graph_enabled=graphrag_enabled,
            graph_coverage=None,
        )
    search_kwargs = openai_search_options_to_search_request_kwargs(req)
    search_query_input = search_query_with_lens_inputs(req.query, (search_lens or {}).get("id"), req.inputs)
    raw_queries = search_query_input if isinstance(search_query_input, list) else [search_query_input]
    query_plans = [
        plan_query(query, rewrite_query=req.rewrite_query, profile_id=query_planner_profile_id)
        for query in raw_queries
    ]
    effective_search_query = (
        query_plans[0].effective_query
        if isinstance(req.query, str)
        else [query_plan.effective_query for query_plan in query_plans]
    )
    base_filters = dict(search_kwargs.pop('filters') or {})
    base_filters['vector_store_id'] = vector_store_id
    search_jobs = [
        (subquery, merge_query_filters(base_filters, query_plan.filters))
        for query_plan in query_plans
        for subquery in query_plan.subqueries
    ]
    subqueries = [subquery for subquery, _filters in search_jobs]
    search_kwargs.pop('query', None)
    legal_exact_diversity = _legal_exact_document_diversity_enabled(query_planner_profile_id, query_plans)
    page_size = req.top_k or req.max_num_results
    page_offset = vector_store_search_next_page_offset(req.next_page)
    search_fetch_limit = page_offset + page_size + 1
    if legal_exact_diversity:
        search_fetch_limit = max(search_fetch_limit, page_offset + max(page_size * 5, 50) + 1)
    search_kwargs['top_k'] = search_fetch_limit
    metadata = dict(search_kwargs.pop('search_metadata') or {})
    compat_meta = dict(metadata.get('openai_compat') or {})
    compat_meta.update({
        'effective_query': effective_search_query,
        'subqueries': subqueries,
        'rewritten': any(query_plan.rewritten for query_plan in query_plans),
        'query_planner_profile_id': query_planner_profile_id,
        'planned_filters': [query_plan.filters for query_plan in query_plans],
        'legal_exact_document_diversity': legal_exact_diversity,
        'search_lens': {'id': search_lens.get('id'), 'inputs': req.inputs or {}} if search_lens else None,
        'search_fetch_limit': search_fetch_limit,
        'page_offset': page_offset,
    })
    metadata['openai_compat'] = compat_meta
    result_lists = []
    for subquery, filters in search_jobs:
        result = await retrieval.search(db, principal, SearchRequest(vector_store_id=vector_store_id, filters=filters, query=subquery, search_metadata=metadata, **search_kwargs))
        result_lists.append(result.results)
    chunks = merge_chunk_results(result_lists, search_fetch_limit)
    chunks = apply_openai_ranking_options(req, chunks, limit=search_fetch_limit)
    if legal_exact_diversity:
        chunks = _document_diversified_chunks(chunks)
    inferred_graph_lens = False
    default_search_lens = search_lens
    if (
        not requested_lens_id
        and corpus_kind == KSCOURTS_CORPUS_KIND
        and graphrag_enabled
        and _query_has_kscourts_graphrag_intent(search_query_input)
    ):
        graph_coverage = _graph_coverage_for_vector_store(db, principal, vector_store_id)
        try:
            search_lens = resolve_search_lens(
                "court_citator",
                vector_store_attrs,
                query_planner_profile_id=query_planner_profile_id,
                graph_enabled=graphrag_enabled,
                graph_coverage=graph_coverage,
            )
            inferred_graph_lens = True
        except ValueError:
            search_lens = default_search_lens
    graph_relation_types = ()
    if search_lens and search_lens.get("requires_graph"):
        try:
            graph_relation_types = search_lens_relation_types(search_lens["id"], req.inputs)
        except ValueError as exc:
            raise OpenAICompatError(str(exc)) from exc
    graph_lens = search_lens if search_lens and search_lens.get("requires_graph") else None
    graph_force = bool(requested_lens_id and graph_lens)
    graph_metadata_by_document_id: dict[str, dict[str, Any]] = {}
    graph_metadata_by_chunk_id: dict[str, dict[str, Any]] = {}
    graph_summary: dict[str, Any] | None = None
    if graph_lens and corpus_kind == GRANT_CORPUS_KIND and cell_profile:
        expansion_limit = cell_profile.max_expansions
        if req.graph_expansion_limit is not None:
            expansion_limit = min(expansion_limit, req.graph_expansion_limit)
        try:
            additions, graph_metadata_by_chunk_id, graph_summary = expand_grant_graph(
                db, principal, vector_store_id, chunks,
                filters=base_filters, relation_types=graph_relation_types,
                limit=expansion_limit, hydrate=retrieval._hydrate_and_acl,
            )
        except ValueError as exc:
            raise OpenAICompatError(str(exc)) from exc
        graph_summary['cell_profile_id'] = cell_profile.profile_id
        chunks = _interleave_graph_expansion_chunks(chunks, additions)
    elif graph_lens and corpus_kind == TOPEKA_CORPUS_KIND:
        chunks, graph_metadata_by_document_id, graph_metadata_by_chunk_id, graph_summary = _apply_topeka_municipal_graphrag_expansion(
            db,
            principal,
            vector_store_id,
            chunks,
            enabled=graphrag_enabled,
            query=search_query_input,
            force=graph_force,
            lens=graph_lens,
            inputs=req.inputs,
            relation_types=graph_relation_types,
            graph_coverage=graph_lens.get("coverage"),
            max_expansions=req.graph_expansion_limit,
        )
    elif corpus_kind == KSCOURTS_CORPUS_KIND:
        chunks, graph_metadata_by_document_id, graph_metadata_by_chunk_id, graph_summary = _apply_kscourts_graphrag_expansion(
            db,
            principal,
            vector_store_id,
            chunks,
            enabled=graphrag_enabled,
            query=search_query_input,
            force=graph_force,
            lens=graph_lens,
            relation_types=graph_relation_types,
            graph_coverage=graph_lens.get("coverage") if graph_lens else graph_coverage,
            max_expansions=req.graph_expansion_limit,
        )
    chunks, next_page = vector_store_search_page_window(req, chunks)
    file_lookup = _vector_store_file_lookup(db, principal, vector_store_id, [ch.document_id for ch in chunks])
    page = vector_store_search_results_page(req, chunks, file_lookup, search_query=effective_search_query, next_page=next_page)
    if search_lens:
        page["search_lens"] = {
            "id": search_lens["id"],
            "status": search_lens["status"],
            "source": "explicit" if requested_lens_id else ("inferred" if inferred_graph_lens else "default"),
            "inputs": req.inputs or {},
            "requires_graph": bool(search_lens.get("requires_graph")),
        }
    if graph_summary is not None:
        page = _annotate_openai_search_page_with_graph(
            page,
            graph_metadata_by_document_id,
            graph_metadata_by_chunk_id,
            graph_summary,
        )
    return page


configure_expert_search_executor(_openai_vector_store_search_page)


@app.post(
    '/v1/vector_stores/{vector_store_id}/search',
    response_model=OpenAIVectorStoreSearchResultsPage,
    response_model_exclude_unset=True,
)
async def vector_store_search(vector_store_id: str, req: OpenAIVectorStoreSearchRequest, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'retrieval:read')
    enforce_rate_limit(db, principal, 'vector_stores.search')
    try:
        page = await _openai_vector_store_search_page(vector_store_id, req, principal, db)
    except OpenAICompatError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return page


def _openai_response_not_found(response_id: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f'Response not found: {response_id}')


def _get_openai_response_row(db: Session, principal: Principal, response_id: str):
    row = db.execute(text('''
        SELECT id, response, input_items, deleted_at
        FROM openai_responses
        WHERE id=:id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
        LIMIT 1
    '''), {'id': response_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id}).mappings().first()
    if not row or row['deleted_at'] is not None:
        raise _openai_response_not_found(response_id)
    return row


def _store_openai_response(
    db: Session,
    principal: Principal,
    *,
    response_payload: dict[str, Any],
    input_items: list[dict[str, Any]],
    request_payload: dict[str, Any],
) -> None:
    db.execute(jsonb_text('''
        INSERT INTO openai_responses(
          id, tenant_id, business_instance_id, user_id, api_key_id, response,
          input_items, request, status
        )
        VALUES (
          :id, :tenant_id, :biz_id, :user_id, :api_key_id, CAST(:response AS jsonb),
          CAST(:input_items AS jsonb), CAST(:request AS jsonb), :status
        )
    ''', 'response', 'input_items', 'request'), {
        'id': response_payload['id'],
        'tenant_id': principal.tenant_id,
        'biz_id': principal.business_instance_id,
        'user_id': principal.user_id,
        'api_key_id': principal.api_key_id,
        'response': jsonb_param(response_payload),
        'input_items': jsonb_param(input_items),
        'request': jsonb_param(request_payload),
        'status': response_payload.get('status', 'completed'),
    })


def _response_stream_requested(value: Any) -> bool:
    if value in (None, False):
        return False
    if value is True:
        return True
    raise HTTPException(status_code=422, detail='Responses stream must be a boolean')


def _response_include_obfuscation_requested(value: Any) -> bool:
    if value is None:
        return True
    if value is True or value is False:
        return value
    raise HTTPException(status_code=422, detail='Responses include_obfuscation must be a boolean')


def _response_stream_options_include_obfuscation(payload: dict[str, Any]) -> bool:
    stream_options = payload.get('stream_options')
    if stream_options is None:
        return True
    if not isinstance(stream_options, dict):
        raise HTTPException(status_code=422, detail='Responses stream_options must be an object')
    return _response_include_obfuscation_requested(stream_options.get('include_obfuscation'))


def _responses_payload_dict(payload: Any) -> dict[str, Any]:
    if hasattr(payload, 'to_compat_payload'):
        payload = payload.to_compat_payload()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail='Responses payload must be an object')
    return payload


@app.post(
    '/v1/responses',
    response_model=OpenAIResponseObject,
    response_model_exclude_unset=True,
    responses={200: {'content': {'text/event-stream': {}}}},
)
async def create_response(
    payload: OpenAIResponseRequest = Body(default_factory=OpenAIResponseRequest),
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
):
    ensure_scope(principal, 'retrieval:read')
    enforce_rate_limit(db, principal, 'responses.create')
    payload_data = _responses_payload_dict(payload)
    stream_response = _response_stream_requested(payload_data.get('stream'))
    include_obfuscation = _response_stream_options_include_obfuscation(payload_data) if stream_response else True
    idempotency_fingerprint, cached = _check_openai_idempotency(
        db,
        principal,
        idempotency_key,
        route='POST /v1/responses',
        request_payload={'payload': payload_data},
    )
    if cached:
        try:
            ensure_openai_response_citation_integrity(cached)
        except OpenAICompatError as exc:
            raise HTTPException(status_code=500, detail=f'Cached Responses citation integrity check failed: {exc}') from exc
        if stream_response:
            return StreamingResponse(
                openai_response_sse_events(cached, include_obfuscation=include_obfuscation),
                media_type='text/event-stream',
            )
        return cached
    try:
        include_search_results = responses_include_search_results(payload_data.get('include'))
        current_query = extract_responses_input_text(payload_data.get('input'))
        if not current_query:
            raise OpenAICompatError('Responses input must contain query text')
        previous_response_id = payload_data.get('previous_response_id')
        previous_input_items: list[dict[str, Any]] = []
        previous_context = ''
        if previous_response_id is not None:
            if not isinstance(previous_response_id, str) or not previous_response_id.strip():
                raise OpenAICompatError('previous_response_id must be a non-empty string')
            if payload_data.get('conversation') is not None:
                raise OpenAICompatError('previous_response_id cannot be used with conversation')
            previous_row = _get_openai_response_row(db, principal, previous_response_id)
            previous_response = dict(previous_row['response'] or {})
            try:
                ensure_openai_response_citation_integrity(previous_response)
            except OpenAICompatError as exc:
                raise HTTPException(status_code=500, detail=f'Previous Responses citation integrity check failed: {exc}') from exc
            previous_input_items = list(previous_row['input_items'] or [])
            previous_context = responses_previous_context_text(previous_response, previous_input_items)
        query = responses_continuation_query(current_query, previous_context)
        tools = responses_file_search_tools(payload_data.get('tools'))
        if not tools:
            raise OpenAICompatError('Responses compatibility currently requires a file_search tool')
        validate_responses_file_search_tool_choice(payload_data.get('tool_choice'))
        search_pages = []
        response_query_plan = plan_query(query, rewrite_query=True)
        for tool in tools:
            for vector_store_id in tool['vector_store_ids']:
                req = OpenAIVectorStoreSearchRequest.model_validate({
                    'query': query,
                    'lens': tool.get('lens'),
                    'inputs': tool.get('inputs'),
                    'filters': tool.get('filters'),
                    'max_num_results': tool['max_num_results'],
                    'ranking_options': tool.get('ranking_options'),
                    'rewrite_query': True,
                    'include_content': True,
                    'include_metadata': True,
                })
                page = await _openai_vector_store_search_page(vector_store_id, req, principal, db)
                search_pages.append({'vector_store_id': vector_store_id, 'page': page})
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    except OpenAICompatError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    response_id = new_id('resp')
    current_input_items = responses_input_items(payload_data.get('input'), item_id=new_id('msg'))
    input_items = [*previous_input_items, *current_input_items]
    full_response = openai_responses_file_search_response(
        payload={**payload_data, 'store': payload_data.get('store', True)},
        query=query,
        tools=tools,
        search_pages=search_pages,
        response_id=response_id,
        message_id=new_id('msg'),
        file_search_call_id=new_id('fs'),
        created_at=int(time.time()),
        include_search_results=True,
        file_search_queries=response_query_plan.subqueries,
    )
    try:
        ensure_openai_response_citation_integrity(full_response)
    except OpenAICompatError as exc:
        raise HTTPException(status_code=500, detail=f'Responses citation integrity check failed: {exc}') from exc
    response_payload = response_with_file_search_include(full_response, include_search_results=include_search_results)
    try:
        ensure_openai_response_citation_integrity(response_payload)
    except OpenAICompatError as exc:
        raise HTTPException(status_code=500, detail=f'Responses citation integrity check failed: {exc}') from exc
    if full_response.get('store') is not False:
        _store_openai_response(db, principal, response_payload=full_response, input_items=input_items, request_payload=payload_data)
    _store_openai_idempotency(db, principal, idempotency_key, fingerprint=idempotency_fingerprint, response=response_payload)
    db.commit()
    if stream_response:
        return StreamingResponse(
            openai_response_sse_events(response_payload, include_obfuscation=include_obfuscation),
            media_type='text/event-stream',
        )
    return response_payload


@app.post(
    '/v1/responses/input_tokens',
    response_model=OpenAIResponseInputTokensResponse,
    response_model_exclude_unset=True,
)
def count_response_input_tokens(
    payload: OpenAIResponseInputTokensRequest = Body(default_factory=OpenAIResponseInputTokensRequest),
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
):
    ensure_scope(principal, 'retrieval:read')
    enforce_rate_limit(db, principal, 'responses.input_tokens')
    try:
        input_tokens = responses_input_token_count(_responses_payload_dict(payload))
    except OpenAICompatError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {'object': 'response.input_tokens', 'input_tokens': input_tokens}


@app.post(
    '/v1/responses/compact',
    response_model=OpenAIResponseCompactionResponse,
    response_model_exclude_unset=True,
)
def compact_response(
    payload: OpenAIResponseCompactRequest = Body(default_factory=OpenAIResponseCompactRequest),
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
):
    ensure_scope(principal, 'retrieval:read')
    enforce_rate_limit(db, principal, 'responses.compact')
    try:
        return responses_compact_response(
            payload=_responses_payload_dict(payload),
            response_id=new_id('resp'),
            compaction_id=new_id('cmp'),
            item_id=new_id('msg'),
            created_at=int(time.time()),
        )
    except OpenAICompatError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get(
    '/v1/responses/{response_id}',
    response_model=OpenAIResponseObject,
    response_model_exclude_unset=True,
    responses={200: {'content': {'text/event-stream': {}}}},
)
def get_response(
    response_id: str,
    include: Annotated[list[str] | None, Query()] = None,
    stream: Annotated[bool | None, Query()] = False,
    starting_after: Annotated[int | None, Query(ge=0)] = None,
    include_obfuscation: Annotated[bool | None, Query()] = True,
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
):
    ensure_scope(principal, 'retrieval:read')
    enforce_rate_limit(db, principal, 'responses.retrieve')
    try:
        include_search_results = responses_include_search_results(include)
    except OpenAICompatError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    row = _get_openai_response_row(db, principal, response_id)
    response_payload = response_with_file_search_include(dict(row['response'] or {}), include_search_results=include_search_results)
    try:
        ensure_openai_response_citation_integrity(response_payload)
    except OpenAICompatError as exc:
        raise HTTPException(status_code=500, detail=f'Stored Responses citation integrity check failed: {exc}') from exc
    if stream is True:
        return StreamingResponse(
            openai_response_sse_events(
                response_payload,
                starting_after=starting_after,
                include_obfuscation=_response_include_obfuscation_requested(include_obfuscation),
            ),
            media_type='text/event-stream',
        )
    return response_payload


@app.post(
    '/v1/responses/{response_id}/cancel',
    response_model=OpenAIResponseObject,
    response_model_exclude_unset=True,
)
def cancel_response(
    response_id: str,
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
):
    ensure_scope(principal, 'retrieval:read')
    enforce_rate_limit(db, principal, 'responses.cancel')
    idempotency_fingerprint, cached = _check_openai_idempotency(
        db,
        principal,
        idempotency_key,
        route='POST /v1/responses/{response_id}/cancel',
        request_payload={'response_id': response_id},
    )
    if cached:
        return cached
    row = _get_openai_response_row(db, principal, response_id)
    response_payload = dict(row['response'] or {})
    if response_payload.get('background') is not True:
        raise HTTPException(status_code=400, detail='Only background Responses can be cancelled')
    cancelled_payload = dict(response_payload)
    cancelled_payload['status'] = 'cancelled'
    output_items = []
    for item in cancelled_payload.get('output') or []:
        if not isinstance(item, dict):
            output_items.append(item)
            continue
        updated_item = dict(item)
        if updated_item.get('status') == 'in_progress':
            updated_item['status'] = 'cancelled'
        output_items.append(updated_item)
    if 'output' in cancelled_payload:
        cancelled_payload['output'] = output_items
    try:
        ensure_openai_response_citation_integrity(cancelled_payload)
    except OpenAICompatError as exc:
        raise HTTPException(status_code=500, detail=f'Responses citation integrity check failed: {exc}') from exc
    db.execute(jsonb_text('''
        UPDATE openai_responses
        SET response=CAST(:response AS jsonb), status='cancelled', updated_at=now()
        WHERE id=:id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
    ''', 'response'), {
        'response': jsonb_param(cancelled_payload),
        'id': row['id'],
        'tenant_id': principal.tenant_id,
        'biz_id': principal.business_instance_id,
    })
    _store_openai_idempotency(db, principal, idempotency_key, fingerprint=idempotency_fingerprint, response=cancelled_payload)
    db.commit()
    return cancelled_payload


@app.delete(
    '/v1/responses/{response_id}',
    response_model=OpenAIResponseDeletedResponse,
    response_model_exclude_unset=True,
)
def delete_response(
    response_id: str,
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
):
    ensure_scope(principal, 'retrieval:read')
    enforce_rate_limit(db, principal, 'responses.delete')
    idempotency_fingerprint, cached = _check_openai_idempotency(
        db,
        principal,
        idempotency_key,
        route='DELETE /v1/responses/{response_id}',
        request_payload={'response_id': response_id},
    )
    if cached:
        return cached
    row = _get_openai_response_row(db, principal, response_id)
    db.execute(text('''
        UPDATE openai_responses
        SET deleted_at=now(), updated_at=now(), status='deleted'
        WHERE id=:id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
    '''), {'id': row['id'], 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id})
    response = {'id': response_id, 'object': 'response', 'deleted': True}
    _store_openai_idempotency(db, principal, idempotency_key, fingerprint=idempotency_fingerprint, response=response)
    db.commit()
    return response


@app.get(
    '/v1/responses/{response_id}/input_items',
    response_model=OpenAIResponseInputItemsPage,
    response_model_exclude_unset=True,
)
def list_response_input_items(
    response_id: str,
    limit: int = 20,
    order: str = Query(default='desc', pattern='^(asc|desc)$'),
    after: str | None = None,
    include: list[str] | None = Query(default=None),
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
):
    ensure_scope(principal, 'retrieval:read')
    enforce_rate_limit(db, principal, 'responses.input_items')
    try:
        responses_include_search_results(include)
    except OpenAICompatError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    row = _get_openai_response_row(db, principal, response_id)
    return responses_input_items_page(list(row['input_items'] or []), limit=limit, order=order, after=after)


def _vector_store_file_lookup(db: Session, principal: Principal, vector_store_id: str, document_ids: list[str]) -> dict[str, dict[str, Any]]:
    ids = sorted({doc_id for doc_id in document_ids if doc_id})
    if not ids:
        return {}
    rows = db.execute(text('''
        SELECT f.document_id,
               coalesce(
                 f.attributes->>'attached_from_file_id',
                 dv.metadata #>> '{attributes,_openai_file_id}',
                 f.document_id,
                 f.id
               ) AS file_id,
               d.title, d.filename, d.source_uri, f.attributes
        FROM vector_store_files f
        JOIN documents d
          ON d.id=f.document_id
         AND d.tenant_id=f.tenant_id
         AND d.business_instance_id=f.business_instance_id
        LEFT JOIN document_versions dv
          ON dv.id=d.current_version_id
         AND dv.document_id=d.id
         AND dv.tenant_id=d.tenant_id
         AND dv.business_instance_id=d.business_instance_id
        WHERE f.tenant_id=:tenant_id AND f.business_instance_id=:biz_id
          AND f.vector_store_id=:vs_id AND f.status <> 'cancelled'
          AND f.document_id = ANY(:document_ids)
        ORDER BY f.created_at DESC
    '''), {'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'vs_id': vector_store_id, 'document_ids': ids}).mappings().all()
    lookup: dict[str, dict[str, Any]] = {}
    for r in rows:
        if r['document_id'] in lookup:
            continue
        lookup[r['document_id']] = {
            'file_id': r['file_id'],
            'title': r['title'],
            'filename': r['filename'],
            'source_uri': r['source_uri'],
            'attributes': _public_vector_store_file_attributes(r['attributes']),
        }
    return lookup


@app.get(
    '/v1/vector_stores/{vector_store_id}/files',
    response_model=OpenAIVectorStoreFileListResponse,
)
def list_vector_store_files(
    vector_store_id: str,
    limit: int = 20,
    order: str = Query(default='desc', pattern='^(asc|desc)$'),
    after: str | None = None,
    before: str | None = None,
    status_filter: str | None = Query(default=None, alias='filter'),
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
):
    ensure_scope(principal, 'vector_stores:read')
    enforce_rate_limit(db, principal, 'vector_store_files.list')
    rows, has_more = _list_vector_store_file_rows(
        db,
        principal,
        vector_store_id,
        limit=limit,
        order=order,
        after=after,
        before=before,
        status_filter=status_filter,
    )
    data = [_openai_vector_store_file_payload(r) for r in rows]
    return _list_response(data, has_more)


@app.get(
    '/v1/vector_stores/{vector_store_id}/files/{file_id}',
    response_model=OpenAIVectorStoreFile,
    response_model_exclude_none=True,
)
def get_vector_store_file(vector_store_id: str, file_id: str, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'vector_stores:read')
    enforce_rate_limit(db, principal, 'vector_store_files.retrieve')
    r = _vector_store_file_row(db, principal, vector_store_id, file_id)
    if not r:
        raise HTTPException(status_code=404, detail='Vector store file not found')
    return _openai_vector_store_file_payload(r)


@app.patch(
    '/v1/vector_stores/{vector_store_id}/files/{file_id}',
    response_model=OpenAIVectorStoreFile,
    response_model_exclude_none=True,
)
@app.post(
    '/v1/vector_stores/{vector_store_id}/files/{file_id}',
    response_model=OpenAIVectorStoreFile,
    response_model_exclude_none=True,
)
def update_vector_store_file(
    vector_store_id: str,
    file_id: str,
    patch: dict[str, Any] = Body(default_factory=dict),
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
):
    ensure_scope(principal, 'vector_stores:write')
    enforce_rate_limit(db, principal, 'vector_store_files.update')
    idempotency_fingerprint, cached = _check_openai_idempotency(
        db,
        principal,
        idempotency_key,
        route='POST/PATCH /v1/vector_stores/{vector_store_id}/files/{file_id}',
        request_payload={'vector_store_id': vector_store_id, 'file_id': file_id, 'patch': patch},
    )
    if cached:
        return cached
    row = _vector_store_file_row(db, principal, vector_store_id, file_id)
    if not row:
        raise HTTPException(status_code=404, detail='Vector store file not found')
    attrs = _vector_store_file_patch_attributes(row, patch)
    result = db.execute(jsonb_text('''
        UPDATE vector_store_files SET attributes=CAST(:attrs AS jsonb)
        WHERE id=:id AND vector_store_id=:vs_id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
    ''', 'attrs'), {'attrs': jsonb_param(attrs), 'id': row['id'], 'vs_id': vector_store_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id})
    if not result.rowcount:
        raise HTTPException(status_code=404, detail='Vector store file not found')
    updated = _vector_store_file_row(db, principal, vector_store_id, row['id'])
    if not updated:
        raise HTTPException(status_code=404, detail='Vector store file not found')
    payload = _openai_vector_store_file_payload(updated)
    _store_openai_idempotency(db, principal, idempotency_key, fingerprint=idempotency_fingerprint, response=payload)
    db.commit()
    return payload


@app.delete(
    '/v1/vector_stores/{vector_store_id}/files/{file_id}',
    response_model=OpenAIVectorStoreFileDeletedResponse,
)
def delete_vector_store_file(
    vector_store_id: str,
    file_id: str,
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
):
    ensure_scope(principal, ['vector_stores:write', 'vector_store_files:delete'], any_of=True)
    enforce_rate_limit(db, principal, 'vector_store_files.delete')
    idempotency_fingerprint, cached = _check_openai_idempotency(
        db,
        principal,
        idempotency_key,
        route='DELETE /v1/vector_stores/{vector_store_id}/files/{file_id}',
        request_payload={'vector_store_id': vector_store_id, 'file_id': file_id},
    )
    if cached:
        return cached
    existing = _vector_store_file_row(db, principal, vector_store_id, file_id)
    if not existing:
        raise HTTPException(status_code=404, detail='Vector store file not found')
    row = db.execute(text('''
        UPDATE vector_store_files SET status='cancelled'
        WHERE id=:id AND vector_store_id=:vs_id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
        RETURNING document_id
    '''), {'id': existing['id'], 'vs_id': vector_store_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail='Vector store file not found')
    if row['document_id']:
        db.execute(text('''
            UPDATE chunks
            SET active=false, deleted_at=now(), dense_index_status='delete_queued', sparse_index_status='delete_queued'
            WHERE document_id=:doc_id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
        '''), {'doc_id': row['document_id'], 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id})
        enqueue_purge_stale_vectors(db, principal, document_id=row['document_id'], reason='vector_store_file_deleted')
    response = {'id': existing['public_file_id'], 'object': 'vector_store.file.deleted', 'deleted': True}
    _store_openai_idempotency(db, principal, idempotency_key, fingerprint=idempotency_fingerprint, response=response)
    db.commit()
    return response


@app.get(
    '/v1/vector_stores/{vector_store_id}/files/{file_id}/content',
    response_model=OpenAIVectorStoreFileContentResponse,
    response_model_exclude_none=True,
)
def get_vector_store_file_content(vector_store_id: str, file_id: str, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'vector_stores:read')
    enforce_rate_limit(db, principal, 'vector_store_files.content')
    existing = _vector_store_file_row(db, principal, vector_store_id, file_id)
    if not existing:
        raise HTTPException(status_code=404, detail='Vector store file not found')
    rows = db.execute(text('''
        SELECT c.ordinal, c.text, c.heading_path, c.page_start, c.page_end
        FROM vector_store_files f JOIN chunks c ON c.document_id=f.document_id
        WHERE f.id=:file_id AND f.vector_store_id=:vs_id AND f.tenant_id=:tenant_id AND f.business_instance_id=:biz_id
          AND c.active=true AND c.security_level <= :max_lvl
        ORDER BY c.ordinal ASC
    '''), {'file_id': existing['id'], 'vs_id': vector_store_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'max_lvl': principal.max_security_level}).mappings().all()
    if not rows:
        raise HTTPException(status_code=404, detail='No readable content found for file')
    return {'object': 'vector_store.file_content', 'data': [{'type': 'text', 'text': r['text'], 'heading_path': list(r['heading_path'] or []), 'page_start': r['page_start'], 'page_end': r['page_end']} for r in rows]}


@app.post(
    '/v1/vector_stores/{vector_store_id}/file_batches',
    response_model=OpenAIVectorStoreFileBatch,
    response_model_exclude_none=True,
)
async def create_file_batch(
    vector_store_id: str,
    payload: dict[str, Any] = Body(default_factory=dict),
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
):
    ensure_scope(principal, 'documents:write')
    enforce_rate_limit(db, principal, 'file_batches.create')
    _enforce_vector_store_file_add_rate_limit(db, principal, vector_store_id)
    idempotency_fingerprint, cached = _check_openai_idempotency(
        db,
        principal,
        idempotency_key,
        route='POST /v1/vector_stores/{vector_store_id}/file_batches',
        request_payload={'vector_store_id': vector_store_id, 'payload': payload},
    )
    if cached:
        return cached
    _refresh_vector_store_activity_or_404(db, principal, vector_store_id)
    parts = _openai_file_batch_request_parts(payload)
    file_refs = parts['file_refs']
    inline_files = parts['inline_files']
    file_ids = parts['file_ids']
    batch_id = new_id('vsfb')
    file_counts = {
        'in_progress': len(inline_files),
        'completed': len(file_refs) + len(file_ids),
        'failed': 0,
        'cancelled': 0,
        'total': parts['total'],
    }
    db.execute(jsonb_text('''
        INSERT INTO file_batches(id, tenant_id, business_instance_id, vector_store_id, status, file_counts)
        VALUES (:id, :tenant_id, :biz_id, :vs_id, :status, CAST(:file_counts AS jsonb))
    ''', 'file_counts'), {'id': batch_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'vs_id': vector_store_id, 'status': 'in_progress' if inline_files else 'completed', 'file_counts': jsonb_param(file_counts)})
    await _attach_existing_document_ids_to_vector_store(
        db,
        principal,
        vector_store_id,
        file_ids,
        attributes=parts['file_id_attributes'],
        file_batch_id=batch_id,
    )
    for ref in file_refs:
        await _attach_existing_document_ids_to_vector_store(
            db,
            principal,
            vector_store_id,
            [ref['file_id']],
            attributes=ref['attributes'],
            file_batch_id=batch_id,
        )
    for raw in inline_files:
        req = DocumentIngestRequest.model_validate({**raw, 'vector_store_id': vector_store_id})
        ingestion.enqueue(db, principal, req, file_batch_id=batch_id)
    row = _get_file_batch_row(db, principal, vector_store_id, batch_id)
    if not row:
        raise HTTPException(status_code=500, detail='File batch could not be retrieved after creation')
    response = _openai_file_batch_payload(row)
    _store_openai_idempotency(db, principal, idempotency_key, fingerprint=idempotency_fingerprint, response=response)
    db.commit()
    return response


@app.get(
    '/v1/vector_stores/{vector_store_id}/file_batches/{batch_id}',
    response_model=OpenAIVectorStoreFileBatch,
    response_model_exclude_none=True,
)
def get_file_batch(vector_store_id: str, batch_id: str, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'vector_stores:read')
    enforce_rate_limit(db, principal, 'file_batches.retrieve')
    r = _get_file_batch_row(db, principal, vector_store_id, batch_id)
    if not r:
        raise HTTPException(status_code=404, detail='File batch not found')
    return _openai_file_batch_payload(r)


@app.post(
    '/v1/vector_stores/{vector_store_id}/file_batches/{batch_id}/cancel',
    response_model=OpenAIVectorStoreFileBatch,
    response_model_exclude_none=True,
)
def cancel_file_batch(
    vector_store_id: str,
    batch_id: str,
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
    idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'),
):
    ensure_scope(principal, ['vector_stores:write', 'documents:write'], any_of=True)
    enforce_rate_limit(db, principal, 'file_batches.cancel')
    idempotency_fingerprint, cached = _check_openai_idempotency(
        db,
        principal,
        idempotency_key,
        route='POST /v1/vector_stores/{vector_store_id}/file_batches/{batch_id}/cancel',
        request_payload={'vector_store_id': vector_store_id, 'batch_id': batch_id},
    )
    if cached:
        return cached
    db.execute(text('''
        UPDATE ingestion_jobs SET status='cancelled', updated_at=now()
        WHERE tenant_id=:tenant_id AND business_instance_id=:biz_id AND status='queued'
          AND (
            payload->>'file_batch_id'=:batch_id
            OR payload #>> '{document,attributes,_file_batch_id}' = :batch_id
          )
    '''), {'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'batch_id': batch_id})
    row = db.execute(text('''
        UPDATE file_batches SET status='cancelled', completed_at=now(),
            file_counts = jsonb_set(
                jsonb_set(
                    file_counts,
                    '{cancelled}',
                    ((coalesce((file_counts->>'cancelled')::int,0) + coalesce((file_counts->>'in_progress')::int,0))::text)::jsonb
                ),
                '{in_progress}',
                '0'::jsonb
            )
        WHERE id=:id AND vector_store_id=:vs_id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
        RETURNING id, vector_store_id, status, file_counts,
                  extract(epoch from created_at)::bigint AS created_at,
                  extract(epoch from completed_at)::bigint AS completed_at
    '''), {'id': batch_id, 'vs_id': vector_store_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail='File batch not found')
    payload = _openai_file_batch_payload(row)
    _store_openai_idempotency(db, principal, idempotency_key, fingerprint=idempotency_fingerprint, response=payload)
    db.commit()
    return payload


@app.get(
    '/v1/vector_stores/{vector_store_id}/file_batches/{batch_id}/files',
    response_model=OpenAIVectorStoreFileBatchFilesPage,
)
def list_file_batch_files(
    vector_store_id: str,
    batch_id: str,
    limit: int = 20,
    order: str = Query(default='desc', pattern='^(asc|desc)$'),
    after: str | None = None,
    before: str | None = None,
    status_filter: str | None = Query(default=None, alias='filter'),
    principal: Principal = Depends(get_request_principal),
    db: Session = Depends(db_for_principal),
):
    ensure_scope(principal, 'vector_stores:read')
    enforce_rate_limit(db, principal, 'file_batches.files.list')
    rows, has_more = _list_vector_store_file_rows(
        db,
        principal,
        vector_store_id,
        limit=limit,
        order=order,
        after=after,
        before=before,
        status_filter=status_filter,
        batch_id=batch_id,
    )
    data = [_openai_vector_store_file_payload(r) for r in rows]
    return _list_response(data, has_more)
