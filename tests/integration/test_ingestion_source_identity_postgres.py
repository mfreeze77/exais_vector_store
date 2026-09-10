from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text

from svs_common.db import set_rls_context
from svs_common.ingestion import IngestionService
from svs_common.schemas import DocumentIngestRequest, Principal


DSN = os.getenv("SVS_TEST_SOURCE_IDENTITY_DSN", "").strip()
pytestmark = pytest.mark.skipif(
    not DSN,
    reason="SVS_TEST_SOURCE_IDENTITY_DSN must name a disposable migrated PostgreSQL database",
)


def _principal() -> Principal:
    return Principal(
        tenant_id="ten_dev",
        business_instance_id="biz_dev",
        user_id="usr_dev",
        max_security_level=5,
    )


def _request(identity: str, *, content: str) -> DocumentIngestRequest:
    return DocumentIngestRequest(
        vector_store_id="vs_dev",
        knowledge_base_id="kb_dev",
        title="Fiscal identity proof",
        filename="fiscal-proof.md",
        mime_type="text/markdown",
        content=content,
        source_uri="https://budget.kansas.gov/moved/fiscal-proof.pdf",
        source_identity=identity,
    )


def _seed_indexed_document(
    connection, *, suffix: str, identity: str, content_hash: str
) -> str:
    document_id = f"doc_identity_{suffix}"
    version_id = f"docv_identity_{suffix}"
    chunk_id = f"chk_identity_{suffix}"
    connection.execute(
        text(
            """
            INSERT INTO documents(
              id, tenant_id, business_instance_id, knowledge_base_id, vector_store_id,
              title, filename, mime_type, source_uri, content_hash, current_version_id
            ) VALUES (
              :doc_id, 'ten_dev', 'biz_dev', 'kb_dev', 'vs_dev',
              'Fiscal identity proof', 'fiscal-proof.md', 'text/markdown',
              'https://budget.kansas.gov/original/fiscal-proof.pdf', :content_hash, NULL
            )
            """
        ),
        {"doc_id": document_id, "content_hash": content_hash},
    )
    connection.execute(
        text(
            """
            INSERT INTO document_versions(
              id, document_id, tenant_id, business_instance_id, version_number,
              parser_profile_id, vectorization_profile_id, embedding_profile_id,
              chunking_profile_id, source_content_hash, metadata, status
            ) VALUES (
              :version_id, :doc_id, 'ten_dev', 'biz_dev', 1,
              'markdown', 'markdown_docs_v1', 'embedding_local_dev',
              'markdown_heading_hierarchy_v2', :content_hash,
              CAST(:metadata AS jsonb), 'indexed'
            )
            """
        ),
        {
            "version_id": version_id,
            "doc_id": document_id,
            "content_hash": content_hash,
            "metadata": f'{{"source_identity":"{identity}"}}',
        },
    )
    connection.execute(
        text("UPDATE documents SET current_version_id=:version_id WHERE id=:doc_id"),
        {"version_id": version_id, "doc_id": document_id},
    )
    connection.execute(
        text(
            """
            INSERT INTO chunks(
              id, tenant_id, business_instance_id, knowledge_base_id, vector_store_id,
              document_id, document_version_id, ordinal, text, text_hash,
              dense_index_status, sparse_index_status
            ) VALUES (
              :chunk_id, 'ten_dev', 'biz_dev', 'kb_dev', 'vs_dev',
              :doc_id, :version_id, 0, 'proof', 'proof-hash', 'indexed', 'indexed'
            )
            """
        ),
        {"chunk_id": chunk_id, "doc_id": document_id, "version_id": version_id},
    )
    return document_id


def test_equal_bytes_remain_distinct_and_identity_survives_a_url_change() -> None:
    engine = create_engine(DSN)
    suffix = uuid.uuid4().hex[:12]
    identity_a = f"statecivics:{suffix}:a"
    identity_b = f"statecivics:{suffix}:b"
    shared_hash = "a" * 64
    service = object.__new__(IngestionService)
    principal = _principal()
    try:
        with engine.begin() as connection:
            set_rls_context(connection, principal)
            document_a = _seed_indexed_document(
                connection,
                suffix=f"{suffix}_a",
                identity=identity_a,
                content_hash=shared_hash,
            )
            document_b = _seed_indexed_document(
                connection,
                suffix=f"{suffix}_b",
                identity=identity_b,
                content_hash=shared_hash,
            )

            exact_a = service._find_exact_duplicate(
                connection,
                principal,
                _request(identity_a, content="same bytes"),
                shared_hash,
            )
            exact_b = service._find_exact_duplicate(
                connection,
                principal,
                _request(identity_b, content="same bytes"),
                shared_hash,
            )
            no_cross_identity_match = service._find_exact_duplicate(
                connection,
                principal,
                _request(f"statecivics:{suffix}:c", content="same bytes"),
                shared_hash,
            )
            version_target = service._find_version_target(
                connection,
                principal,
                _request(identity_a, content="changed bytes"),
                "b" * 64,
            )

            assert exact_a["id"] == document_a
            assert exact_b["id"] == document_b
            assert no_cross_identity_match is None
            assert version_target["id"] == document_a
    finally:
        with engine.begin() as connection:
            set_rls_context(connection, principal)
            connection.execute(
                text("DELETE FROM documents WHERE id LIKE :prefix"),
                {"prefix": f"doc_identity_{suffix}%"},
            )
        engine.dispose()
