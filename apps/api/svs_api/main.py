from __future__ import annotations
from hashlib import sha256
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
from svs_common.security import principal_from_dev_headers
from svs_common.schemas import (
    Principal, VectorStoreCreateRequest, SearchRequest, ContextPackRequest, RetrievalAnswerRequest, DocumentIngestRequest,
    VectorStoreDeletedResponse, VectorStoreListResponse, VectorStoreResponse,
    IngestionPreviewRequest, ModelEndpointRequest, ModelEndpointResponse,
    BakeoffRunRequest, ReindexRequest, OpenAIFile, OpenAIFileDeletedResponse,
    OpenAIFileListResponse, OpenAIVectorStoreFile, OpenAIVectorStoreFileBatch,
    OpenAIVectorStoreFileBatchFilesPage, OpenAIVectorStoreFileContentResponse,
    OpenAIVectorStoreFileDeletedResponse, OpenAIVectorStoreFileListResponse,
    OpenAIVectorStoreSearchRequest, OpenAIVectorStoreSearchResultsPage,
    VectorStoreUpdateRequest,
    OpenAIResponseCompactRequest, OpenAIResponseCompactionResponse, OpenAIResponseDeletedResponse,
    OpenAIResponseInputItemsPage, OpenAIResponseInputTokensRequest, OpenAIResponseInputTokensResponse,
    OpenAIAdminApiKey, OpenAIAdminApiKeyCreateRequest, OpenAIAdminApiKeyCreateResponse,
    OpenAIAdminApiKeyDeletedResponse, OpenAIAdminApiKeyListResponse,
    OpenAIProjectApiKey, OpenAIProjectApiKeyDeletedResponse, OpenAIProjectApiKeyListResponse,
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
from svs_common.query_planner import plan_query
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


def custom_openapi() -> dict[str, Any]:
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    _install_openai_response_stream_openapi_contract(openapi_schema)
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

    attrs = marker_attribute_summary(
        original_filename=file.filename,
        pdf_bytes=content_bytes,
        output=output,
        job_id=job_ids[-1] if job_ids else None,
        source_object_key=source_key,
    )
    return DocumentIngestRequest(
        vector_store_id=vector_store_id,
        knowledge_base_id=knowledge_base_id,
        title=title or file.filename or 'uploaded PDF',
        filename=markdown_filename_for_pdf(file.filename),
        mime_type='text/markdown',
        content=markdown,
        mode='pdf_markdown_external_v1',
        source_uri=f'object://{source_key}',
        attributes=attrs,
        security_level=security_level,
        source_trust='external_pdf_parser',
    )


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


@app.get('/healthz')
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


@app.get('/readyz')
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


@app.get('/metrics', response_class=PlainTextResponse)
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


@app.get('/v1/files/{file_id}/content', response_class=PlainTextResponse)
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
    return PlainTextResponse(content, media_type=row['mime_type'] or 'text/plain')


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


@app.get('/api/v1/vectorization/modes')
def list_modes():
    return {'modes': vectorization_modes()}


@app.get('/api/v1/models/registry')
def list_models():
    return model_registry()


@app.get('/api/v1/retrieval/profiles')
def list_profiles():
    return {'profiles': retrieval_profiles()}


@app.post('/api/v1/ingestion/preview')
def ingestion_preview(req: IngestionPreviewRequest, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, ['documents:write', 'retrieval:read'], any_of=True)
    enforce_rate_limit(db, principal, 'ingestion.preview')
    plan = build_ingestion_plan(principal, req)
    if req.persist:
        plan = persist_ingestion_plan(db, principal, req, plan)
        db.commit()
    return plan


@app.post('/api/v1/documents/ingest')
async def ingest_document(req: DocumentIngestRequest, idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'), principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'documents:write')
    enforce_rate_limit(db, principal, 'documents.ingest')
    fp = stable_hash(req.model_dump())
    if cached := check_idempotency(db, principal, idempotency_key, fp):
        return cached
    result = await ingest_or_enqueue(req, principal, db)
    payload = result.model_dump()
    store_idempotency(db, principal, idempotency_key, fp, payload)
    db.commit()
    return payload


@app.post('/api/v1/documents/upload')
async def upload_document(file: UploadFile = File(...), title: str | None = Form(default=None), mode: str = Form(default='auto_detect_v1'), vector_store_id: str | None = Form(default=None), knowledge_base_id: str | None = Form(default=None), security_level: int = Form(default=1), principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'documents:write')
    enforce_rate_limit(db, principal, 'documents.upload')
    content_bytes = await file.read()
    if len(content_bytes) > settings.svs_request_body_limit_bytes:
        raise HTTPException(status_code=413, detail='Uploaded document exceeds configured body limit')
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
        )
    else:
        content = content_bytes.decode('utf-8', errors='replace')
        req = DocumentIngestRequest(vector_store_id=vector_store_id, knowledge_base_id=knowledge_base_id, title=title or file.filename or 'uploaded document', filename=file.filename, mime_type=file.content_type, content=content, mode=mode, security_level=security_level)
    return await ingest_or_enqueue(req, principal, db)


@app.get('/api/v1/jobs')
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


@app.get('/api/v1/jobs/{job_id}')
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


@app.post('/api/v1/jobs/{job_id}/retry')
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


@app.post('/api/v1/retrieval/search')
async def search(req: SearchRequest, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'retrieval:read')
    enforce_rate_limit(db, principal, 'retrieval.search')
    if req.vector_store_id:
        _refresh_vector_store_activity_or_404(db, principal, req.vector_store_id)
    result = await retrieval.search(db, principal, req)
    db.commit()
    return result


@app.post('/api/v1/retrieval/context-pack')
async def context_pack(req: ContextPackRequest, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'retrieval:read')
    enforce_rate_limit(db, principal, 'retrieval.context_pack')
    if req.vector_store_id:
        _refresh_vector_store_activity_or_404(db, principal, req.vector_store_id)
    result = await retrieval.context_pack(db, principal, req)
    db.commit()
    return result


@app.post('/api/v1/retrieval/answer')
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


@app.get('/api/v1/model-endpoints')
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


@app.post('/api/v1/bakeoffs')
def create_bakeoff(req: BakeoffRunRequest, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, ['evals:write', 'models:write'], any_of=True)
    result = bakeoff.create_run(db, principal, req)
    db.commit()
    return result


@app.get('/api/v1/bakeoffs')
def list_bakeoffs(limit: int = 20, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, ['evals:read', 'evals:write', 'models:write'], any_of=True)
    data, has_more = bakeoff.list_runs(db, principal, limit=limit)
    return _list_response(data, has_more)


@app.get('/api/v1/bakeoffs/{run_id}')
def get_bakeoff(run_id: str, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, ['evals:read', 'evals:write', 'models:write'], any_of=True)
    result = bakeoff.get_run(db, principal, run_id)
    if not result:
        raise HTTPException(status_code=404, detail='Bakeoff run not found')
    return result


@app.post('/api/v1/maintenance/expire-vector-stores')
def expire_vector_stores(principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'maintenance:write')
    result = maintenance.sweep_expired_vector_stores(db, principal)
    db.commit()
    return result


@app.post('/api/v1/maintenance/reindex')
async def reindex(req: ReindexRequest, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'maintenance:write')
    result = await maintenance.reindex_chunks(db, principal, req)
    db.commit()
    return result


@app.get('/api/v1/admin/session')
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
          AND (:selected_business_id IS NULL
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


@app.get('/api/v1/admin/usage')
def usage(limit: int = 100, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, ['admin:read', 'usage:read'], any_of=True)
    rows = db.execute(text('''
        SELECT event_type, quantity, unit, provider, model, cost_estimate_usd, metadata, extract(epoch from created_at)::bigint created_at
        FROM usage_events WHERE tenant_id=:tenant_id AND business_instance_id=:biz_id
        ORDER BY created_at DESC LIMIT :limit
    '''), {'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'limit': min(max(limit, 1), 500)}).mappings().all()
    return _list_response([dict(r) for r in rows])


@app.get('/api/v1/admin/audit-events')
def audit_events(limit: int = 100, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, ['admin:read', 'audit:read'], any_of=True)
    rows = db.execute(text('''
        SELECT id, event_type, action, resource_type, resource_id, security_level, allowed, metadata, extract(epoch from created_at)::bigint created_at
        FROM audit_events WHERE tenant_id=:tenant_id AND business_instance_id=:biz_id
        ORDER BY created_at DESC LIMIT :limit
    '''), {'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'limit': min(max(limit, 1), 500)}).mappings().all()
    return _list_response([dict(r) for r in rows])


@app.post('/api/v1/admin/tenants')
def create_tenant(name: str, slug: str, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'admin:write')
    tenant_id = new_id('ten')
    db.execute(text("SELECT set_config('svs.tenant_id', :tenant_id, true)"), {'tenant_id': tenant_id})
    db.execute(text('INSERT INTO tenants(id, name, slug) VALUES (:id, :name, :slug)'), {'id': tenant_id, 'name': name, 'slug': slug})
    db.commit()
    return {'id': tenant_id, 'name': name, 'slug': slug}


@app.post('/api/v1/admin/api-keys')
def create_instance_api_key(label: str = 'default', scopes: str = 'retrieval:read,documents:write,vector_stores:write,vector_stores:read', max_security_level: int | None = None, expires_at: int | None = None, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'api_keys:write')
    enforce_rate_limit(db, principal, 'admin.api_keys.create')
    result = create_api_key(db, principal, label, [s.strip() for s in scopes.split(',') if s.strip()], max_security_level, expires_at)
    db.commit()
    return result


@app.get('/api/v1/admin/api-keys')
def list_instance_api_keys(limit: int = 20, after: str | None = None, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, ['api_keys:read', 'api_keys:write'], any_of=True)
    enforce_rate_limit(db, principal, 'admin.api_keys.list')
    data, has_more = list_api_keys(db, principal, limit, after=after)
    return _list_response(data, has_more)


@app.delete('/api/v1/admin/api-keys/{api_key_id}')
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


async def _openai_vector_store_search_page(
    vector_store_id: str,
    req: OpenAIVectorStoreSearchRequest,
    principal: Principal,
    db: Session,
) -> dict[str, Any]:
    _refresh_vector_store_activity_or_404(db, principal, vector_store_id)
    search_kwargs = openai_search_options_to_search_request_kwargs(req)
    raw_queries = req.query if isinstance(req.query, list) else [req.query]
    query_plans = [plan_query(query, rewrite_query=req.rewrite_query) for query in raw_queries]
    effective_search_query = (
        query_plans[0].effective_query
        if isinstance(req.query, str)
        else [query_plan.effective_query for query_plan in query_plans]
    )
    subqueries = [
        subquery
        for query_plan in query_plans
        for subquery in query_plan.subqueries
    ]
    filters = dict(search_kwargs.pop('filters') or {})
    filters['vector_store_id'] = vector_store_id
    search_kwargs.pop('query', None)
    page_size = req.top_k or req.max_num_results
    page_offset = vector_store_search_next_page_offset(req.next_page)
    search_fetch_limit = page_offset + page_size + 1
    search_kwargs['top_k'] = search_fetch_limit
    metadata = dict(search_kwargs.pop('search_metadata') or {})
    compat_meta = dict(metadata.get('openai_compat') or {})
    compat_meta.update({
        'effective_query': effective_search_query,
        'subqueries': subqueries,
        'rewritten': any(query_plan.rewritten for query_plan in query_plans),
        'page_offset': page_offset,
    })
    metadata['openai_compat'] = compat_meta
    result_lists = []
    for subquery in subqueries:
        result = await retrieval.search(db, principal, SearchRequest(vector_store_id=vector_store_id, filters=filters, query=subquery, search_metadata=metadata, **search_kwargs))
        result_lists.append(result.results)
    chunks = merge_chunk_results(result_lists, search_fetch_limit)
    chunks = apply_openai_ranking_options(req, chunks, limit=search_fetch_limit)
    chunks, next_page = vector_store_search_page_window(req, chunks)
    file_lookup = _vector_store_file_lookup(db, principal, vector_store_id, [ch.document_id for ch in chunks])
    return vector_store_search_results_page(req, chunks, file_lookup, search_query=effective_search_query, next_page=next_page)


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
