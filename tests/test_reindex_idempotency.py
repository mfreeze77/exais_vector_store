from __future__ import annotations

import asyncio
from types import SimpleNamespace

from svs_common import maintenance as maintenance_mod
from svs_common.ids import point_uuid
from svs_common.maintenance import MaintenanceService
from svs_common.schemas import Principal, ReindexRequest


class _Rows:
    def __init__(self, *, row=None, rows=None):
        self.row = row
        self.rows = list(rows or [])

    def mappings(self):
        return self

    def first(self):
        return self.row

    def all(self):
        return self.rows


class _Db:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls: list[tuple[str, dict]] = []

    def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params or {}))
        if self.results:
            result = self.results.pop(0)
            if isinstance(result, list):
                return _Rows(rows=result)
            return _Rows(row=result)
        return _Rows()


class _Embedding:
    def __init__(self, vector):
        self.embedding = vector


class _EmbeddingResponse:
    provider = "hash_mock"
    model = "deterministic-dev-hash"

    def __init__(self, count: int, dimensions: int):
        self.data = [_Embedding([float(idx + 1)] * dimensions) for idx in range(count)]


class _Provider:
    def __init__(self):
        self.calls = []

    async def embed(self, texts, model, dimensions, input_type="document"):
        self.calls.append({
            "texts": list(texts),
            "model": model,
            "dimensions": dimensions,
            "input_type": input_type,
        })
        return _EmbeddingResponse(len(texts), dimensions)


class _Qdrant:
    def __init__(self):
        self.upserts = []

    def collection_name(self, business_instance_id, embedding_profile_id):
        return f"svs_{business_instance_id}_{embedding_profile_id}"

    def upsert(self, collection, points, dimensions):
        self.upserts.append({
            "collection": collection,
            "points": points,
            "dimensions": dimensions,
        })


class _OpenSearch:
    def __init__(self):
        self.upserts = []

    def index_name(self, business_instance_id):
        return f"svs_{business_instance_id}_chunks"

    def upsert_chunk(self, index, chunk_id, body):
        self.upserts.append({"index": index, "chunk_id": chunk_id, "body": body})


def _principal() -> Principal:
    return Principal(
        tenant_id="tenant",
        business_instance_id="biz",
        user_id="user",
        api_key_id="key",
        scopes=["maintenance:write"],
    )


def _row(chunk_id: str, *, point_id: str | None, text: str = "chunk text"):
    return {
        "id": chunk_id,
        "text": text,
        "tenant_id": "tenant",
        "business_instance_id": "biz",
        "knowledge_base_id": "kb",
        "vector_store_id": "vs_123",
        "document_id": "doc_123",
        "document_version_id": "docv_123",
        "security_level": 1,
        "classification": "internal",
        "acl_bucket": "default",
        "embedding_profile_id": "hash_mock_1536",
        "model_name": "old-model",
        "dimensions": 3,
        "vector_collection": "old_collection",
        "vector_point_id": point_id,
    }


def _service(provider: _Provider, qdrant: _Qdrant, opensearch: _OpenSearch, *, sparse_backend: str = "opensearch") -> MaintenanceService:
    svc = MaintenanceService.__new__(MaintenanceService)
    svc.settings = SimpleNamespace(svs_reindex_batch_size=2, svs_sparse_backend=sparse_backend)
    svc.qdrant = qdrant
    svc.opensearch = opensearch
    return svc


def _patch_registry_and_provider(monkeypatch, provider: _Provider) -> None:
    monkeypatch.setattr(maintenance_mod, "provider_for", lambda provider_name: provider)
    monkeypatch.setattr(maintenance_mod, "model_registry", lambda: {
        "models": {
            "hash_mock_1536": {
                "provider": "hash_mock",
                "model": "deterministic-dev-hash",
                "dimensions": 3,
            }
        }
    })


def test_reindex_chunks_replays_stable_dense_and_sparse_ids(monkeypatch):
    provider = _Provider()
    qdrant = _Qdrant()
    opensearch = _OpenSearch()
    svc = _service(provider, qdrant, opensearch)
    rows = [
        _row("chk_existing", point_id="point_existing", text="alpha"),
        _row("chk_missing_point", point_id=None, text="beta"),
    ]
    db = _Db(results=[rows])
    _patch_registry_and_provider(monkeypatch, provider)

    result = asyncio.run(svc.reindex_chunks(
        db,
        _principal(),
        ReindexRequest(vector_store_id="vs_123", batch_size=2),
    ))

    select_sql, select_params = db.calls[0]
    update_sql, update_params = db.calls[1]
    embedding_sql, embedding_params = db.calls[2]
    audit_sql, audit_params = db.calls[3]

    assert result.action == "reindex_chunks"
    assert result.processed == 2
    assert result.details == {"batch_size": 2, "has_more": False, "last_chunk_id": "chk_missing_point"}
    assert "c.vector_store_id=:vs_id" in select_sql
    assert "c.dense_index_status <> 'indexed' OR c.sparse_index_status <> 'indexed'" in select_sql
    assert select_params["tenant_id"] == "tenant"
    assert select_params["biz_id"] == "biz"
    assert provider.calls == [{
        "texts": ["alpha", "beta"],
        "model": "deterministic-dev-hash",
        "dimensions": 3,
        "input_type": "document",
    }]
    assert qdrant.upserts[0]["collection"] == "svs_biz_hash_mock_1536"
    assert [point["id"] for point in qdrant.upserts[0]["points"]] == [
        "point_existing",
        point_uuid("chk_missing_point"),
    ]
    assert [doc["chunk_id"] for doc in opensearch.upserts] == ["chk_existing", "chk_missing_point"]
    assert "UPDATE chunks SET dense_index_status='indexed', sparse_index_status='indexed'" in update_sql
    assert update_params["ids"] == ["chk_existing", "chk_missing_point"]
    assert "UPDATE embeddings" in embedding_sql
    assert "vector_collection=:collection" in embedding_sql
    assert "vector_point_id=CASE chunk_id" in embedding_sql
    assert embedding_params["collection"] == "svs_biz_hash_mock_1536"
    assert embedding_params["ids"] == ["chk_existing", "chk_missing_point"]
    assert embedding_params["point_id_0"] == "point_existing"
    assert embedding_params["point_id_1"] == point_uuid("chk_missing_point")
    assert "INSERT INTO audit_events" in audit_sql
    assert '"processed":2' in audit_params["metadata"]


def test_forced_reindex_omits_status_filter_for_repair_all(monkeypatch):
    provider = _Provider()
    svc = _service(provider, _Qdrant(), _OpenSearch(), sparse_backend="postgres_fts")
    db = _Db(results=[[_row("chk_force", point_id="point_force")]])
    _patch_registry_and_provider(monkeypatch, provider)

    result = asyncio.run(svc.reindex_chunks(
        db,
        _principal(),
        ReindexRequest(vector_store_id="vs_123", batch_size=1, force=True),
    ))

    select_sql = db.calls[0][0]
    assert result.processed == 1
    assert "dense_index_status <> 'indexed'" not in select_sql
    assert "sparse_index_status <> 'indexed'" not in select_sql


def test_reindex_cursor_missing_returns_without_provider_calls(monkeypatch):
    provider = _Provider()
    svc = _service(provider, _Qdrant(), _OpenSearch())
    db = _Db(results=[None])

    result = asyncio.run(svc.reindex_chunks(
        db,
        _principal(),
        ReindexRequest(vector_store_id="vs_123", after_chunk_id="chk_missing", batch_size=2),
    ))

    cursor_sql, cursor_params = db.calls[0]
    assert result.action == "reindex_chunks"
    assert result.processed == 0
    assert result.details == {
        "batch_size": 2,
        "has_more": False,
        "last_chunk_id": None,
        "cursor_missing": "chk_missing",
    }
    assert "WHERE id=:after_chunk_id AND tenant_id=:tenant_id AND business_instance_id=:biz_id" in " ".join(cursor_sql.split())
    assert "AND vector_store_id=:vs_id" in cursor_sql
    assert cursor_params["after_chunk_id"] == "chk_missing"
    assert provider.calls == []


def test_reindex_reports_has_more_and_cursor_for_multi_batch_repair(monkeypatch):
    provider = _Provider()
    svc = _service(provider, _Qdrant(), _OpenSearch(), sparse_backend="postgres_fts")
    rows = [
        _row("chk_1", point_id="point_1"),
        _row("chk_2", point_id="point_2"),
        _row("chk_3", point_id="point_3"),
    ]
    db = _Db(results=[rows])
    _patch_registry_and_provider(monkeypatch, provider)

    result = asyncio.run(svc.reindex_chunks(
        db,
        _principal(),
        ReindexRequest(vector_store_id="vs_123", batch_size=2, force=True),
    ))

    assert result.processed == 2
    assert result.details == {"batch_size": 2, "has_more": True, "last_chunk_id": "chk_2"}
    assert db.calls[1][1]["ids"] == ["chk_1", "chk_2"]
