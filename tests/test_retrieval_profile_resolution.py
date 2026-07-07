from svs_common.retrieval import RetrievalService
from svs_common.schemas import Principal, SearchRequest
from svs_common.security import build_retrieval_scope


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def all(self):
        return self.rows


class _Db:
    def __init__(self, rows):
        self.rows = rows
        self.sql = ""
        self.params = {}

    def execute(self, sql, params):
        self.sql = str(sql)
        self.params = params
        return _Rows(self.rows)


def test_search_embedding_profile_comes_from_indexed_vector_store_chunks():
    service = RetrievalService.__new__(RetrievalService)
    db = _Db([{"embedding_profile_id": "openai_text_embedding_3_small_1536"}])
    principal = Principal(tenant_id="tenant", business_instance_id="biz-dev", max_security_level=5)
    scope = build_retrieval_scope(principal)
    req = SearchRequest(query="proof", vector_store_id="vs_scale", mode="markdown_docs_v1")

    profiles = service._embedding_profiles_for_search(db, scope, req, {"vector_store_id": "vs_scale"})

    assert profiles == ["openai_text_embedding_3_small_1536"]
    assert "c.vector_store_id" in db.sql
    assert db.params["vector_store_id"] == "vs_scale"
    assert db.params["max_lvl"] == 5
