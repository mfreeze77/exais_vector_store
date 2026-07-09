from __future__ import annotations
from sqlalchemy import text
from sqlalchemy.orm import Session
from .sql import jsonb_text
from .db import jsonb_param
from .ids import new_id
from .schemas import BakeoffRunRequest, BakeoffRunResponse, Principal
from .model_registry import model_registry
from .evals import golden_retrieval_metrics

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
            latency_proxy_ms = 40 + int(p.get('dimensions', 1536)) / 10
            metrics = golden_retrieval_metrics(req.queries, profile_id, k=req.top_k)
            if metrics['result_source'] == 'golden_results':
                leakage_penalty = min(int(metrics.get('leakage_count') or 0), 10) * 0.1
                score = round(max(
                    0.0,
                    (metrics['recall_at_k'] * 0.45)
                    + (metrics['mrr'] * 0.25)
                    + (metrics['ndcg_at_k'] * 0.2)
                    + (metrics['precision_at_k'] * 0.1)
                    - leakage_penalty,
                ), 4)
            else:
                # Proxy score favors smaller/private/local cost and counts golden positives until a runner supplies results.
                total_queries = max(1, len(req.queries))
                positive_refs = sum(
                    1 for q in req.queries if q.get('expected_chunk_ids') or q.get('expected_document_ids')
                )
                metrics['recall_proxy'] = positive_refs / total_queries
                score = round(
                    (metrics['recall_proxy'] * 0.7)
                    + (1.0 / max(1.0, latency_proxy_ms / 100)) * 0.3,
                    4,
                )
            result = {
                'model_profile_id': profile_id,
                'provider': p.get('provider'),
                'model': p.get('model'),
                'dimensions': p.get('dimensions'),
                'latency_proxy_ms': latency_proxy_ms,
                'score': score,
                **metrics,
            }
            db.execute(jsonb_text('''
                INSERT INTO bakeoff_results(id, tenant_id, business_instance_id, run_id, model_profile_id, metrics, status)
                VALUES (:id, :tenant_id, :biz_id, :run_id, :model_profile_id, CAST(:metrics AS jsonb), 'completed')
            ''', 'metrics'), {'id': new_id('bres'), 'tenant_id': principal.tenant_id, 'biz_id': principal.business_instance_id,
                  'run_id': run_id, 'model_profile_id': profile_id, 'metrics': jsonb_param(result)})
            results.append(result)
        metrics = {
            'candidate_count': len(results),
            'query_count': len(req.queries),
            'metric_source': 'golden_results' if any(
                result.get('result_source') == 'golden_results' for result in results
            ) else 'proxy',
            'best_model_profile_id': max(results, key=lambda x: x['score'])['model_profile_id'] if results else None,
        }
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
