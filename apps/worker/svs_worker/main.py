from __future__ import annotations
import asyncio, os, traceback
from sqlalchemy import text
from svs_common.db import scoped_session, set_rls_context
from svs_common.schemas import Principal, DocumentIngestRequest, ReindexRequest
from svs_common.ingestion import IngestionService
from svs_common.maintenance import MaintenanceService
from svs_common.config import get_settings
from svs_common.config import validate_production_guardrails

WORKER_ID = os.getenv('HOSTNAME', 'svs-worker')
POLL_SECONDS = float(os.getenv('SVS_WORKER_POLL_SECONDS', '5'))
get_settings().validate_runtime_guards()


def _system_principal(row) -> Principal:
    return Principal(tenant_id=row['tenant_id'], business_instance_id=row['business_instance_id'], roles=['system'], max_security_level=5, scopes=['system', '*'])


def _update_batch_count(db, row, status: str) -> None:
    payload = row['payload']
    batch_id = payload.get('file_batch_id') if isinstance(payload, dict) else None
    if not batch_id:
        return
    target = 'completed' if status == 'completed' else 'failed' if status == 'failed' else 'cancelled'
    db.execute(text(f'''
        UPDATE file_batches
        SET file_counts = jsonb_set(
              jsonb_set(file_counts, '{{{target}}}', ((coalesce((file_counts->>'{target}')::int,0)+1)::text)::jsonb),
              '{{in_progress}}', (greatest(coalesce((file_counts->>'in_progress')::int,0)-1,0)::text)::jsonb
            ),
            status = CASE WHEN greatest(coalesce((file_counts->>'in_progress')::int,0)-1,0)=0 THEN :final_status ELSE status END,
            completed_at = CASE WHEN greatest(coalesce((file_counts->>'in_progress')::int,0)-1,0)=0 THEN now() ELSE completed_at END
        WHERE id=:batch_id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
    '''), {'batch_id': batch_id, 'tenant_id': row['tenant_id'], 'biz_id': row['business_instance_id'], 'final_status': 'completed' if status == 'completed' else 'failed'})


async def process_once() -> bool:
    ingestion = IngestionService()
    maintenance = MaintenanceService()
    with scoped_session() as db:
        db.execute(text("SELECT set_config('svs.system_worker', 'true', true)"))
        row = db.execute(text('''
            UPDATE ingestion_jobs SET status='running', locked_by=:worker, locked_at=now(), attempts=attempts+1, updated_at=now()
            WHERE id = (
              SELECT id FROM ingestion_jobs WHERE status='queued' AND attempts < max_attempts
              ORDER BY priority ASC, created_at ASC
              FOR UPDATE SKIP LOCKED LIMIT 1
            )
            RETURNING *
        '''), {'worker': WORKER_ID}).mappings().first()
        if not row:
            return False
        principal = _system_principal(row)
        set_rls_context(db, principal)
        try:
            # Each job attempt runs inside a SAVEPOINT beneath the outer
            # transaction that claimed the job. If ingestion/indexing raises,
            # SQLAlchemy rolls back only the partial document/version/chunk
            # writes while preserving attempts, lock ownership, and retry
            # accounting in the outer transaction.
            with db.begin_nested():
                payload = row['payload'] or {}
                if row['job_type'] == 'document_ingest':
                    if isinstance(payload, dict) and 'document' in payload:
                        req = DocumentIngestRequest.model_validate(payload['document'])
                        req.attributes['_file_batch_id'] = payload.get('file_batch_id')
                    else:
                        req = DocumentIngestRequest.model_validate(payload)
                    await ingestion.ingest_now(db, principal, req)
                elif row['job_type'] == 'reindex_chunks':
                    await maintenance.reindex_chunks(db, principal, ReindexRequest.model_validate(payload or {}))
                elif row['job_type'] == 'expire_vector_stores':
                    maintenance.sweep_expired_vector_stores(db, principal)
                elif row['job_type'] == 'purge_stale_vectors':
                    maintenance.purge_stale_vectors(db, principal, payload or {})
                else:
                    raise ValueError(f'Unsupported job_type: {row["job_type"]}')
            db.execute(text("UPDATE ingestion_jobs SET status='completed', completed_at=now(), updated_at=now() WHERE id=:id"), {'id': row['id']})
            _update_batch_count(db, row, 'completed')
        except Exception as exc:
            err = ''.join(traceback.format_exception_only(type(exc), exc)).strip()
            terminal = row['attempts'] >= row['max_attempts']
            db.execute(text("""
                UPDATE ingestion_jobs SET status=:status, last_error=:err, updated_at=now(), locked_by=NULL, locked_at=NULL
                WHERE id=:id
            """), {'id': row['id'], 'err': err, 'status': 'failed' if terminal else 'queued'})
            if terminal:
                _update_batch_count(db, row, 'failed')
            print(f'job {row["id"]} failed: {err}')
        return True


async def main():
    validate_production_guardrails()
    print(f'SVS worker {WORKER_ID} starting')
    while True:
        if not await process_once():
            await asyncio.sleep(POLL_SECONDS)

if __name__ == '__main__':
    asyncio.run(main())
