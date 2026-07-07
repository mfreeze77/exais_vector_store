from __future__ import annotations
from collections import defaultdict
from typing import Any
from sqlalchemy import text
from sqlalchemy.orm import Session
from .sql import jsonb_text
from .db import jsonb_param
from .ids import new_id
from .schemas import Principal
from .qdrant_adapter import QdrantAdapter
from .opensearch_adapter import OpenSearchAdapter
from .config import get_settings


def enqueue_purge_stale_vectors(
    db: Session,
    principal: Principal,
    *,
    document_version_ids: list[str] | None = None,
    document_id: str | None = None,
    vector_store_id: str | None = None,
    reason: str = 'stale_index_cleanup',
) -> str | None:
    """Queue physical index cleanup after the caller's DB transaction commits."""
    document_version_ids = [v for v in (document_version_ids or []) if v]
    if not document_version_ids and not document_id and not vector_store_id:
        return None
    job_id = new_id('job')
    db.execute(jsonb_text('''
        INSERT INTO ingestion_jobs(id, tenant_id, business_instance_id, job_type, status, priority, payload, max_attempts)
        VALUES (:id, :tenant_id, :biz_id, 'purge_stale_vectors', 'queued', 75, CAST(:payload AS jsonb), 5)
    ''', 'payload'), {
        'id': job_id,
        'tenant_id': principal.tenant_id,
        'biz_id': principal.business_instance_id,
        'payload': jsonb_param({
            'document_version_ids': document_version_ids,
            'document_id': document_id,
            'vector_store_id': vector_store_id,
            'reason': reason,
        }),
    })
    return job_id


class IndexCleanup:
    """Physical cleanup engine for stale external index entries.

    Mutation paths should queue ``purge_stale_vectors`` instead of calling this
    directly before commit. The worker invokes these methods after logical
    deactivation is committed, avoiding non-transactional Qdrant/OpenSearch
    deletes that could remove the last live version during a failed ingest.
    """
    def __init__(self):
        self.settings = get_settings()
        self.qdrant = QdrantAdapter()
        self.opensearch = OpenSearchAdapter()

    def _delete_rows(
        self,
        rows: list[dict[str, Any]],
        principal: Principal,
        *,
        document_id: str | None = None,
        vector_store_id: str | None = None,
        document_version_ids: list[str] | None = None,
    ) -> dict[str, int]:
        deleted_dense = 0
        deleted_sparse = 0
        if self.settings.svs_dense_backend == 'qdrant':
            by_collection: dict[str, list[str]] = defaultdict(list)
            for r in rows:
                if r.get('vector_collection') and r.get('vector_point_id'):
                    by_collection[r['vector_collection']].append(r['vector_point_id'])
            for collection, point_ids in by_collection.items():
                deleted_dense += self.qdrant.delete_points(collection, point_ids)
        if self.settings.svs_sparse_backend == 'opensearch':
            index = self.opensearch.index_name(principal.business_instance_id)
            base = {'tenant_id': principal.tenant_id, 'business_instance_id': principal.business_instance_id}
            if document_version_ids:
                for docv_id in document_version_ids:
                    deleted_sparse += self.opensearch.delete_by_query(index, {**base, 'document_version_id': docv_id})
            else:
                scope = dict(base)
                if document_id:
                    scope['document_id'] = document_id
                if vector_store_id:
                    scope['vector_store_id'] = vector_store_id
                deleted_sparse += self.opensearch.delete_by_query(index, scope)
        return {'dense_points_deleted': deleted_dense, 'sparse_docs_deleted': deleted_sparse}

    def _select_rows(
        self,
        db: Session,
        principal: Principal,
        *,
        document_id: str | None = None,
        vector_store_id: str | None = None,
        document_version_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id}
        clauses = ['c.tenant_id=:tenant_id', 'c.business_instance_id=:biz_id']
        if document_id:
            clauses.append('c.document_id=:doc_id')
            params['doc_id'] = document_id
        if vector_store_id:
            clauses.append('c.vector_store_id=:vs_id')
            params['vs_id'] = vector_store_id
        if document_version_ids:
            clauses.append('c.document_version_id = ANY(:docv_ids)')
            params['docv_ids'] = document_version_ids
        rows = db.execute(text(f'''
            SELECT c.id AS chunk_id, e.vector_collection, e.vector_point_id
            FROM chunks c LEFT JOIN embeddings e ON e.chunk_id=c.id
            WHERE {' AND '.join(clauses)}
        '''), params).mappings().all()
        return [dict(r) for r in rows]

    def delete_by_document(self, db: Session, principal: Principal, document_id: str) -> dict[str, int]:
        rows = self._select_rows(db, principal, document_id=document_id)
        return self._delete_rows(rows, principal, document_id=document_id)

    def delete_by_vector_store(self, db: Session, principal: Principal, vector_store_id: str) -> dict[str, int]:
        rows = self._select_rows(db, principal, vector_store_id=vector_store_id)
        return self._delete_rows(rows, principal, vector_store_id=vector_store_id)

    def delete_by_document_versions(self, db: Session, principal: Principal, document_version_ids: list[str]) -> dict[str, int]:
        document_version_ids = [v for v in document_version_ids if v]
        if not document_version_ids:
            return {'dense_points_deleted': 0, 'sparse_docs_deleted': 0}
        rows = self._select_rows(db, principal, document_version_ids=document_version_ids)
        return self._delete_rows(rows, principal, document_version_ids=document_version_ids)
