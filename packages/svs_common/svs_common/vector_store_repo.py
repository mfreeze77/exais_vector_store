from __future__ import annotations
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from sqlalchemy.orm import Session
from .sql import jsonb_text
from .db import jsonb_param
from .ids import new_id
from .schemas import Principal, VectorStoreCreateRequest, VectorStoreResponse
from .index_cleanup import enqueue_purge_stale_vectors

def _expires_at_from_policy(expires_after: dict | None) -> datetime | None:
    if not expires_after:
        return None
    days = None
    anchor = expires_after.get('anchor') or expires_after.get('anchor_timestamp')
    if 'days' in expires_after:
        days = int(expires_after['days'])
    elif 'duration_days' in expires_after:
        days = int(expires_after['duration_days'])
    if days is None:
        return None
    return datetime.now(timezone.utc) + timedelta(days=days)

class VectorStoreRepository:
    def create(self, db: Session, principal: Principal, req: VectorStoreCreateRequest) -> VectorStoreResponse:
        vs_id = new_id('vs')
        attrs = req.metadata or req.attributes or {}
        expires_at = _expires_at_from_policy(req.expires_after)
        db.execute(jsonb_text('''
            INSERT INTO vector_stores(id, tenant_id, business_instance_id, knowledge_base_id, name, attributes, expires_after, expires_at, last_active_at, status)
            VALUES (:id, :tenant_id, :biz_id, :kb_id, :name, CAST(:attrs AS jsonb), CAST(:expires_after AS jsonb), :expires_at, now(), 'completed')
        ''', 'attrs', 'expires_after'), {'id': vs_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'kb_id': req.knowledge_base_id,
              'name': req.name, 'attrs': jsonb_param(attrs), 'expires_after': jsonb_param(req.expires_after), 'expires_at': expires_at})
        return VectorStoreResponse(id=vs_id, name=req.name, attributes=attrs, expires_after=req.expires_after, expires_at=int(expires_at.timestamp()) if expires_at else None)

    def list(self, db: Session, principal: Principal, limit: int = 20, *, after: str | None = None) -> tuple[list[VectorStoreResponse], bool]:
        limit = min(max(limit, 1), 100)
        params = {'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'limit': limit + 1}
        after_clause = ''
        if after:
            after_row = db.execute(text('SELECT created_at FROM vector_stores WHERE id=:after AND tenant_id=:tenant_id AND business_instance_id=:biz_id'), {**params, 'after': after}).mappings().first()
            if after_row:
                after_clause = 'AND created_at < :after_created_at'
                params['after_created_at'] = after_row['created_at']
        rows = db.execute(text(f'''
            SELECT id, name, status, usage_bytes, attributes, expires_after, extract(epoch from created_at)::bigint as created_at,
                   extract(epoch from expires_at)::bigint as expires_at, extract(epoch from last_active_at)::bigint as last_active_at
            FROM vector_stores
            WHERE tenant_id=:tenant_id AND business_instance_id=:biz_id AND status != 'deleted' {after_clause}
            ORDER BY created_at DESC LIMIT :limit
        '''), params).mappings().all()
        has_more = len(rows) > limit
        rows = rows[:limit]
        data = [VectorStoreResponse(id=r['id'], name=r['name'], status=r['status'], usage_bytes=r['usage_bytes'], attributes=dict(r['attributes'] or {}), created_at=r['created_at'], expires_after=dict(r['expires_after'] or {}) if r['expires_after'] else None, expires_at=r['expires_at'], last_active_at=r['last_active_at']) for r in rows]
        return data, has_more

    def get(self, db: Session, principal: Principal, vector_store_id: str) -> VectorStoreResponse | None:
        r = db.execute(text('''
            SELECT id, name, status, usage_bytes, attributes, expires_after, extract(epoch from created_at)::bigint as created_at,
                   extract(epoch from expires_at)::bigint as expires_at, extract(epoch from last_active_at)::bigint as last_active_at
            FROM vector_stores
            WHERE id=:id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
        '''), {'id': vector_store_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id}).mappings().first()
        if not r:
            return None
        return VectorStoreResponse(id=r['id'], name=r['name'], status=r['status'], usage_bytes=r['usage_bytes'], attributes=dict(r['attributes'] or {}), created_at=r['created_at'], expires_after=dict(r['expires_after'] or {}) if r['expires_after'] else None, expires_at=r['expires_at'], last_active_at=r['last_active_at'])

    def update(self, db: Session, principal: Principal, vector_store_id: str, patch: dict) -> VectorStoreResponse | None:
        fields, params = [], {'id': vector_store_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id}
        json_params: list[str] = []
        if 'name' in patch:
            fields.append('name=:name')
            params['name'] = patch['name']
        if 'attributes' in patch or 'metadata' in patch:
            fields.append('attributes=CAST(:attrs AS jsonb)')
            params['attrs'] = jsonb_param(patch.get('attributes', patch.get('metadata')) or {})
        if 'expires_after' in patch:
            fields.append('expires_after=CAST(:expires_after AS jsonb)')
            fields.append('expires_at=:expires_at')
            params['expires_after'] = jsonb_param(patch['expires_after'])
            params['expires_at'] = _expires_at_from_policy(patch['expires_after'])
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
            db.execute(text('''
                UPDATE chunks
                SET active=false, deleted_at=now(), dense_index_status='delete_queued', sparse_index_status='delete_queued'
                WHERE vector_store_id=:id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
            '''), {'id': vector_store_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id})
            enqueue_purge_stale_vectors(db, principal, vector_store_id=vector_store_id, reason='vector_store_deleted')
        return bool(result.rowcount)
