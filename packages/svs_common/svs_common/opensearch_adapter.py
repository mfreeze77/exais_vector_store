from __future__ import annotations
from typing import Any
from .config import get_settings
from .openai_compat import file_attribute_payload_key
from .qdrant_adapter import IndexBackendUnavailable, IndexOperationError

class OpenSearchAdapter:
    def __init__(self):
        self.settings = get_settings()
        self.client = None
        self.init_error: str | None = None
        try:
            from opensearchpy import OpenSearch
            use_ssl = self.settings.opensearch_url.startswith("https")
            auth = None if self.settings.opensearch_url.startswith("http://") else (self.settings.opensearch_user, self.settings.opensearch_password)
            self.client = OpenSearch(
                hosts=[self.settings.opensearch_url],
                http_auth=auth,
                use_ssl=use_ssl,
                verify_certs=self.settings.opensearch_verify_certs if use_ssl else False,
            )
        except Exception as exc:
            self.client = None
            self.init_error = str(exc)

    def _require_client(self, operation: str) -> bool:
        if self.client:
            return True
        if self.settings.svs_index_strict:
            raise IndexBackendUnavailable(f"OpenSearch unavailable during {operation}: {self.init_error or 'client not initialized'}")
        return False

    def index_name(self, business_instance_id: str) -> str:
        return f"{self.settings.opensearch_index_prefix}chunks_{business_instance_id.replace('-', '_').lower()}"

    def ensure_index(self, index: str) -> None:
        if not self._require_client("ensure_index"):
            return
        try:
            if self.client.indices.exists(index=index):
                return
            self.client.indices.create(index=index, body={
                "settings": {"index": {"number_of_shards": 1, "number_of_replicas": 0}},
                "mappings": {
                    "dynamic_templates": [
                        {"file_attributes": {"match": "file_attr_*", "mapping": {"type": "keyword"}}}
                    ],
                    "properties": {
                        "tenant_id": {"type": "keyword"},
                        "business_instance_id": {"type": "keyword"},
                        "knowledge_base_id": {"type": "keyword"},
                        "vector_store_id": {"type": "keyword"},
                        "document_id": {"type": "keyword"},
                        "document_version_id": {"type": "keyword"},
                        "chunk_id": {"type": "keyword"},
                        "security_level": {"type": "integer"},
                        "classification": {"type": "keyword"},
                        "acl_bucket": {"type": "keyword"},
                        "active": {"type": "boolean"},
                        "heading_path": {"type": "keyword"},
                        "text": {"type": "text", "analyzer": "standard"},
                    }
                },
            })
        except Exception as exc:
            if self.settings.svs_index_strict:
                raise IndexOperationError(f"OpenSearch ensure_index failed for {index}: {exc}") from exc

    def upsert_chunk(self, index: str, doc_id: str, body: dict[str, Any]) -> None:
        if not self._require_client("upsert_chunk"):
            return
        try:
            self.ensure_index(index)
            self.client.index(index=index, id=doc_id, body=body, refresh=False)
        except Exception as exc:
            if self.settings.svs_index_strict:
                raise IndexOperationError(f"OpenSearch upsert failed for {index}/{doc_id}: {exc}") from exc


    def delete_by_query(self, index: str, scope_filter: dict[str, Any]) -> int:
        if not self._require_client("delete_by_query"):
            return 0
        body = {"query": {"bool": {"filter": [
            {"term": {"tenant_id": scope_filter["tenant_id"]}},
            {"term": {"business_instance_id": scope_filter["business_instance_id"]}},
        ]}}}
        for key in ("vector_store_id", "knowledge_base_id", "document_id", "document_version_id"):
            if scope_filter.get(key):
                body["query"]["bool"]["filter"].append({"term": {key: scope_filter[key]}})
        try:
            resp = self.client.delete_by_query(index=index, body=body, refresh=True, conflicts="proceed")
            return int(resp.get("deleted", 0))
        except Exception as exc:
            if self.settings.svs_index_strict:
                raise IndexOperationError(f"OpenSearch delete_by_query failed for {index}: {exc}") from exc
            return 0

    def search(self, index: str, query: str, scope_filter: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
        if not self._require_client("search"):
            return []
        body = {
            "size": limit,
            "query": {
                "bool": {
                    "must": [{"match": {"text": query}}],
                    "filter": [
                        {"term": {"tenant_id": scope_filter["tenant_id"]}},
                        {"term": {"business_instance_id": scope_filter["business_instance_id"]}},
                        {"term": {"active": True}},
                        {"range": {"security_level": {"lte": scope_filter["max_security_level"]}}},
                    ],
                }
            },
        }
        for key in ("vector_store_id", "knowledge_base_id", "document_id", "classification", "acl_bucket"):
            if scope_filter.get(key):
                body["query"]["bool"]["filter"].append({"term": {key: scope_filter[key]}})
        for key, value in (scope_filter.get("file_attribute_filters") or {}).items():
            body["query"]["bool"]["filter"].append({"term": {file_attribute_payload_key(key): value}})
        try:
            hits = self.client.search(index=index, body=body).get("hits", {}).get("hits", [])
            return [{"id": h["_id"], "score": float(h.get("_score") or 0), "payload": h.get("_source", {})} for h in hits]
        except Exception as exc:
            if self.settings.svs_index_strict:
                raise IndexOperationError(f"OpenSearch search failed for {index}: {exc}") from exc
            return []
