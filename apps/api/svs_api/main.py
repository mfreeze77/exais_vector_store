from __future__ import annotations
from typing import Any
from fastapi import Depends, FastAPI, HTTPException, UploadFile, File, Form, Header, Body, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from svs_common.config import get_settings, validate_production_guardrails
from svs_common.db import jsonb_param, get_session, set_rls_context
from svs_common.sql import jsonb_text
from svs_common.security import principal_from_dev_headers
from svs_common.schemas import (
    Principal, VectorStoreCreateRequest, SearchRequest, ContextPackRequest, DocumentIngestRequest,
    VectorStoreResponse, IngestionPreviewRequest, ModelEndpointRequest, ModelEndpointResponse,
    BakeoffRunRequest, ReindexRequest,
)
from svs_common.vector_store_repo import VectorStoreRepository
from svs_common.ingestion import IngestionService
from svs_common.retrieval import RetrievalService
from svs_common.model_registry import vectorization_modes, model_registry, retrieval_profiles
from svs_common.ids import new_id
from svs_common.auth import resolve_api_key_principal, create_api_key, ensure_scope
from svs_common.request_controls import stable_hash, check_idempotency, store_idempotency, enforce_rate_limit
from svs_common.vectorization_router import build_ingestion_plan, persist_ingestion_plan
from svs_common.maintenance import MaintenanceService
from svs_common.bakeoff import BakeoffService
from svs_common.index_cleanup import enqueue_purge_stale_vectors

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


def should_enqueue_ingest(req: DocumentIngestRequest) -> bool:
    raw_len = len((req.content or '').encode('utf-8'))
    if req.attributes.get('force_sync') is True:
        return False
    if req.attributes.get('force_async') is True:
        return True
    return raw_len > settings.svs_ingest_inline_max_bytes


async def ingest_or_enqueue(req: DocumentIngestRequest, principal: Principal, db: Session):
    if should_enqueue_ingest(req):
        result = ingestion.enqueue(db, principal, req)
    else:
        result = await ingestion.ingest_now(db, principal, req)
    db.commit()
    return result


def _list_response(data: list[Any], has_more: bool = False) -> dict[str, Any]:
    def item_id(x):
        return x.get('id') if isinstance(x, dict) else getattr(x, 'id', None)
    return {'object': 'list', 'data': data, 'first_id': item_id(data[0]) if data else None, 'last_id': item_id(data[-1]) if data else None, 'has_more': has_more}


@app.get('/healthz')
def healthz():
    return {'ok': True, 'service': 'svs-api', 'version': settings.svs_product_version, 'sparse_backend': settings.svs_sparse_backend, 'dense_backend': settings.svs_dense_backend}


@app.get('/readyz')
def readyz(db: Session = Depends(get_session)):
    try:
        db.execute(text('SELECT 1'))
        db_ok = True
    except Exception:
        db_ok = False
    return {'ready': db_ok, 'db': db_ok}


@app.get('/metrics', response_class=PlainTextResponse)
def metrics(db: Session = Depends(get_session)):
    lines = [f'svs_api_build_info{{version="{settings.svs_product_version}"}} 1']
    for name, sql in {
        'svs_ingestion_jobs_queued': "SELECT count(*) FROM ingestion_jobs WHERE status='queued'",
        'svs_ingestion_jobs_failed': "SELECT count(*) FROM ingestion_jobs WHERE status='failed'",
        'svs_vector_stores_active': "SELECT count(*) FROM vector_stores WHERE status IN ('active','completed')",
        'svs_chunks_index_pending': "SELECT count(*) FROM chunks WHERE dense_index_status <> 'indexed' OR sparse_index_status <> 'indexed'",
    }.items():
        try:
            value = db.execute(text(sql)).scalar() or 0
            lines.append(f'{name} {int(value)}')
        except Exception:
            lines.append(f'{name} 0')
    return '\n'.join(lines) + '\n'


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
    result = await retrieval.search(db, principal, req)
    db.commit()
    return result


@app.post('/api/v1/retrieval/context-pack')
async def context_pack(req: ContextPackRequest, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'retrieval:read')
    enforce_rate_limit(db, principal, 'retrieval.context_pack')
    result = await retrieval.context_pack(db, principal, req)
    db.commit()
    return result


@app.post('/api/v1/model-endpoints', response_model=ModelEndpointResponse)
def create_model_endpoint(req: ModelEndpointRequest, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'models:write')
    endpoint_id = new_id('mdl')
    db.execute(jsonb_text('''
        INSERT INTO model_endpoints(id, tenant_id, business_instance_id, name, provider, kind, base_url, model, dimensions,
          privacy, security_max_level, status, config)
        VALUES (:id, :tenant_id, :biz_id, :name, :provider, :kind, :base_url, :model, :dimensions, :privacy, :security_max_level, :status, CAST(:config AS jsonb))
    ''', 'config'), {**req.model_dump(), 'id': endpoint_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'config': jsonb_param(req.config)})
    db.commit()
    return ModelEndpointResponse(id=endpoint_id, **req.model_dump())


@app.get('/api/v1/model-endpoints')
def list_model_endpoints(principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, ['models:read', 'models:write'], any_of=True)
    rows = db.execute(text('''
        SELECT id, name, provider, kind, base_url, model, dimensions, privacy, security_max_level, status, config,
               extract(epoch from created_at)::bigint created_at, extract(epoch from updated_at)::bigint updated_at
        FROM model_endpoints WHERE tenant_id=:tenant_id AND business_instance_id=:biz_id ORDER BY created_at DESC
    '''), {'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id}).mappings().all()
    return _list_response([dict(r) for r in rows])


@app.patch('/api/v1/model-endpoints/{endpoint_id}', response_model=ModelEndpointResponse)
def update_model_endpoint(endpoint_id: str, patch: dict[str, Any] = Body(default_factory=dict), principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'models:write')
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
    return ModelEndpointResponse(id=row['id'], name=row['name'], provider=row['provider'], kind=row['kind'], base_url=row['base_url'], model=row['model'], dimensions=row['dimensions'], privacy=row['privacy'], security_max_level=row['security_max_level'], status=row['status'], config=dict(row['config'] or {}))


@app.post('/api/v1/bakeoffs')
def create_bakeoff(req: BakeoffRunRequest, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, ['evals:write', 'models:write'], any_of=True)
    result = bakeoff.create_run(db, principal, req)
    db.commit()
    return result


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
def create_instance_api_key(label: str = 'default', scopes: str = 'retrieval:read,documents:write,vector_stores:write,vector_stores:read', max_security_level: int | None = None, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'api_keys:write')
    result = create_api_key(db, principal, label, [s.strip() for s in scopes.split(',') if s.strip()], max_security_level)
    db.commit()
    return result


@app.post('/v1/vector_stores', response_model=VectorStoreResponse)
def create_vector_store(req: VectorStoreCreateRequest, idempotency_key: str | None = Header(default=None, alias='Idempotency-Key'), principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'vector_stores:write')
    enforce_rate_limit(db, principal, 'vector_stores.create')
    fp = stable_hash(req.model_dump())
    if cached := check_idempotency(db, principal, idempotency_key, fp):
        return cached
    result = vs_repo.create(db, principal, req)
    payload = result.model_dump()
    store_idempotency(db, principal, idempotency_key, fp, payload)
    db.commit()
    return result


@app.get('/v1/vector_stores')
def list_vector_stores(limit: int = 20, after: str | None = None, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'vector_stores:read')
    data, has_more = vs_repo.list(db, principal, limit, after=after)
    return _list_response(data, has_more)


@app.get('/v1/vector_stores/{vector_store_id}')
def get_vector_store(vector_store_id: str, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'vector_stores:read')
    result = vs_repo.get(db, principal, vector_store_id)
    if not result:
        raise HTTPException(status_code=404, detail='Vector store not found')
    return result


@app.patch('/v1/vector_stores/{vector_store_id}', response_model=VectorStoreResponse)
def update_vector_store(vector_store_id: str, patch: dict[str, Any] = Body(default_factory=dict), principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'vector_stores:write')
    result = vs_repo.update(db, principal, vector_store_id, patch)
    if not result:
        raise HTTPException(status_code=404, detail='Vector store not found')
    db.commit()
    return result


@app.delete('/v1/vector_stores/{vector_store_id}')
def delete_vector_store(vector_store_id: str, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, ['vector_stores:delete', 'vector_stores:write'], any_of=True)
    deleted = vs_repo.delete(db, principal, vector_store_id)
    db.commit()
    return {'id': vector_store_id, 'object': 'vector_store.deleted', 'deleted': deleted}


@app.post('/v1/vector_stores/{vector_store_id}/files')
async def attach_file(vector_store_id: str, req: DocumentIngestRequest, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'documents:write')
    req.vector_store_id = vector_store_id
    result = await ingest_or_enqueue(req, principal, db)
    return {'id': result.vector_store_file_id, 'object': 'vector_store.file', 'status': result.status, 'vector_store_id': vector_store_id}


@app.post('/v1/vector_stores/{vector_store_id}/search')
async def vector_store_search(vector_store_id: str, req: SearchRequest, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'retrieval:read')
    req.vector_store_id = vector_store_id
    result = await retrieval.search(db, principal, req)
    db.commit()
    return {'object': 'vector_store.search_results.page', 'search_query': req.query, 'data': [
        {'file_id': ch.document_id, 'score': ch.score, 'attributes': ch.metadata, 'content': [{'type': 'text', 'text': ch.text}] if req.include_content else []}
        for ch in result.results
    ]}


@app.get('/v1/vector_stores/{vector_store_id}/files')
def list_vector_store_files(vector_store_id: str, limit: int = 20, after: str | None = None, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'vector_stores:read')
    req_limit = min(max(limit, 1), 100)
    params = {'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'vs_id': vector_store_id, 'limit': req_limit + 1}
    after_clause = ''
    if after:
        row = db.execute(text('SELECT created_at FROM vector_store_files WHERE id=:after AND tenant_id=:tenant_id AND business_instance_id=:biz_id AND vector_store_id=:vs_id'), {**params, 'after': after}).mappings().first()
        if row:
            after_clause = 'AND created_at < :after_created_at'
            params['after_created_at'] = row['created_at']
    rows = db.execute(text(f'''
        SELECT id, vector_store_id, document_id, status, attributes, usage_bytes, last_error,
               extract(epoch from created_at)::bigint AS created_at, extract(epoch from completed_at)::bigint AS completed_at
        FROM vector_store_files
        WHERE tenant_id=:tenant_id AND business_instance_id=:biz_id AND vector_store_id=:vs_id {after_clause}
        ORDER BY created_at DESC LIMIT :limit
    '''), params).mappings().all()
    has_more = len(rows) > req_limit
    rows = rows[:req_limit]
    data = [{'id': r['id'], 'object': 'vector_store.file', 'vector_store_id': r['vector_store_id'], 'document_id': r['document_id'], 'status': r['status'], 'attributes': dict(r['attributes'] or {}), 'usage_bytes': r['usage_bytes'], 'created_at': r['created_at'], 'completed_at': r['completed_at'], 'last_error': r['last_error']} for r in rows]
    return _list_response(data, has_more)


@app.get('/v1/vector_stores/{vector_store_id}/files/{file_id}')
def get_vector_store_file(vector_store_id: str, file_id: str, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'vector_stores:read')
    r = db.execute(text('''
        SELECT id, vector_store_id, document_id, status, attributes, usage_bytes, last_error,
               extract(epoch from created_at)::bigint AS created_at, extract(epoch from completed_at)::bigint AS completed_at
        FROM vector_store_files
        WHERE id=:id AND vector_store_id=:vs_id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
    '''), {'id': file_id, 'vs_id': vector_store_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id}).mappings().first()
    if not r:
        raise HTTPException(status_code=404, detail='Vector store file not found')
    return {'id': r['id'], 'object': 'vector_store.file', 'vector_store_id': r['vector_store_id'], 'document_id': r['document_id'], 'status': r['status'], 'attributes': dict(r['attributes'] or {}), 'usage_bytes': r['usage_bytes'], 'created_at': r['created_at'], 'completed_at': r['completed_at'], 'last_error': r['last_error']}


@app.patch('/v1/vector_stores/{vector_store_id}/files/{file_id}')
def update_vector_store_file(vector_store_id: str, file_id: str, patch: dict[str, Any] = Body(default_factory=dict), principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'vector_stores:write')
    attrs = patch.get('attributes', {})
    result = db.execute(jsonb_text('''
        UPDATE vector_store_files SET attributes=CAST(:attrs AS jsonb)
        WHERE id=:id AND vector_store_id=:vs_id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
    ''', 'attrs'), {'attrs': jsonb_param(attrs), 'id': file_id, 'vs_id': vector_store_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id})
    if not result.rowcount:
        raise HTTPException(status_code=404, detail='Vector store file not found')
    db.commit()
    return get_vector_store_file(vector_store_id, file_id, principal, db)


@app.delete('/v1/vector_stores/{vector_store_id}/files/{file_id}')
def delete_vector_store_file(vector_store_id: str, file_id: str, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, ['vector_stores:write', 'vector_store_files:delete'], any_of=True)
    row = db.execute(text('''
        UPDATE vector_store_files SET status='cancelled'
        WHERE id=:id AND vector_store_id=:vs_id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
        RETURNING document_id
    '''), {'id': file_id, 'vs_id': vector_store_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail='Vector store file not found')
    if row['document_id']:
        db.execute(text('''
            UPDATE chunks
            SET active=false, deleted_at=now(), dense_index_status='delete_queued', sparse_index_status='delete_queued'
            WHERE document_id=:doc_id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
        '''), {'doc_id': row['document_id'], 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id})
        enqueue_purge_stale_vectors(db, principal, document_id=row['document_id'], reason='vector_store_file_deleted')
    db.commit()
    return {'id': file_id, 'object': 'vector_store.file.deleted', 'deleted': True}


@app.get('/v1/vector_stores/{vector_store_id}/files/{file_id}/content')
def get_vector_store_file_content(vector_store_id: str, file_id: str, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'vector_stores:read')
    rows = db.execute(text('''
        SELECT c.ordinal, c.text, c.heading_path, c.page_start, c.page_end
        FROM vector_store_files f JOIN chunks c ON c.document_id=f.document_id
        WHERE f.id=:file_id AND f.vector_store_id=:vs_id AND f.tenant_id=:tenant_id AND f.business_instance_id=:biz_id
          AND c.active=true AND c.security_level <= :max_lvl
        ORDER BY c.ordinal ASC
    '''), {'file_id': file_id, 'vs_id': vector_store_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'max_lvl': principal.max_security_level}).mappings().all()
    if not rows:
        raise HTTPException(status_code=404, detail='No readable content found for file')
    return {'object': 'vector_store.file_content', 'data': [{'type': 'text', 'text': r['text'], 'heading_path': list(r['heading_path'] or []), 'page_start': r['page_start'], 'page_end': r['page_end']} for r in rows]}


@app.post('/v1/vector_stores/{vector_store_id}/file_batches')
def create_file_batch(vector_store_id: str, payload: dict[str, Any] = Body(default_factory=dict), principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'documents:write')
    files = payload.get('files') or []
    file_ids = payload.get('file_ids') or []
    total = len(files) + len(file_ids)
    batch_id = new_id('vsfb')
    file_counts = {'in_progress': len(files), 'completed': len(file_ids), 'failed': 0, 'cancelled': 0, 'total': total}
    db.execute(jsonb_text('''
        INSERT INTO file_batches(id, tenant_id, business_instance_id, vector_store_id, status, file_counts)
        VALUES (:id, :tenant_id, :biz_id, :vs_id, :status, CAST(:file_counts AS jsonb))
    ''', 'file_counts'), {'id': batch_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'vs_id': vector_store_id, 'status': 'in_progress' if files else 'completed', 'file_counts': jsonb_param(file_counts)})
    for doc_id in file_ids:
        db.execute(jsonb_text('''
            INSERT INTO vector_store_files(id, tenant_id, business_instance_id, vector_store_id, document_id, file_batch_id, status, attributes, completed_at)
            SELECT :id, :tenant_id, :biz_id, :vs_id, d.id, :batch_id, 'completed', CAST(:attrs AS jsonb), now()
            FROM documents d WHERE d.id=:doc_id AND d.tenant_id=:tenant_id AND d.business_instance_id=:biz_id
        ''', 'attrs'), {'id': new_id('vsf'), 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'vs_id': vector_store_id, 'doc_id': doc_id, 'batch_id': batch_id, 'attrs': jsonb_param({'attached_from_document_id': doc_id})})
    for raw in files:
        req = DocumentIngestRequest.model_validate({**raw, 'vector_store_id': vector_store_id})
        ingestion.enqueue(db, principal, req, file_batch_id=batch_id)
    db.commit()
    return {'id': batch_id, 'object': 'vector_store.file_batch', 'vector_store_id': vector_store_id, 'status': 'in_progress' if files else 'completed', 'file_counts': file_counts}


@app.get('/v1/vector_stores/{vector_store_id}/file_batches/{batch_id}')
def get_file_batch(vector_store_id: str, batch_id: str, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'vector_stores:read')
    r = db.execute(text('''
        SELECT id, vector_store_id, status, file_counts, extract(epoch from created_at)::bigint AS created_at, extract(epoch from completed_at)::bigint AS completed_at
        FROM file_batches
        WHERE id=:id AND vector_store_id=:vs_id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
    '''), {'id': batch_id, 'vs_id': vector_store_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id}).mappings().first()
    if not r:
        raise HTTPException(status_code=404, detail='File batch not found')
    return {'id': r['id'], 'object': 'vector_store.file_batch', 'vector_store_id': r['vector_store_id'], 'status': r['status'], 'file_counts': dict(r['file_counts'] or {}), 'created_at': r['created_at'], 'completed_at': r['completed_at']}


@app.post('/v1/vector_stores/{vector_store_id}/file_batches/{batch_id}/cancel')
def cancel_file_batch(vector_store_id: str, batch_id: str, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, ['vector_stores:write', 'documents:write'], any_of=True)
    db.execute(text('''
        UPDATE ingestion_jobs SET status='cancelled', updated_at=now()
        WHERE tenant_id=:tenant_id AND business_instance_id=:biz_id AND status='queued'
          AND payload->>'file_batch_id'=:batch_id
    '''), {'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'batch_id': batch_id})
    db.execute(text('''
        UPDATE file_batches SET status='cancelled', completed_at=now(),
            file_counts = jsonb_set(jsonb_set(file_counts, '{cancelled}', (coalesce((file_counts->>'in_progress')::int,0)::text)::jsonb), '{in_progress}', '0'::jsonb)
        WHERE id=:id AND vector_store_id=:vs_id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
    '''), {'id': batch_id, 'vs_id': vector_store_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id})
    db.commit()
    return get_file_batch(vector_store_id, batch_id, principal, db)


@app.get('/v1/vector_stores/{vector_store_id}/file_batches/{batch_id}/files')
def list_file_batch_files(vector_store_id: str, batch_id: str, principal: Principal = Depends(get_request_principal), db: Session = Depends(db_for_principal)):
    ensure_scope(principal, 'vector_stores:read')
    rows = db.execute(text('''
        SELECT id, vector_store_id, document_id, status, attributes, usage_bytes, extract(epoch from created_at)::bigint AS created_at
        FROM vector_store_files
        WHERE tenant_id=:tenant_id AND business_instance_id=:biz_id AND vector_store_id=:vs_id AND file_batch_id=:batch_id
        ORDER BY created_at DESC
    '''), {'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'vs_id': vector_store_id, 'batch_id': batch_id}).mappings().all()
    data = [{'id': r['id'], 'object': 'vector_store.file', 'vector_store_id': r['vector_store_id'], 'document_id': r['document_id'], 'status': r['status'], 'attributes': dict(r['attributes'] or {}), 'usage_bytes': r['usage_bytes'], 'created_at': r['created_at']} for r in rows]
    return _list_response(data)
