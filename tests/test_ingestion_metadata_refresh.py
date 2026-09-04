from __future__ import annotations

import json

import pytest

from svs_common.ingestion import (
    IngestionService,
    SOURCE_IDENTITY_ATTRIBUTE,
    VECTOR_STORE_FILE_CHUNKING_STRATEGY_ATTRIBUTE,
    _document_version_metadata,
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


def test_source_identity_is_trimmed_and_must_not_be_blank():
    request = DocumentIngestRequest(title="Fiscal report", content="body", source_identity=" id ")
    assert request.source_identity == "id"
    with pytest.raises(ValueError, match="source_identity"):
        DocumentIngestRequest(title="Fiscal report", content="body", source_identity="   ")


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


def test_exact_duplicate_is_scoped_to_source_identity_when_supplied():
    service = object.__new__(IngestionService)
    db = _FakeDb()
    request = _request().model_copy(update={"source_identity": "statecivics:logical-a"})

    service._find_exact_duplicate(db, _principal(), request, "same-bytes")

    sql, params = db.calls[0]
    assert "dv.metadata #>> '{source_identity}' = :source_identity" in sql
    assert params["source_identity"] == "statecivics:logical-a"


def test_equal_bytes_keep_legacy_dedupe_when_no_source_identity_is_supplied():
    service = object.__new__(IngestionService)
    db = _FakeDb()

    service._find_exact_duplicate(db, _principal(), _request(), "same-bytes")

    sql, params = db.calls[0]
    assert "dv.metadata #>> '{source_identity}'" not in sql
    assert "source_identity" not in params


def test_version_target_prefers_stable_identity_over_a_changed_citation_url():
    service = object.__new__(IngestionService)
    db = _FakeDb()
    request = _request().model_copy(update={"source_identity": "statecivics:logical-a"})

    service._find_version_target(db, _principal(), request, "new-bytes")

    sql, params = db.calls[0]
    assert "JOIN document_versions dv" in sql
    assert "dv.metadata #>> '{source_identity}' = :source_identity" in sql
    assert "d.source_uri=:source_uri" not in sql
    assert params["source_identity"] == "statecivics:logical-a"


def test_source_identity_is_persisted_and_exposed_as_retrieval_metadata():
    request = _request().model_copy(
        update={
            "source_identity": "statecivics:logical-a",
            "attributes": {**_request().attributes, "source_identity": "untrusted-duplicate"},
        }
    )

    metadata = _document_version_metadata(request, "markdown_docs_v1")

    assert metadata[SOURCE_IDENTITY_ATTRIBUTE] == "statecivics:logical-a"
    assert metadata["attributes"][SOURCE_IDENTITY_ATTRIBUTE] == "statecivics:logical-a"


def test_link_vector_store_file_uses_first_class_source_identity():
    service = object.__new__(IngestionService)
    db = _FakeDb({"id": "vsf_existing"})
    request = _request().model_copy(update={"source_identity": "statecivics:logical-a"})

    service._link_vector_store_file(db, _principal(), request, "doc_existing")

    _, params = db.calls[1]
    attrs = json.loads(params["attrs"])
    assert attrs[SOURCE_IDENTITY_ATTRIBUTE] == "statecivics:logical-a"
