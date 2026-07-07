from __future__ import annotations

import svs_common.vector_store_repo as vector_store_repo
from svs_common.schemas import Principal
from svs_common.vector_store_repo import VectorStoreRepository


class _Result:
    def __init__(self, row=None, rowcount: int = 1):
        self._row = row
        self.rowcount = rowcount

    def mappings(self):
        return self

    def first(self):
        return self._row


class _Db:
    def __init__(self):
        self.calls: list[str] = []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.calls.append(sql)
        if "SELECT id FROM vector_stores" in sql:
            return _Result({"id": "vs_test"})
        return _Result()


def test_vector_store_delete_sets_system_worker_before_chunk_soft_delete(monkeypatch):
    db = _Db()
    monkeypatch.setattr(vector_store_repo, "enqueue_purge_stale_vectors", lambda *args, **kwargs: "job_test")
    principal = Principal(tenant_id="ten_dev", business_instance_id="biz_dev", max_security_level=5)

    deleted = VectorStoreRepository().delete(db, principal, "vs_test")

    assert deleted is True
    set_config_index = next(i for i, sql in enumerate(db.calls) if "svs.system_worker" in sql)
    chunk_update_index = next(i for i, sql in enumerate(db.calls) if "UPDATE chunks" in sql)
    assert set_config_index < chunk_update_index
