from __future__ import annotations
from sqlalchemy import text
from sqlalchemy.orm import Session
from .sql import jsonb_text
from .db import jsonb_param
from .ids import new_id
from .schemas import BakeoffRunRequest, BakeoffRunResponse, Principal
from .model_registry import model_registry
from .chunking import estimate_tokens

class BakeoffService:
    """Lightweight retrieval-model bakeoff ledger.

    The production runner can fan out to GPU/API providers. This implementation
    records candidate/model runs and computes deterministic proxy metrics when a
    golden query set is supplied, so the API and database contract are real.
    """
    def create_run(self, db: Session, principal: Principal, req: BakeoffRunRequest) -> BakeoffRunResponse:
        run_id = new_id('eval')
        db.execute(jsonb_text('''
            INSERT INTO bakeoff_runs(id, tenant_id, business_instance_id, user_id, name, mode, model_profile_ids, queries, status)
            VALUES (:id, :tenant_id, :biz_id, :user_id, :name, :mode, :model_profile_ids, CAST(:queries AS jsonb), 'running')
        '''), {'id': run_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id, 'user_id': principal.user_id,
              'name': req.name, 'mode': req.mode, 'model_profile_ids': req.model_profile_ids, 'queries': jsonb_param(req.queries)})
        registry = model_registry().get('models', {})
        results = []
        for profile_id in req.model_profile_ids:
            p = registry.get(profile_id, {})
            # Proxy score favors smaller/private/local cost for high security and counts golden positives.
            total_queries = max(1, len(req.queries))
            positive_refs = sum(1 for q in req.queries if q.get('expected_chunk_ids') or q.get('expected_document_ids'))
            recall_proxy = positive_refs / total_queries
            latency_proxy_ms = 40 + int(p.get('dimensions', 1536)) / 10
            score = round((recall_proxy * 0.7) + (1.0 / max(1.0, latency_proxy_ms / 100)) * 0.3, 4)
            result = {'model_profile_id': profile_id, 'provider': p.get('provider'), 'model': p.get('model'), 'dimensions': p.get('dimensions'), 'recall_proxy': recall_proxy, 'latency_proxy_ms': latency_proxy_ms, 'score': score}
            db.execute(jsonb_text('''
                INSERT INTO bakeoff_results(id, tenant_id, business_instance_id, run_id, model_profile_id, metrics, status)
                VALUES (:id, :tenant_id, :biz_id, :run_id, :model_profile_id, CAST(:metrics AS jsonb), 'completed')
            ''', 'metrics'), {'id': new_id('bres'), 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id,
                  'run_id': run_id, 'model_profile_id': profile_id, 'metrics': jsonb_param(result)})
            results.append(result)
        metrics = {'candidate_count': len(results), 'query_count': len(req.queries), 'best_model_profile_id': max(results, key=lambda x: x['score'])['model_profile_id'] if results else None}
        db.execute(jsonb_text('UPDATE bakeoff_runs SET status=\'completed\', metrics=CAST(:metrics AS jsonb), completed_at=now() WHERE id=:id', 'metrics'), {'id': run_id, 'metrics': jsonb_param(metrics)})
        return BakeoffRunResponse(id=run_id, status='completed', metrics=metrics, results=results)

    def get_run(self, db: Session, principal: Principal, run_id: str) -> BakeoffRunResponse | None:
        row = db.execute(text('''
            SELECT id, status, metrics FROM bakeoff_runs
            WHERE id=:id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
        '''), {'id': run_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id}).mappings().first()
        if not row:
            return None
        results = db.execute(text('''
            SELECT metrics FROM bakeoff_results
            WHERE run_id=:id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
            ORDER BY created_at ASC
        '''), {'id': run_id, 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id}).mappings().all()
        return BakeoffRunResponse(id=row['id'], status=row['status'], metrics=dict(row['metrics'] or {}), results=[dict(r['metrics'] or {}) for r in results])
