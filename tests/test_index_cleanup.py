from svs_common.index_cleanup import IndexCleanup
from svs_common.schemas import Principal
from svs_api import main as api_main
from svs_common.maintenance import MaintenanceService

class FakeResult:
    def __init__(self, rows):
        self._rows = rows
    def mappings(self):
        return self
    def all(self):
        return self._rows

class FakeDB:
    def execute(self, *_args, **_kwargs):
        return FakeResult([
            {'chunk_id': 'chk1', 'vector_collection': 'c1', 'vector_point_id': 'p1'},
            {'chunk_id': 'chk2', 'vector_collection': 'c1', 'vector_point_id': 'p2'},
            {'chunk_id': 'chk3', 'vector_collection': 'c2', 'vector_point_id': 'p3'},
        ])

class FakeQdrant:
    def __init__(self):
        self.calls = []
    def delete_points(self, collection, point_ids):
        self.calls.append((collection, list(point_ids)))
        return len(point_ids)

class FakeOpenSearch:
    def __init__(self):
        self.calls = []
    def index_name(self, biz):
        return 'idx_' + biz
    def delete_by_query(self, index, scope):
        self.calls.append((index, dict(scope)))
        return 7

def test_delete_by_document_removes_dense_points_and_sparse_docs():
    cleanup = IndexCleanup()
    cleanup.settings.svs_dense_backend = 'qdrant'
    cleanup.settings.svs_sparse_backend = 'opensearch'
    cleanup.qdrant = FakeQdrant()
    cleanup.opensearch = FakeOpenSearch()
    p = Principal(tenant_id='ten', business_instance_id='biz')
    result = cleanup.delete_by_document(FakeDB(), p, 'doc1')
    assert result == {'dense_points_deleted': 3, 'sparse_docs_deleted': 7}
    assert cleanup.qdrant.calls == [('c1', ['p1', 'p2']), ('c2', ['p3'])]
    assert cleanup.opensearch.calls[0][1]['document_id'] == 'doc1'

class CaptureResult:
    def __init__(self, rows=None):
        self._rows = list(rows or [])
    def mappings(self):
        return self
    def all(self):
        return self._rows

class CaptureDB:
    def __init__(self, rows=None):
        self.sql = []
        self.params = []
        self.rows = list(rows or [])
        self.committed = False
    def execute(self, stmt, params=None):
        self.sql.append(str(stmt))
        self.params.append(params or {})
        rows = self.rows.pop(0) if self.rows else []
        return CaptureResult(rows)
    def commit(self):
        self.committed = True

class FakeCleanupEngine:
    def __init__(self):
        self.docv_calls = []
    def delete_by_document_versions(self, db, principal, document_version_ids):
        self.docv_calls.append(list(document_version_ids))
        return {'dense_points_deleted': 2, 'sparse_docs_deleted': 1}
    def delete_by_document(self, db, principal, document_id):
        return {'dense_points_deleted': 0, 'sparse_docs_deleted': 0}
    def delete_by_vector_store(self, db, principal, vector_store_id):
        return {'dense_points_deleted': 0, 'sparse_docs_deleted': 0}

def test_purge_stale_vectors_marks_queued_chunks_deleted_without_chunk_updated_at():
    svc = MaintenanceService()
    fake = FakeCleanupEngine()
    svc.index_cleanup = fake
    db = CaptureDB()
    p = Principal(tenant_id='ten', business_instance_id='biz')
    result = svc.purge_stale_vectors(db, p, {'document_version_ids': ['docv_old'], 'reason': 'test'})
    assert fake.docv_calls == [['docv_old']]
    assert result.action == 'purge_stale_vectors'
    assert result.processed == 3
    joined = '\n'.join(db.sql)
    assert "dense_index_status='deleted'" in joined
    assert 'deleted_at=coalesce(deleted_at, now())' in joined
    assert 'updated_at=now()' not in joined


def test_sweep_expired_vector_stores_deactivates_chunks_and_queues_purge(monkeypatch):
    svc = MaintenanceService()
    db = CaptureDB(rows=[[{'id': 'vs_expired_1'}, {'id': 'vs_expired_2'}]])
    p = Principal(tenant_id='ten', business_instance_id='biz', user_id='user', api_key_id='ak')
    enqueued = []

    def fake_enqueue(db_session, principal, *, vector_store_id, reason, **kwargs):
        enqueued.append((vector_store_id, reason, kwargs))
        return f'job_{vector_store_id}'

    monkeypatch.setattr('svs_common.maintenance.enqueue_purge_stale_vectors', fake_enqueue)

    result = svc.sweep_expired_vector_stores(db, p)

    assert result.action == 'sweep_expired_vector_stores'
    assert result.processed == 2
    assert result.details == {
        'vector_store_ids': ['vs_expired_1', 'vs_expired_2'],
        'purge_job_ids': {
            'vs_expired_1': 'job_vs_expired_1',
            'vs_expired_2': 'job_vs_expired_2',
        },
    }
    assert enqueued == [
        ('vs_expired_1', 'vector_store_expired', {}),
        ('vs_expired_2', 'vector_store_expired', {}),
    ]
    joined = '\n'.join(db.sql)
    assert "UPDATE vector_stores SET status='expired'" in joined
    assert "status IN ('active','completed')" in joined
    assert 'expires_at IS NOT NULL AND expires_at <= now()' in joined
    assert "UPDATE chunks" in joined
    assert "active=false" in joined
    assert "dense_index_status='delete_queued'" in joined
    assert "sparse_index_status='delete_queued'" in joined
    assert "expire_vector_stores" in joined
    assert db.params[0] == {'tenant_id': 'ten', 'biz_id': 'biz'}
    assert db.params[1] == {'tenant_id': 'ten', 'biz_id': 'biz', 'ids': ['vs_expired_1', 'vs_expired_2']}


def test_expire_vector_stores_route_requires_scope_and_commits(monkeypatch):
    expected = {'action': 'sweep_expired_vector_stores', 'processed': 0, 'details': {}}

    class FakeMaintenance:
        def sweep_expired_vector_stores(self, db, principal):
            assert principal.tenant_id == 'ten'
            return expected

    monkeypatch.setattr(api_main, 'maintenance', FakeMaintenance())
    db = CaptureDB()

    result = api_main.expire_vector_stores(
        principal=Principal(tenant_id='ten', business_instance_id='biz', scopes=['maintenance:write']),
        db=db,
    )

    assert result == expected
    assert db.committed is True

    try:
        api_main.expire_vector_stores(
            principal=Principal(tenant_id='ten', business_instance_id='biz', scopes=['retrieval:read']),
            db=CaptureDB(),
        )
    except Exception as exc:
        assert getattr(exc, 'status_code', None) == 403
    else:
        raise AssertionError('missing maintenance:write scope should fail')
