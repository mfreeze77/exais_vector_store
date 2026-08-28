from __future__ import annotations

import json

from svs_common.ingestion import (
    IngestionService,
    VECTOR_STORE_FILE_CHUNKING_STRATEGY_ATTRIBUTE,
)
from svs_common.schemas import DocumentIngestRequest, Principal


class _Rows:
    def __init__(self, first_row=None):
        self._first_row = first_row

    def mappings(self):
        return self

    def first(self):
        return self._first_row


class _FakeDb:
    def __init__(self, first_row=None):
        self.first_row = first_row
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return _Rows(self.first_row if len(self.calls) == 1 else None)


def _principal() -> Principal:
    return Principal(
        tenant_id="ten",
        business_instance_id="biz",
        user_id="usr",
        max_security_level=5,
    )


def _request() -> DocumentIngestRequest:
    return DocumentIngestRequest(
        vector_store_id="vs",
        knowledge_base_id="kb",
        title="Charter Ordinance 126",
        filename="CharterOrdinance126.md",
        mime_type="text/markdown",
        source_uri="https://files.topeka.gov/community/ordinances/charter/CharterOrdinance126.pdf",
        content="# Charter Ordinance 126\n\nBody",
        attributes={
            "source_collection": "topeka-ordinances",
            "ordinance_number": "126",
            "category": "charter_ordinance",
            "_private_operator_note": "drop",
            VECTOR_STORE_FILE_CHUNKING_STRATEGY_ATTRIBUTE: {"type": "auto"},
        },
        security_level=2,
        classification="tenant_private",
        allowed_groups=["grp"],
        allowed_roles=["reader"],
        source_trust="external_pdf_parser",
    )


def test_link_vector_store_file_refreshes_existing_file_metadata():
    service = object.__new__(IngestionService)
    db = _FakeDb({"id": "vsf_existing"})

    vsf_id = service._link_vector_store_file(db, _principal(), _request(), "doc_existing")

    assert vsf_id == "vsf_existing"
    assert "SELECT id FROM vector_store_files" in db.calls[0][0]
    update_sql, params = db.calls[1]
    assert "UPDATE vector_store_files" in update_sql
    assert "attributes=CAST(:attrs AS jsonb)" in update_sql
    assert params["id"] == "vsf_existing"
    assert params["status"] == "completed"
    assert params["bytes"] == len(_request().content.encode())
    attrs = json.loads(params["attrs"])
    assert attrs["source_collection"] == "topeka-ordinances"
    assert attrs["ordinance_number"] == "126"
    assert attrs["category"] == "charter_ordinance"
    assert "_private_operator_note" not in attrs
    assert VECTOR_STORE_FILE_CHUNKING_STRATEGY_ATTRIBUTE in attrs


def test_refresh_document_metadata_updates_existing_document_identity_fields():
    service = object.__new__(IngestionService)
    db = _FakeDb()

    service._refresh_document_metadata(
        db,
        _principal(),
        _request(),
        "doc_existing",
        content_hash="hash-new",
        current_version_id="docv-new",
    )

    sql, params = db.calls[0]
    assert "UPDATE documents" in sql
    assert "title=:title" in sql
    assert "filename=:filename" in sql
    assert "source_uri=:source_uri" in sql
    assert "content_hash=:hash" in sql
    assert "current_version_id=:docv_id" in sql
    assert params["doc_id"] == "doc_existing"
    assert params["title"] == "Charter Ordinance 126"
    assert params["filename"] == "CharterOrdinance126.md"
    assert params["source_uri"].endswith("CharterOrdinance126.pdf")
    assert params["hash"] == "hash-new"
    assert params["docv_id"] == "docv-new"
