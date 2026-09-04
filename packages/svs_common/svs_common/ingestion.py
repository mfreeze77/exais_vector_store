from __future__ import annotations
from sqlalchemy import text
from sqlalchemy.orm import Session
from .sql import jsonb_text
from .db import jsonb_param
from .schemas import DocumentIngestRequest, IngestionJobResponse, Principal
from .ids import new_id, point_uuid
from .hashing import sha256_text
from .chunking import choose_chunker
from .model_registry import resolve_vectorization_profile, model_registry
from .vectorization_router import build_ingestion_plan
from .providers import ProviderConfigurationError, provider_for
from .qdrant_adapter import QdrantAdapter
from .opensearch_adapter import OpenSearchAdapter
from .object_store import ObjectStore
from .index_cleanup import enqueue_purge_stale_vectors
from .openai_compat import file_attribute_payload, safe_file_attributes
from .vector_store_repo import refresh_vector_store_activity, require_active_vector_store

OPENAI_FILE_ID_ATTRIBUTE = "_openai_file_id"
VECTOR_STORE_FILE_CHUNKING_STRATEGY_ATTRIBUTE = "_openai_chunking_strategy"
SOURCE_IDENTITY_ATTRIBUTE = "source_identity"


def _request_attributes(req: DocumentIngestRequest) -> dict:
    attributes = dict(req.attributes)
    if req.source_identity:
        # The first-class field governs ingest identity. Mirror it into public
        # retrieval metadata so an indexed passage can be traced back to its
        # source manifest without requiring database access.
        attributes[SOURCE_IDENTITY_ATTRIBUTE] = req.source_identity
    return attributes


def _document_version_metadata(req: DocumentIngestRequest, mode_id: str) -> dict:
    metadata = {"mode": mode_id, "attributes": _request_attributes(req)}
    if req.source_identity:
        metadata[SOURCE_IDENTITY_ATTRIBUTE] = req.source_identity
    return metadata


def embedding_profile_config(embedding_profile_id: str, registry: dict | None = None) -> dict:
    profiles = registry if registry is not None else model_registry().get("models", {})
    profile = profiles.get(embedding_profile_id)
    if not profile:
        raise ProviderConfigurationError(f"Unknown embedding profile: {embedding_profile_id}")
    return profile


def validate_embedding_provider_response(embedding_profile_id: str, expected_provider: str, actual_provider: str) -> None:
    if expected_provider != "hash_mock" and actual_provider == "hash_mock":
        raise ProviderConfigurationError(
            f"Embedding profile {embedding_profile_id} returned hash_mock vectors for real provider {expected_provider}"
        )


class IngestionService:
    def __init__(self):
        self.qdrant = QdrantAdapter()
        self.opensearch = OpenSearchAdapter()
        self.object_store = ObjectStore()

    def enqueue(self, db: Session, principal: Principal, req: DocumentIngestRequest, file_batch_id: str | None = None) -> IngestionJobResponse:
        job_id = new_id("job")
        payload = req.model_dump() if not file_batch_id else {"document": req.model_dump(), "file_batch_id": file_batch_id}
        db.execute(jsonb_text("""
            INSERT INTO ingestion_jobs(id, tenant_id, business_instance_id, job_type, status, payload)
            VALUES (:id, :tenant_id, :biz_id, 'document_ingest', 'queued', CAST(:payload AS jsonb))
        """, 'payload'), {"id": job_id, "tenant_id": principal.tenant_id, "biz_id": principal.business_instance_id, "payload": jsonb_param(payload)})
        return IngestionJobResponse(id=job_id, status="queued")

    def _link_vector_store_file(self, db: Session, principal: Principal, req: DocumentIngestRequest, document_id: str, *, status: str = "completed") -> str | None:
        if not req.vector_store_id:
            return None
        file_attrs = {
            k: v for k, v in _request_attributes(req).items()
            if not k.startswith("_") or k == VECTOR_STORE_FILE_CHUNKING_STRATEGY_ATTRIBUTE
        }
        usage_bytes = len(req.content.encode())
        existing = db.execute(text("""
            SELECT id FROM vector_store_files
            WHERE tenant_id=:tenant_id AND business_instance_id=:biz_id
              AND vector_store_id=:vs_id AND document_id=:doc_id
            LIMIT 1
        """), {"tenant_id": principal.tenant_id, "biz_id": principal.business_instance_id, "vs_id": req.vector_store_id, "doc_id": document_id}).mappings().first()
        if existing:
            db.execute(jsonb_text("""
                UPDATE vector_store_files
                SET status=:status,
                    attributes=CAST(:attrs AS jsonb),
                    usage_bytes=:bytes,
                    last_error=NULL,
                    completed_at=CASE WHEN :status='completed' THEN now() ELSE completed_at END,
                    file_batch_id=COALESCE(:file_batch_id, file_batch_id)
                WHERE id=:id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
            """, 'attrs'), {
                "id": existing["id"],
                "tenant_id": principal.tenant_id,
                "biz_id": principal.business_instance_id,
                "status": status,
                "attrs": jsonb_param(file_attrs),
                "bytes": usage_bytes,
                "file_batch_id": req.attributes.get("_file_batch_id"),
            })
            return existing["id"]
        vsf_id = new_id("vsf")
        db.execute(jsonb_text("""
            INSERT INTO vector_store_files(id, tenant_id, business_instance_id, vector_store_id, document_id, file_batch_id, status, attributes, usage_bytes, completed_at)
            VALUES (:id, :tenant_id, :biz_id, :vs_id, :doc_id, :file_batch_id, :status, CAST(:attrs AS jsonb), :bytes, now())
        """, 'attrs'), {"id": vsf_id, "tenant_id": principal.tenant_id, "biz_id": principal.business_instance_id, "vs_id": req.vector_store_id, "doc_id": document_id, "file_batch_id": req.attributes.get("_file_batch_id"), "status": status, "attrs": jsonb_param(file_attrs), "bytes": usage_bytes})
        return vsf_id

    def _refresh_document_metadata(
        self,
        db: Session,
        principal: Principal,
        req: DocumentIngestRequest,
        document_id: str,
        *,
        content_hash: str | None = None,
        current_version_id: str | None = None,
    ) -> None:
        assignments = [
            "title=:title",
            "filename=:filename",
            "mime_type=:mime_type",
            "source_uri=:source_uri",
            "security_level=:security_level",
            "classification=:classification",
            "allowed_groups=:allowed_groups",
            "allowed_roles=:allowed_roles",
            "source_trust=:source_trust",
            "status='active'",
            "updated_at=now()",
        ]
        params = {
            "doc_id": document_id,
            "tenant_id": principal.tenant_id,
            "biz_id": principal.business_instance_id,
            "title": req.title,
            "filename": req.filename,
            "mime_type": req.mime_type,
            "source_uri": req.source_uri,
            "security_level": req.security_level,
            "classification": req.classification,
            "allowed_groups": req.allowed_groups,
            "allowed_roles": req.allowed_roles,
            "source_trust": req.source_trust,
        }
        if content_hash is not None:
            assignments.append("content_hash=:hash")
            params["hash"] = content_hash
        if current_version_id is not None:
            assignments.append("current_version_id=:docv_id")
            params["docv_id"] = current_version_id
        db.execute(text(f"""
            UPDATE documents
            SET {", ".join(assignments)}
            WHERE id=:doc_id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
        """), params)

    def _find_exact_duplicate(self, db: Session, principal: Principal, req: DocumentIngestRequest, content_hash: str):
        # Dedupe is only safe when the target document's current version is
        # fully indexed in every retrieval backend. This prevents a failed
        # attempt that inserted rows but never committed vectors from being
        # treated as a successful prior ingest on retry.
        identity_clause = ""
        params = {
            "tenant_id": principal.tenant_id,
            "biz_id": principal.business_instance_id,
            "kb_id": req.knowledge_base_id,
            "vs_id": req.vector_store_id,
            "hash": content_hash,
        }
        if req.source_identity:
            # Equal bytes are not sufficient identity. Two official documents
            # can legitimately publish the same content and remain separate
            # evidence. When a connector supplies a stable identity, dedupe is
            # scoped to that identity as well as the content hash.
            identity_clause = "AND dv.metadata #>> '{source_identity}' = :source_identity"
            params["source_identity"] = req.source_identity
        return db.execute(text(f"""
            SELECT d.id, d.current_version_id
            FROM documents d
            JOIN document_versions dv
              ON dv.id = d.current_version_id
             AND dv.document_id = d.id
             AND dv.tenant_id = d.tenant_id
             AND dv.business_instance_id = d.business_instance_id
            WHERE d.tenant_id=:tenant_id AND d.business_instance_id=:biz_id
              AND d.knowledge_base_id IS NOT DISTINCT FROM :kb_id
              AND d.vector_store_id IS NOT DISTINCT FROM :vs_id
              AND d.content_hash=:hash AND d.status='active'
              AND dv.status='indexed'
              {identity_clause}
              AND EXISTS (
                SELECT 1 FROM chunks c
                WHERE c.document_id=d.id
                  AND c.document_version_id=d.current_version_id
                  AND c.tenant_id=d.tenant_id
                  AND c.business_instance_id=d.business_instance_id
                  AND c.active=true
                  AND c.dense_index_status='indexed'
                  AND c.sparse_index_status='indexed'
              )
              AND NOT EXISTS (
                SELECT 1 FROM chunks c
                WHERE c.document_id=d.id
                  AND c.document_version_id=d.current_version_id
                  AND c.tenant_id=d.tenant_id
                  AND c.business_instance_id=d.business_instance_id
                  AND c.active=true
                  AND (c.dense_index_status <> 'indexed' OR c.sparse_index_status <> 'indexed')
            )
            ORDER BY d.created_at DESC LIMIT 1
        """), params).mappings().first()

    def _find_version_target(self, db: Session, principal: Principal, req: DocumentIngestRequest, content_hash: str):
        join = ""
        if req.source_identity:
            # Source identity is stable across content and citation URL changes;
            # source_uri is a citation and may legitimately move.
            join = """
                JOIN document_versions dv
                  ON dv.id = d.current_version_id
                 AND dv.document_id = d.id
                 AND dv.tenant_id = d.tenant_id
                 AND dv.business_instance_id = d.business_instance_id
            """
            clause = "dv.metadata #>> '{source_identity}' = :source_identity"
            params = {"source_identity": req.source_identity}
        elif req.source_uri:
            clause = "d.source_uri=:source_uri"
            params = {"source_uri": req.source_uri}
        elif req.filename:
            clause = "d.filename=:filename"
            params = {"filename": req.filename}
        else:
            return None
        params.update({"tenant_id": principal.tenant_id, "biz_id": principal.business_instance_id, "kb_id": req.knowledge_base_id, "vs_id": req.vector_store_id, "hash": content_hash})
        return db.execute(text(f"""
            SELECT d.id, d.current_version_id FROM documents d
            {join}
            WHERE d.tenant_id=:tenant_id AND d.business_instance_id=:biz_id
              AND d.knowledge_base_id IS NOT DISTINCT FROM :kb_id
              AND d.vector_store_id IS NOT DISTINCT FROM :vs_id
              AND {clause}
              AND d.content_hash <> :hash AND d.status='active'
            ORDER BY d.created_at DESC LIMIT 1
        """), params).mappings().first()

    async def ingest_now(self, db: Session, principal: Principal, req: DocumentIngestRequest) -> IngestionJobResponse:
        if req.vector_store_id:
            require_active_vector_store(db, principal, req.vector_store_id)
        content_hash = sha256_text(req.content)

        if not req.attributes.get(OPENAI_FILE_ID_ATTRIBUTE):
            exact = self._find_exact_duplicate(db, principal, req, content_hash)
            if exact:
                self._refresh_document_metadata(db, principal, req, exact["id"])
                vsf_id = self._link_vector_store_file(db, principal, req, exact["id"], status="completed")
                if req.vector_store_id:
                    if not refresh_vector_store_activity(db, principal, req.vector_store_id):
                        require_active_vector_store(db, principal, req.vector_store_id)
                return IngestionJobResponse(id=new_id("job"), status="deduplicated", document_id=exact["id"], vector_store_file_id=vsf_id)

        plan = build_ingestion_plan(principal, req)
        mode_id, mode = resolve_vectorization_profile(req.filename, req.mime_type, req.mode, req.attributes)
        embedding_profile_id = plan.embedding_profile_id
        registry = model_registry().get("models", {})
        emb_profile = embedding_profile_config(embedding_profile_id, registry)
        dimensions = int(emb_profile.get("dimensions", 1536))
        expected_provider = emb_profile.get("provider", "hash_mock")
        provider = provider_for(expected_provider)
        model_name = emb_profile.get("model", "deterministic-dev-hash")

        version_target = self._find_version_target(db, principal, req, content_hash)
        superseded_version_ids: list[str] = []
        if version_target:
            doc_id = version_target["id"]
            old_rows = db.execute(text("""
                SELECT id FROM document_versions
                WHERE document_id=:doc_id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
                  AND status <> 'superseded'
            """), {"doc_id": doc_id, "tenant_id": principal.tenant_id, "biz_id": principal.business_instance_id}).mappings().all()
            superseded_version_ids = [r["id"] for r in old_rows]
            row = db.execute(text("""
                SELECT coalesce(max(version_number), 0) + 1 AS next_version
                FROM document_versions WHERE document_id=:doc_id
            """), {"doc_id": doc_id}).mappings().first()
            version_number = int(row["next_version"])
            db.execute(text("""
                UPDATE chunks
                SET active=false, deleted_at=now(), dense_index_status='delete_queued', sparse_index_status='delete_queued'
                WHERE document_id=:doc_id AND tenant_id=:tenant_id AND business_instance_id=:biz_id
            """), {"doc_id": doc_id, "tenant_id": principal.tenant_id, "biz_id": principal.business_instance_id})
        else:
            doc_id = new_id("doc")
            version_number = 1

        docv_id = new_id("docv")
        object_key = f"tenants/{principal.tenant_id}/business/{principal.business_instance_id}/documents/{doc_id}/original/v{version_number}/{req.filename or 'content.md'}"
        parsed_key = f"tenants/{principal.tenant_id}/business/{principal.business_instance_id}/documents/{doc_id}/parsed/{docv_id}.md"
        self.object_store.put_text(object_key, req.content, req.mime_type or "text/markdown")
        self.object_store.put_text(parsed_key, req.content, "text/markdown")

        if version_target:
            self._refresh_document_metadata(
                db,
                principal,
                req,
                doc_id,
                content_hash=content_hash,
                current_version_id=docv_id,
            )
        else:
            db.execute(text("""
                INSERT INTO documents(id, tenant_id, business_instance_id, knowledge_base_id, vector_store_id, title, filename,
                  mime_type, source_uri, content_hash, security_level, classification, allowed_groups, allowed_roles,
                  source_trust, current_version_id)
                VALUES (:id, :tenant_id, :biz_id, :kb_id, :vs_id, :title, :filename, :mime_type, :source_uri, :hash,
                  :security_level, :classification, :allowed_groups, :allowed_roles, :source_trust, :docv_id)
            """), {
                "id": doc_id, "tenant_id": principal.tenant_id, "biz_id": principal.business_instance_id,
                "kb_id": req.knowledge_base_id, "vs_id": req.vector_store_id, "title": req.title,
                "filename": req.filename, "mime_type": req.mime_type, "source_uri": req.source_uri,
                "hash": content_hash, "security_level": req.security_level, "classification": req.classification,
                "allowed_groups": req.allowed_groups, "allowed_roles": req.allowed_roles, "source_trust": req.source_trust,
                "docv_id": docv_id,
            })

        version_metadata = _document_version_metadata(req, mode_id)
        db.execute(jsonb_text("""
            INSERT INTO document_versions(id, document_id, tenant_id, business_instance_id, version_number, object_key,
              parsed_object_key, parser_profile_id, vectorization_profile_id, embedding_profile_id, chunking_profile_id,
              source_content_hash, metadata, status)
            VALUES (:id, :doc_id, :tenant_id, :biz_id, :version_number, :object_key, :parsed_key, :parser, :mode_id,
              :embedding_profile_id, :chunker, :hash, CAST(:metadata AS jsonb), 'indexing')
        """, 'metadata'), {
            "id": docv_id, "doc_id": doc_id, "tenant_id": principal.tenant_id, "biz_id": principal.business_instance_id,
            "version_number": version_number, "object_key": object_key, "parsed_key": parsed_key, "parser": mode.get("parser", "markdown_ast_v1"),
            "mode_id": mode_id, "embedding_profile_id": embedding_profile_id, "chunker": mode.get("chunker", "markdown_heading_hierarchy_v2"),
            "hash": content_hash, "metadata": jsonb_param(version_metadata),
        })

        parsed_chunks = choose_chunker(mode_id)(req.content)
        if not parsed_chunks:
            raise ValueError("No chunks produced from document content")
        embeddings = await provider.embed([c.text for c in parsed_chunks], model_name, dimensions, input_type="document")
        validate_embedding_provider_response(embedding_profile_id, expected_provider, embeddings.provider)
        collection = self.qdrant.collection_name(principal.business_instance_id, embedding_profile_id)
        os_index = self.opensearch.index_name(principal.business_instance_id)
        acl_bucket = sha256_text("|".join(sorted(req.allowed_groups + req.allowed_roles)) or "default")[:16]
        request_attributes = _request_attributes(req)
        file_attrs = safe_file_attributes(request_attributes)
        file_attr_payload = file_attribute_payload(request_attributes)
        points: list[dict] = []
        sparse_docs: list[tuple[str, dict]] = []
        chunk_ids: list[str] = []

        for c, e in zip(parsed_chunks, embeddings.data):
            chunk_id = new_id("chk")
            chunk_ids.append(chunk_id)
            qdrant_point_id = point_uuid(chunk_id)
            db.execute(jsonb_text("""
                INSERT INTO chunks(id, tenant_id, business_instance_id, knowledge_base_id, vector_store_id, document_id,
                  document_version_id, ordinal, heading_path, page_start, page_end, char_start, char_end, token_count, text,
                  text_hash, metadata, security_level, classification, allowed_groups, allowed_roles, acl_bucket,
                  dense_index_status, sparse_index_status)
                VALUES (:id, :tenant_id, :biz_id, :kb_id, :vs_id, :doc_id, :docv_id, :ordinal, :heading_path,
                  :page_start, :page_end, :char_start, :char_end, :token_count, :text, :text_hash, CAST(:metadata AS jsonb),
                  :security_level, :classification, :allowed_groups, :allowed_roles, :acl_bucket, 'pending', 'pending')
            """, 'metadata'), {
                "id": chunk_id, "tenant_id": principal.tenant_id, "biz_id": principal.business_instance_id,
                "kb_id": req.knowledge_base_id, "vs_id": req.vector_store_id, "doc_id": doc_id, "docv_id": docv_id,
                "ordinal": c.ordinal, "heading_path": c.heading_path, "page_start": c.page_start, "page_end": c.page_end,
                "char_start": c.char_start, "char_end": c.char_end, "token_count": c.token_count, "text": c.text,
                "text_hash": sha256_text(c.text), "metadata": jsonb_param(c.metadata), "security_level": req.security_level,
                "classification": req.classification, "allowed_groups": req.allowed_groups, "allowed_roles": req.allowed_roles,
                "acl_bucket": acl_bucket,
            })
            db.execute(text("""
                INSERT INTO embeddings(id, chunk_id, tenant_id, business_instance_id, embedding_profile_id, model_provider,
                  model_name, dimensions, vector_point_id, vector_collection, input_hash, status)
                VALUES (:id, :chunk_id, :tenant_id, :biz_id, :embedding_profile_id, :provider, :model, :dimensions,
                  :point_id, :collection, :input_hash, 'pending')
            """), {
                "id": new_id("emb"), "chunk_id": chunk_id, "tenant_id": principal.tenant_id, "biz_id": principal.business_instance_id,
                "embedding_profile_id": embedding_profile_id, "provider": embeddings.provider, "model": embeddings.model, "dimensions": dimensions,
                "point_id": qdrant_point_id, "collection": collection, "input_hash": sha256_text(c.text),
            })
            payload = {"tenant_id": principal.tenant_id, "business_instance_id": principal.business_instance_id,
                       "knowledge_base_id": req.knowledge_base_id, "vector_store_id": req.vector_store_id,
                       "document_id": doc_id, "document_version_id": docv_id, "chunk_id": chunk_id,
                       "security_level": req.security_level, "classification": req.classification,
                       "acl_bucket": acl_bucket, "active": True, "embedding_profile_id": embedding_profile_id,
                       "file_attributes": file_attrs, **file_attr_payload}
            points.append({"id": qdrant_point_id, "vector": e.embedding, "payload": payload})
            sparse_docs.append((chunk_id, {**payload, "text": c.text, "heading_path": c.heading_path}))

        # Strict adapters raise here. Because the API/worker transaction has not committed yet,
        # failed dense/sparse writes will not leave this document marked searchable in Postgres.
        self.qdrant.upsert(collection, points, dimensions)
        if self.qdrant.settings.svs_sparse_backend == "opensearch":
            for chunk_id, body in sparse_docs:
                self.opensearch.upsert_chunk(os_index, chunk_id, body)
        # Postgres FTS is generated from the chunk text, so it is indexed at commit time.

        db.execute(text("""
            UPDATE chunks SET dense_index_status='indexed', sparse_index_status='indexed', indexed_at=now()
            WHERE id = ANY(:ids) AND tenant_id=:tenant_id AND business_instance_id=:biz_id
        """), {"ids": chunk_ids, "tenant_id": principal.tenant_id, "biz_id": principal.business_instance_id})
        db.execute(text("""
            UPDATE embeddings SET status='active'
            WHERE chunk_id = ANY(:ids) AND tenant_id=:tenant_id AND business_instance_id=:biz_id
        """), {"ids": chunk_ids, "tenant_id": principal.tenant_id, "biz_id": principal.business_instance_id})
        db.execute(text("UPDATE document_versions SET status='indexed' WHERE id=:id"), {"id": docv_id})
        if superseded_version_ids:
            db.execute(text("""
                UPDATE document_versions
                SET status='superseded', superseded_by_version_id=:new_docv_id
                WHERE id = ANY(:old_docv_ids) AND tenant_id=:tenant_id AND business_instance_id=:biz_id
            """), {"new_docv_id": docv_id, "old_docv_ids": superseded_version_ids, "tenant_id": principal.tenant_id, "biz_id": principal.business_instance_id})
            enqueue_purge_stale_vectors(db, principal, document_version_ids=superseded_version_ids, reason='document_version_superseded')
        db.execute(jsonb_text("""
            INSERT INTO usage_events(id, tenant_id, business_instance_id, user_id, api_key_id, event_type, quantity, unit, provider, model, metadata)
            VALUES (:id, :tenant_id, :biz_id, :user_id, :api_key_id, 'ingestion.chunks_indexed', :quantity, 'chunk', :provider, :model, CAST(:metadata AS jsonb))
        """, 'metadata'), {"id": new_id("use"), "tenant_id": principal.tenant_id, "biz_id": principal.business_instance_id, "user_id": principal.user_id,
              "api_key_id": principal.api_key_id,
              "quantity": len(chunk_ids), "provider": embeddings.provider, "model": embeddings.model,
              "metadata": jsonb_param({"document_id": doc_id, "document_version_id": docv_id, "vector_store_id": req.vector_store_id, "mode": mode_id})})

        vsf_id = self._link_vector_store_file(db, principal, req, doc_id, status="completed")
        # Keep vector-store usage/materialized activity current for billing and expiration.
        if req.vector_store_id:
            if not refresh_vector_store_activity(db, principal, req.vector_store_id, usage_bytes_delta=len(req.content.encode())):
                require_active_vector_store(db, principal, req.vector_store_id)
        return IngestionJobResponse(id=new_id("job"), status="completed", document_id=doc_id, vector_store_file_id=vsf_id)
