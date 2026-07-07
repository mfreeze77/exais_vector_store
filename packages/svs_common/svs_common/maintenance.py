from __future__ import annotations

from typing import Any
from sqlalchemy import text
from sqlalchemy.orm import Session
from .sql import jsonb_text
from .db import jsonb_param

from .schemas import MaintenanceResult, Principal, ReindexRequest
from .providers import ProviderConfigurationError, provider_for
from .model_registry import model_registry
from .qdrant_adapter import QdrantAdapter
from .opensearch_adapter import OpenSearchAdapter
from .config import get_settings
from .ids import point_uuid, new_id
from .index_cleanup import IndexCleanup, enqueue_purge_stale_vectors


class MaintenanceService:
    def __init__(self):
        self.settings = get_settings()
        self.qdrant = QdrantAdapter()
        self.opensearch = OpenSearchAdapter()
        self.index_cleanup = IndexCleanup()

    def cleanup_document_indexes(self, db: Session, principal: Principal, document_id: str) -> dict[str, int]:
        return self.index_cleanup.delete_by_document(db, principal, document_id)

    def cleanup_vector_store_indexes(self, db: Session, principal: Principal, vector_store_id: str) -> dict[str, int]:
        return self.index_cleanup.delete_by_vector_store(db, principal, vector_store_id)

    def purge_stale_vectors(self, db: Session, principal: Principal, payload: dict[str, Any]) -> MaintenanceResult:
        """Physically remove stale dense/sparse index entries queued by mutation paths.

        The logical row deactivation happens in the mutating transaction first. This
        worker-side job runs after that commit, so external index deletes cannot
        accidentally remove the only live copy if a document version ingest rolls
        back. Document-version scoped purge is preferred for supersedes.
        """
        document_version_ids = [v for v in payload.get('document_version_ids', []) if v]
        document_id = payload.get('document_id')
        vector_store_id = payload.get('vector_store_id')
        reason = payload.get('reason') or 'stale_index_cleanup'

        if document_version_ids:
            result = self.index_cleanup.delete_by_document_versions(db, principal, document_version_ids)
            db.execute(text('''
                UPDATE chunks
                SET dense_index_status='deleted', sparse_index_status='deleted', deleted_at=coalesce(deleted_at, now()), last_index_error=NULL
                WHERE tenant_id=:tenant_id AND business_instance_id=:biz_id
                  AND document_version_id = ANY(:docv_ids)
                  AND active=false
                  AND (dense_index_status='delete_queued' OR sparse_index_status='delete_queued')
            '''), {'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'docv_ids': document_version_ids})
        elif vector_store_id:
            result = self.index_cleanup.delete_by_vector_store(db, principal, vector_store_id)
            db.execute(text('''
                UPDATE chunks
                SET dense_index_status='deleted', sparse_index_status='deleted', deleted_at=coalesce(deleted_at, now()), last_index_error=NULL
                WHERE tenant_id=:tenant_id AND business_instance_id=:biz_id
                  AND vector_store_id=:vs_id
                  AND active=false
                  AND (dense_index_status='delete_queued' OR sparse_index_status='delete_queued')
            '''), {'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'vs_id': vector_store_id})
        elif document_id:
            result = self.index_cleanup.delete_by_document(db, principal, document_id)
            db.execute(text('''
                UPDATE chunks
                SET dense_index_status='deleted', sparse_index_status='deleted', deleted_at=coalesce(deleted_at, now()), last_index_error=NULL
                WHERE tenant_id=:tenant_id AND business_instance_id=:biz_id
                  AND document_id=:doc_id
                  AND active=false
                  AND (dense_index_status='delete_queued' OR sparse_index_status='delete_queued')
            '''), {'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'doc_id': document_id})
        else:
            result = {'dense_points_deleted': 0, 'sparse_docs_deleted': 0}

        processed = int(result.get('dense_points_deleted', 0)) + int(result.get('sparse_docs_deleted', 0))
        db.execute(jsonb_text('''
            INSERT INTO audit_events(id, tenant_id, business_instance_id, user_id, api_key_id, event_type, action, resource_type, metadata)
            VALUES (:id, :tenant_id, :biz_id, :user_id, :api_key_id, 'maintenance', 'purge_stale_vectors', 'index', CAST(:metadata AS jsonb))
        ''', 'metadata'), {
            'id': new_id('aud'),
            'tenant_id': principal.tenant_id,
            'biz_id': principal.business_instance_id,
            'user_id': principal.user_id,
            'api_key_id': principal.api_key_id,
            'metadata': jsonb_param({
                'reason': reason,
                'document_version_ids': document_version_ids,
                'document_id': document_id,
                'vector_store_id': vector_store_id,
                'result': result,
            }),
        })
        return MaintenanceResult(action='purge_stale_vectors', processed=processed, details={**result, 'reason': reason})

    def sweep_expired_vector_stores(self, db: Session, principal: Principal) -> MaintenanceResult:
        rows = db.execute(text('''
            UPDATE vector_stores SET status='expired', updated_at=now()
            WHERE tenant_id=:tenant_id AND business_instance_id=:biz_id
              AND status IN ('active','completed') AND expires_at IS NOT NULL AND expires_at <= now()
            RETURNING id
        '''), {'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id}).mappings().all()
        ids = [r['id'] for r in rows]
        purge_job_ids: dict[str, str | None] = {}
        if ids:
            db.execute(text('''
                UPDATE chunks
                SET active=false, deleted_at=now(), dense_index_status='delete_queued', sparse_index_status='delete_queued'
                WHERE tenant_id=:tenant_id AND business_instance_id=:biz_id
                  AND vector_store_id = ANY(:ids)
                  AND active=true
            '''), {'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'ids': ids})
            for vs_id in ids:
                purge_job_ids[vs_id] = enqueue_purge_stale_vectors(db, principal, vector_store_id=vs_id, reason='vector_store_expired')
            db.execute(jsonb_text('''
                INSERT INTO audit_events(id, tenant_id, business_instance_id, user_id, api_key_id, event_type, action, resource_type, metadata)
                VALUES (:id, :tenant_id, :biz_id, :user_id, :api_key_id, 'maintenance', 'expire_vector_stores', 'vector_store', CAST(:metadata AS jsonb))
            ''', 'metadata'), {
                'id': new_id('aud'),
                'tenant_id': principal.tenant_id,
                'biz_id': principal.business_instance_id,
                'user_id': principal.user_id,
                'api_key_id': principal.api_key_id,
                'metadata': jsonb_param({'vector_store_ids': ids, 'purge_job_ids': purge_job_ids}),
            })
        return MaintenanceResult(action='sweep_expired_vector_stores', processed=len(ids), details={'vector_store_ids': ids, 'purge_job_ids': purge_job_ids})

    async def reindex_chunks(self, db: Session, principal: Principal, req: ReindexRequest) -> MaintenanceResult:
        batch = min(max(req.batch_size or self.settings.svs_reindex_batch_size, 1), 1000)
        params = {'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'limit': batch + 1}
        extra = []
        if req.vector_store_id:
            extra.append('AND c.vector_store_id=:vs_id')
            params['vs_id'] = req.vector_store_id
        if req.document_id:
            extra.append('AND c.document_id=:doc_id')
            params['doc_id'] = req.document_id
        if req.after_chunk_id:
            cursor_extra = []
            if req.vector_store_id:
                cursor_extra.append('AND vector_store_id=:vs_id')
            if req.document_id:
                cursor_extra.append('AND document_id=:doc_id')
            cursor = db.execute(text(f'''
                SELECT created_at
                FROM chunks
                WHERE id=:after_chunk_id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
                  {' '.join(cursor_extra)}
            '''), {**params, 'after_chunk_id': req.after_chunk_id}).mappings().first()
            if not cursor:
                return MaintenanceResult(
                    action='reindex_chunks',
                    processed=0,
                    details={'batch_size': batch, 'has_more': False, 'last_chunk_id': None, 'cursor_missing': req.after_chunk_id},
                )
            params['after_chunk_id'] = req.after_chunk_id
            params['after_created_at'] = cursor['created_at']
            extra.append('AND (c.created_at > :after_created_at OR (c.created_at = :after_created_at AND c.id > :after_chunk_id))')
        status_clause = '' if req.force else "AND (c.dense_index_status <> 'indexed' OR c.sparse_index_status <> 'indexed')"
        selected_rows = db.execute(text(f'''
            SELECT c.id, c.text, c.tenant_id, c.business_instance_id, c.knowledge_base_id, c.vector_store_id,
                   c.document_id, c.document_version_id, c.security_level, c.classification, c.acl_bucket,
                   e.embedding_profile_id, e.model_name, e.dimensions, e.vector_collection, e.vector_point_id
            FROM chunks c JOIN embeddings e ON e.chunk_id=c.id
            WHERE c.tenant_id=:tenant_id AND c.business_instance_id=:biz_id AND c.active=true
              {status_clause} {' '.join(extra)}
            ORDER BY c.created_at ASC, c.id ASC LIMIT :limit
        '''), params).mappings().all()
        has_more = len(selected_rows) > batch
        rows = selected_rows[:batch]
        if not rows:
            return MaintenanceResult(action='reindex_chunks', processed=0, details={'batch_size': batch, 'has_more': False, 'last_chunk_id': None})
        by_profile: dict[str, list] = {}
        for r in rows:
            by_profile.setdefault(r['embedding_profile_id'], []).append(r)
        processed = 0
        for profile_id, group in by_profile.items():
            profile = model_registry().get('models', {}).get(profile_id)
            if not profile:
                raise ProviderConfigurationError(f"Unknown embedding profile: {profile_id}")
            provider = provider_for(profile.get('provider', 'hash_mock'))
            model = profile.get('model') or group[0]['model_name']
            dimensions = int(profile.get('dimensions') or group[0]['dimensions'])
            emb = await provider.embed([r['text'] for r in group], model, dimensions, input_type="document")
            collection = self.qdrant.collection_name(principal.business_instance_id, profile_id)
            points = []
            for r, e in zip(group, emb.data):
                points.append({'id': r['vector_point_id'] or point_uuid(r['id']), 'vector': e.embedding, 'payload': {
                    'tenant_id': r['tenant_id'], 'business_instance_id': r['business_instance_id'], 'knowledge_base_id': r['knowledge_base_id'],
                    'vector_store_id': r['vector_store_id'], 'document_id': r['document_id'], 'document_version_id': r['document_version_id'],
                    'chunk_id': r['id'], 'security_level': r['security_level'], 'classification': r['classification'], 'acl_bucket': r['acl_bucket'],
                    'active': True, 'embedding_profile_id': profile_id,
                }})
            self.qdrant.upsert(collection, points, dimensions)
            if self.settings.svs_sparse_backend == 'opensearch':
                index = self.opensearch.index_name(principal.business_instance_id)
                for r in group:
                    self.opensearch.upsert_chunk(index, r['id'], {
                        'tenant_id': r['tenant_id'], 'business_instance_id': r['business_instance_id'], 'knowledge_base_id': r['knowledge_base_id'],
                        'vector_store_id': r['vector_store_id'], 'document_id': r['document_id'], 'document_version_id': r['document_version_id'],
                        'chunk_id': r['id'], 'security_level': r['security_level'], 'classification': r['classification'], 'acl_bucket': r['acl_bucket'],
                        'active': True, 'embedding_profile_id': profile_id, 'text': r['text'],
                    })
            db.execute(text('''
                UPDATE chunks SET dense_index_status='indexed', sparse_index_status='indexed', last_index_error=NULL, indexed_at=now()
                WHERE id = ANY(:ids) AND tenant_id=:tenant_id AND business_instance_id=:biz_id
            '''), {'ids': [r['id'] for r in group], 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id})
            processed += len(group)
        last_chunk_id = rows[-1]['id']
        db.execute(jsonb_text('''
            INSERT INTO audit_events(id, tenant_id, business_instance_id, user_id, api_key_id, event_type, action, resource_type, metadata)
            VALUES (:id, :tenant_id, :biz_id, :user_id, :api_key_id, 'maintenance', 'reindex_chunks', 'chunk', CAST(:metadata AS jsonb))
        ''', 'metadata'), {'id': new_id('aud'), 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id,
              'user_id': principal.user_id, 'api_key_id': principal.api_key_id, 'metadata': jsonb_param({'processed': processed, 'request': req.model_dump(), 'has_more': has_more, 'last_chunk_id': last_chunk_id})})
        return MaintenanceResult(
            action='reindex_chunks',
            processed=processed,
            details={'batch_size': batch, 'has_more': has_more, 'last_chunk_id': last_chunk_id},
        )
