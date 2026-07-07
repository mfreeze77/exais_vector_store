from svs_common.index_cleanup import IndexCleanup
from svs_common.schemas import Principal

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

from svs_common.maintenance import MaintenanceService

class CaptureResult:
    def mappings(self):
        return self
    def all(self):
        return []

class CaptureDB:
    def __init__(self):
        self.sql = []
        self.params = []
    def execute(self, stmt, params=None):
        self.sql.append(str(stmt))
        self.params.append(params or {})
        return CaptureResult()

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
