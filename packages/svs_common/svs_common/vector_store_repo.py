from __future__ import annotations
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from sqlalchemy.orm import Session
from .sql import jsonb_text
from .db import jsonb_param
from .ids import new_id
from .schemas import Principal, VectorStoreCreateRequest, VectorStoreResponse
from .index_cleanup import enqueue_purge_stale_vectors
from .openai_metadata import validate_openai_metadata

OPENAI_DESCRIPTION_ATTRIBUTE = "_openai_description"
OPENAI_CHUNKING_STRATEGY_ATTRIBUTE = "_openai_chunking_strategy"
ZERO_FILE_COUNTS = {'in_progress': 0, 'completed': 0, 'failed': 0, 'cancelled': 0, 'total': 0}


class VectorStoreUnavailableError(RuntimeError):
    def __init__(self, vector_store_id: str, reason: str = 'not_found'):
        self.vector_store_id = vector_store_id
        self.reason = reason
        super().__init__(f'Vector store {vector_store_id} is unavailable: {reason}')


def _expiration_policy_days(expires_after: dict | None) -> int | None:
    if not expires_after:
        return None
    anchor = expires_after.get('anchor', expires_after.get('anchor_timestamp'))
    if anchor != 'last_active_at':
        return None
    raw_days = None
    if 'days' in expires_after:
        raw_days = expires_after['days']
    elif 'duration_days' in expires_after:
        raw_days = expires_after['duration_days']
    if raw_days is None:
        return None
    if isinstance(raw_days, bool):
        return None
    try:
        days = int(raw_days)
    except (TypeError, ValueError):
        return None
    if days <= 0:
        return None
    return days


def _expires_at_from_policy(expires_after: dict | None, *, anchor_time: datetime | None = None) -> datetime | None:
    days = _expiration_policy_days(expires_after)
    if days is None:
        return None
    anchor = anchor_time or datetime.now(timezone.utc)
    return anchor + timedelta(days=days)


def require_active_vector_store(db: Session, principal: Principal, vector_store_id: str) -> dict:
    row = db.execute(text('''
        SELECT id, status, expires_at IS NOT NULL AND expires_at <= now() AS is_expired
        FROM vector_stores
        WHERE id=:id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
          AND status != 'deleted'
        LIMIT 1
    '''), {'id': vector_store_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id}).mappings().first()
    if not row:
        raise VectorStoreUnavailableError(vector_store_id, 'not_found')
    if row['status'] == 'expired' or row.get('is_expired'):
        raise VectorStoreUnavailableError(vector_store_id, 'expired')
    return dict(row)


def refresh_vector_store_activity(db: Session, principal: Principal, vector_store_id: str, *, usage_bytes_delta: int = 0) -> bool:
    delta = max(int(usage_bytes_delta or 0), 0)
    row = db.execute(text('''
        UPDATE vector_stores
        SET last_active_at=now(),
            usage_bytes=usage_bytes + :usage_bytes_delta,
            expires_at=CASE
              WHEN coalesce(expires_after->>'anchor', expires_after->>'anchor_timestamp') = 'last_active_at'
               AND coalesce(expires_after->>'days', expires_after->>'duration_days') ~ '^[1-9][0-9]*$'
              THEN now() + ((coalesce(expires_after->>'days', expires_after->>'duration_days'))::int * interval '1 day')
              ELSE expires_at
            END,
            updated_at=now()
        WHERE id=:id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
          AND status NOT IN ('deleted', 'expired')
          AND (expires_at IS NULL OR expires_at > now())
        RETURNING id
    '''), {
        'id': vector_store_id,
        'tenant_id': principal.tenant_id,
        'biz_id': principal.business_instance_id,
        'usage_bytes_delta': delta,
    }).mappings().first()
    return bool(row)


def _openai_public_metadata(attributes: dict | None) -> dict:
    attrs = dict(attributes or {})
    attrs.pop(OPENAI_DESCRIPTION_ATTRIBUTE, None)
    attrs.pop(OPENAI_CHUNKING_STRATEGY_ATTRIBUTE, None)
    return attrs


def _attributes_from_create_request(req: VectorStoreCreateRequest) -> dict:
    attrs = validate_openai_metadata(req.metadata if req.metadata is not None else req.attributes or {}, context='vector store metadata')
    if req.description is not None:
        attrs[OPENAI_DESCRIPTION_ATTRIBUTE] = req.description
    if req.chunking_strategy is not None:
        attrs[OPENAI_CHUNKING_STRATEGY_ATTRIBUTE] = req.chunking_strategy
    return attrs


def _vector_store_response_from_row(row) -> VectorStoreResponse:
    attrs = dict(row['attributes'] or {})
    metadata = _openai_public_metadata(attrs)
    usage_bytes = int(row['usage_bytes'] or 0)
    file_counts = dict(row.get('file_counts') or ZERO_FILE_COUNTS)
    for key, value in ZERO_FILE_COUNTS.items():
        file_counts.setdefault(key, value)
    return VectorStoreResponse(
        id=row['id'],
        name=row['name'],
        description=attrs.get(OPENAI_DESCRIPTION_ATTRIBUTE),
        status=row['status'],
        usage_bytes=usage_bytes,
        bytes=usage_bytes,
        file_counts=file_counts,
        attributes=metadata,
        metadata=metadata,
        created_at=row['created_at'],
        expires_after=dict(row['expires_after'] or {}) if row['expires_after'] else None,
        expires_at=row['expires_at'],
        last_active_at=row['last_active_at'],
    )


class VectorStoreRepository:
    def create(self, db: Session, principal: Principal, req: VectorStoreCreateRequest) -> VectorStoreResponse:
        vs_id = new_id('vs')
        name = req.name or vs_id
        attrs = _attributes_from_create_request(req)
        expires_at = _expires_at_from_policy(req.expires_after)
        db.execute(jsonb_text('''
            INSERT INTO vector_stores(id, tenant_id, business_instance_id, knowledge_base_id, name, attributes, expires_after, expires_at, last_active_at, status)
            VALUES (:id, :tenant_id, :biz_id, :kb_id, :name, CAST(:attrs AS jsonb), CAST(:expires_after AS jsonb), :expires_at, now(), 'completed')
        ''', 'attrs', 'expires_after'), {'id': vs_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'kb_id': req.knowledge_base_id,
              'name': name, 'attrs': jsonb_param(attrs), 'expires_after': jsonb_param(req.expires_after), 'expires_at': expires_at})
        return VectorStoreResponse(
            id=vs_id,
            name=name,
            description=req.description,
            attributes=_openai_public_metadata(attrs),
            metadata=_openai_public_metadata(attrs),
            expires_after=req.expires_after,
            expires_at=int(expires_at.timestamp()) if expires_at else None,
        )

    def list(self, db: Session, principal: Principal, limit: int = 20, *, after: str | None = None, before: str | None = None, order: str = 'desc') -> tuple[list[VectorStoreResponse], bool]:
        limit = min(max(limit, 1), 100)
        params = {'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'limit': limit + 1}
        order = 'asc' if str(order).lower() == 'asc' else 'desc'
        after_clause = ''
        if after:
            after_row = db.execute(text('SELECT id, created_at FROM vector_stores WHERE id=:after AND tenant_id=:tenant_id AND business_instance_id=:biz_id'), {**params, 'after': after}).mappings().first()
            if after_row:
                after_op = '>' if order == 'asc' else '<'
                after_clause = f'AND (vs.created_at {after_op} :after_created_at OR (vs.created_at=:after_created_at AND vs.id {after_op} :after_id))'
                params['after_created_at'] = after_row['created_at']
                params['after_id'] = after_row['id']
        before_clause = ''
        if before:
            before_row = db.execute(text('SELECT id, created_at FROM vector_stores WHERE id=:before AND tenant_id=:tenant_id AND business_instance_id=:biz_id'), {**params, 'before': before}).mappings().first()
            if before_row:
                before_op = '<' if order == 'asc' else '>'
                before_clause = f'AND (vs.created_at {before_op} :before_created_at OR (vs.created_at=:before_created_at AND vs.id {before_op} :before_id))'
                params['before_created_at'] = before_row['created_at']
                params['before_id'] = before_row['id']
        rows = db.execute(text(f'''
            SELECT vs.id, vs.name, vs.status, vs.usage_bytes, vs.attributes, vs.expires_after,
                   extract(epoch from vs.created_at)::bigint as created_at,
                   extract(epoch from vs.expires_at)::bigint as expires_at,
                   extract(epoch from vs.last_active_at)::bigint as last_active_at,
                   jsonb_build_object(
                     'in_progress', count(vsf.id) FILTER (WHERE vsf.status='in_progress'),
                     'completed', count(vsf.id) FILTER (WHERE vsf.status='completed'),
                     'failed', count(vsf.id) FILTER (WHERE vsf.status='failed'),
                     'cancelled', count(vsf.id) FILTER (WHERE vsf.status='cancelled'),
                     'total', count(vsf.id)
                   ) AS file_counts
            FROM vector_stores vs
            LEFT JOIN vector_store_files vsf
              ON vsf.vector_store_id=vs.id
             AND vsf.tenant_id=vs.tenant_id
             AND vsf.business_instance_id=vs.business_instance_id
            WHERE vs.tenant_id=:tenant_id AND vs.business_instance_id=:biz_id AND vs.status != 'deleted' {after_clause} {before_clause}
            GROUP BY vs.id, vs.name, vs.status, vs.usage_bytes, vs.attributes, vs.expires_after, vs.created_at, vs.expires_at, vs.last_active_at
            ORDER BY vs.created_at {order.upper()}, vs.id {order.upper()} LIMIT :limit
        '''), params).mappings().all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        data = [_vector_store_response_from_row(r) for r in rows]
        return data, has_more

    def get(self, db: Session, principal: Principal, vector_store_id: str) -> VectorStoreResponse | None:
        r = db.execute(text('''
            SELECT vs.id, vs.name, vs.status, vs.usage_bytes, vs.attributes, vs.expires_after,
                   extract(epoch from vs.created_at)::bigint as created_at,
                   extract(epoch from vs.expires_at)::bigint as expires_at,
                   extract(epoch from vs.last_active_at)::bigint as last_active_at,
                   jsonb_build_object(
                     'in_progress', count(vsf.id) FILTER (WHERE vsf.status='in_progress'),
                     'completed', count(vsf.id) FILTER (WHERE vsf.status='completed'),
                     'failed', count(vsf.id) FILTER (WHERE vsf.status='failed'),
                     'cancelled', count(vsf.id) FILTER (WHERE vsf.status='cancelled'),
                     'total', count(vsf.id)
                   ) AS file_counts
            FROM vector_stores vs
            LEFT JOIN vector_store_files vsf
              ON vsf.vector_store_id=vs.id
             AND vsf.tenant_id=vs.tenant_id
             AND vsf.business_instance_id=vs.business_instance_id
            WHERE vs.id=:id AND vs.tenant_id=:tenant_id AND vs.business_instance_id=:biz_id
            GROUP BY vs.id, vs.name, vs.status, vs.usage_bytes, vs.attributes, vs.expires_after, vs.created_at, vs.expires_at, vs.last_active_at
        '''), {'id': vector_store_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id}).mappings().first()
        if not r:
            return None
        return _vector_store_response_from_row(r)

    def update(self, db: Session, principal: Principal, vector_store_id: str, patch: dict) -> VectorStoreResponse | None:
        fields, params = [], {'id': vector_store_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id}
        json_params: list[str] = []
        if hasattr(patch, 'model_dump'):
            patch = patch.model_dump(exclude_unset=True)
        if 'name' in patch and patch['name'] is not None:
            fields.append('name=:name')
            params['name'] = patch['name']
        if 'attributes' in patch or 'metadata' in patch or 'description' in patch or 'chunking_strategy' in patch:
            current = db.execute(text('''
                SELECT attributes FROM vector_stores
                WHERE id=:id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
            '''), params).mappings().first()
            attrs = dict(current['attributes'] or {}) if current else {}
            if 'attributes' in patch or 'metadata' in patch:
                raw_public_attrs = patch['attributes'] if 'attributes' in patch else patch.get('metadata')
                public_attrs = validate_openai_metadata(
                    raw_public_attrs,
                    context='vector store metadata',
                )
                attrs = {
                    key: value
                    for key, value in attrs.items()
                    if key in {OPENAI_DESCRIPTION_ATTRIBUTE, OPENAI_CHUNKING_STRATEGY_ATTRIBUTE}
                }
                attrs.update(public_attrs)
            if 'description' in patch:
                if patch['description'] is None:
                    attrs.pop(OPENAI_DESCRIPTION_ATTRIBUTE, None)
                else:
                    attrs[OPENAI_DESCRIPTION_ATTRIBUTE] = patch['description']
            if 'chunking_strategy' in patch:
                if patch['chunking_strategy'] is None:
                    attrs.pop(OPENAI_CHUNKING_STRATEGY_ATTRIBUTE, None)
                else:
                    attrs[OPENAI_CHUNKING_STRATEGY_ATTRIBUTE] = patch['chunking_strategy']
            fields.append('attributes=CAST(:attrs AS jsonb)')
            params['attrs'] = jsonb_param(attrs)
            json_params.append('attrs')
        if 'expires_after' in patch:
            fields.append('expires_after=CAST(:expires_after AS jsonb)')
            fields.append('expires_at=:expires_at')
            params['expires_after'] = jsonb_param(patch['expires_after'])
            params['expires_at'] = _expires_at_from_policy(patch['expires_after'])
            json_params.append('expires_after')
        if fields:
            db.execute(jsonb_text(f'''
                UPDATE vector_stores SET {', '.join(fields)}, updated_at=now()
                WHERE id=:id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
            ''', *json_params), params)
        return self.get(db, principal, vector_store_id)

    def delete(self, db: Session, principal: Principal, vector_store_id: str) -> bool:
        exists = db.execute(text('''
            SELECT id FROM vector_stores
            WHERE id=:id AND tenant_id=:tenant_id AND business_instance_id=:biz_id AND status != 'deleted'
        '''), {'id': vector_store_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id}).mappings().first()
        if not exists:
            return False
        result = db.execute(text('''
            UPDATE vector_stores SET status='deleted', updated_at=now(), deleted_at=now()
            WHERE id=:id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
        '''), {'id': vector_store_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id})
        if result.rowcount:
            # Chunk soft-delete is a tenant-scoped maintenance mutation. The RLS
            # policy allows this only under the transaction-local system worker
            # flag, while still requiring the tenant/business context.
            db.execute(text("SELECT set_config('svs.system_worker', 'true', true)"))
            db.execute(text('''
                UPDATE chunks
                SET active=false, deleted_at=now(), dense_index_status='delete_queued', sparse_index_status='delete_queued'
                WHERE vector_store_id=:id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
            '''), {'id': vector_store_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id})
            enqueue_purge_stale_vectors(db, principal, vector_store_id=vector_store_id, reason='vector_store_deleted')
        return bool(result.rowcount)
