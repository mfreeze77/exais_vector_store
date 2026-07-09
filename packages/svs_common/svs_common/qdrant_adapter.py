from __future__ import annotations
from typing import Any
from .config import get_settings
from .index_versions import index_version_suffix, safe_index_part

class IndexBackendUnavailable(RuntimeError):
    pass

class IndexOperationError(RuntimeError):
    pass

class QdrantAdapter:
    def __init__(self):
        self.settings = get_settings()
        self.client = None
        self.init_error: str | None = None
        try:
            from qdrant_client import QdrantClient
            self.client = QdrantClient(url=self.settings.qdrant_url, api_key=self.settings.qdrant_api_key or None)
        except Exception as exc:
            self.client = None
            self.init_error = str(exc)

    def _require_client(self, operation: str) -> bool:
        if self.client:
            return True
        if self.settings.svs_index_strict:
            raise IndexBackendUnavailable(f"Qdrant unavailable during {operation}: {self.init_error or 'client not initialized'}")
        return False

    def healthcheck(self) -> tuple[bool, str | None]:
        if not self.client:
            return False, self.init_error or "client not initialized"
        try:
            self.client.get_collections()
            return True, None
        except Exception as exc:
            return False, str(exc)

    def collection_name(self, business_instance_id: str, embedding_profile_id: str = "default") -> str:
        safe_biz = safe_index_part(business_instance_id)
        safe_profile = safe_index_part(embedding_profile_id)
        return f"{self.settings.qdrant_collection_prefix}{safe_biz}_{safe_profile}{index_version_suffix(self.settings)}"

    def ensure_collection(self, collection: str, dimensions: int) -> None:
        if not self._require_client("ensure_collection"):
            return
        try:
            from qdrant_client.http.models import Distance, VectorParams
            names = [c.name for c in self.client.get_collections().collections]
            if collection not in names:
                self.client.create_collection(
                    collection_name=collection,
                    vectors_config=VectorParams(size=dimensions, distance=Distance.COSINE, on_disk=True),
                )
        except Exception as exc:
            if self.settings.svs_index_strict:
                raise IndexOperationError(f"Qdrant ensure_collection failed for {collection}: {exc}") from exc

    def upsert(self, collection: str, points: list[dict[str, Any]], dimensions: int) -> None:
        if not points:
            return
        if not self._require_client("upsert"):
            return
        try:
            self.ensure_collection(collection, dimensions)
            from qdrant_client.http.models import PointStruct
            self.client.upsert(collection_name=collection, points=[PointStruct(**p) for p in points])
        except Exception as exc:
            if self.settings.svs_index_strict:
                raise IndexOperationError(f"Qdrant upsert failed for {collection}: {exc}") from exc


    def delete_by_filter(self, collection: str, query_filter: dict[str, Any]) -> int:
        if not self._require_client("delete_by_filter"):
            return 0
        try:
            from qdrant_client.http.models import FilterSelector
            filt = self._filter(query_filter)
            self.client.delete(collection_name=collection, points_selector=FilterSelector(filter=filt), wait=True)
            return 1
        except Exception as exc:
            if self.settings.svs_index_strict:
                raise IndexOperationError(f"Qdrant delete_by_filter failed for {collection}: {exc}") from exc
            return 0

    def delete_points(self, collection: str, point_ids: list[str]) -> int:
        if not point_ids:
            return 0
        if not self._require_client("delete_points"):
            return 0
        try:
            self.client.delete(collection_name=collection, points_selector=point_ids, wait=True)
            return len(point_ids)
        except Exception as exc:
            if self.settings.svs_index_strict:
                raise IndexOperationError(f"Qdrant delete_points failed for {collection}: {exc}") from exc
            return 0

    def _filter(self, query_filter: dict[str, Any]):
        if not query_filter:
            return None
        try:
            from qdrant_client.http.models import Filter
            return Filter(**query_filter)
        except Exception:
            return query_filter

    def search(self, collection: str, query_vector: list[float], query_filter: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
        if not self._require_client("search"):
            return []
        try:
            filt = self._filter(query_filter)
            if hasattr(self.client, "search"):
                results = self.client.search(
                    collection_name=collection,
                    query_vector=query_vector,
                    query_filter=filt,
                    limit=limit,
                    with_payload=True,
                )
            else:
                response = self.client.query_points(
                    collection_name=collection,
                    query=query_vector,
                    query_filter=filt,
                    limit=limit,
                    with_payload=True,
                )
                results = response.points
            return [{"id": str(r.id), "score": float(r.score), "payload": r.payload or {}} for r in results]
        except Exception as exc:
            if self.settings.svs_index_strict:
                raise IndexOperationError(f"Qdrant search failed for {collection}: {exc}") from exc
            return []
