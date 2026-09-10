from __future__ import annotations

import asyncio

from svs_api import main as api_main
from svs_common.schemas import DocumentIngestRequest, IngestionJobResponse, Principal


class _Db:
    def __init__(self):
        self.committed = False

    def commit(self):
        self.committed = True


class _Upload:
    filename = "fiscal-proof.md"
    content_type = "text/markdown"

    async def read(self):
        return b"# Fiscal proof\n\nBody"


class _PdfUpload:
    filename = "fiscal-proof.pdf"
    content_type = "application/pdf"

    async def read(self):
        return b"%PDF-1.7\nFiscal proof"


def test_ingest_document_restores_rls_context_before_idempotency_store(monkeypatch):
    events: list[str] = []
    principal = Principal(tenant_id="tenant", business_instance_id="biz", user_id="user", scopes=["documents:write"])
    db = _Db()
    req = DocumentIngestRequest(
        vector_store_id="vs_123",
        knowledge_base_id="kb_dev",
        title="Kansas proof",
        content="body",
        attributes={"force_async": True},
    )

    async def fake_ingest_or_enqueue(request, request_principal, request_db):
        assert request is req
        assert request_principal is principal
        assert request_db is db
        events.append("ingest_or_enqueue")
        return IngestionJobResponse(id="job_123", status="queued")

    def fake_set_rls_context(request_db, request_principal):
        assert request_db is db
        assert request_principal is principal
        events.append("set_rls_context")

    def fake_store_idempotency(request_db, request_principal, key, fingerprint, response):
        assert request_db is db
        assert request_principal is principal
        assert key == "idem_123"
        assert response["id"] == "job_123"
        events.append("store_idempotency")

    monkeypatch.setattr(api_main, "enforce_rate_limit", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_main, "check_idempotency", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_main, "ingest_or_enqueue", fake_ingest_or_enqueue)
    monkeypatch.setattr(api_main, "set_rls_context", fake_set_rls_context)
    monkeypatch.setattr(api_main, "store_idempotency", fake_store_idempotency)

    result = asyncio.run(api_main.ingest_document(req, idempotency_key="idem_123", principal=principal, db=db))

    assert result["id"] == "job_123"
    assert db.committed is True
    assert events == ["ingest_or_enqueue", "set_rls_context", "store_idempotency"]


def test_upload_document_carries_source_identity_and_stores_idempotency(monkeypatch):
    events: list[str] = []
    captured: dict[str, object] = {}
    principal = Principal(
        tenant_id="tenant",
        business_instance_id="biz",
        user_id="user",
        scopes=["documents:write"],
    )
    db = _Db()

    async def fake_ingest_or_enqueue(req, request_principal, request_db):
        assert request_principal is principal
        assert request_db is db
        captured["request"] = req
        events.append("ingest_or_enqueue")
        return IngestionJobResponse(
            id="job_upload",
            status="completed",
            document_id="doc_upload",
            vector_store_file_id="vsf_upload",
        )

    def fake_store_idempotency(request_db, request_principal, key, fingerprint, response):
        assert request_db is db
        assert request_principal is principal
        assert key == "fiscal-idempotency"
        assert fingerprint
        assert response["vector_store_file_id"] == "vsf_upload"
        events.append("store_idempotency")

    monkeypatch.setattr(api_main, "enforce_rate_limit", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_main, "check_idempotency", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_main, "is_marker_pdf_upload", lambda *args, **kwargs: False)
    monkeypatch.setattr(api_main, "ingest_or_enqueue", fake_ingest_or_enqueue)
    monkeypatch.setattr(api_main, "set_rls_context", lambda *args: events.append("set_rls_context"))
    monkeypatch.setattr(api_main, "store_idempotency", fake_store_idempotency)

    result = asyncio.run(
        api_main.upload_document(
            file=_Upload(),
            title="Fiscal proof",
            mode="markdown_docs_v1",
            vector_store_id="vs_fiscal",
            knowledge_base_id="kb_civics",
            security_level=0,
            classification="public",
            source_uri="https://budget.kansas.gov/fiscal-proof.pdf",
            source_identity="statecivics:logical-document",
            attributes_json='{"source_revision_id":"revision-1"}',
            idempotency_key="fiscal-idempotency",
            principal=principal,
            db=db,
        )
    )

    request = captured["request"]
    assert isinstance(request, DocumentIngestRequest)
    assert request.source_uri == "https://budget.kansas.gov/fiscal-proof.pdf"
    assert request.source_identity == "statecivics:logical-document"
    assert request.attributes["source_revision_id"] == "revision-1"
    assert request.classification == "public"
    assert result["document_id"] == "doc_upload"
    assert db.committed is True
    assert events == ["ingest_or_enqueue", "set_rls_context", "store_idempotency"]


def test_cached_pdf_upload_returns_before_marker(monkeypatch):
    principal = Principal(
        tenant_id="tenant",
        business_instance_id="biz",
        user_id="user",
        scopes=["documents:write"],
    )
    cached = {
        "id": "job_cached",
        "status": "completed",
        "document_id": "doc_cached",
        "vector_store_file_id": "vsf_cached",
    }

    async def forbidden_marker(**kwargs):
        raise AssertionError("an idempotent replay must not consume another Marker job")

    monkeypatch.setattr(api_main, "enforce_rate_limit", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_main, "check_idempotency", lambda *args, **kwargs: cached)
    monkeypatch.setattr(api_main, "marker_pdf_upload_request", forbidden_marker)

    result = asyncio.run(
        api_main.upload_document(
            file=_PdfUpload(),
            title="Fiscal proof",
            mode="auto_detect_v1",
            vector_store_id="vs_fiscal",
            knowledge_base_id="kb_civics",
            security_level=0,
            classification="public",
            source_uri="https://budget.kansas.gov/fiscal-proof.pdf",
            source_identity="statecivics:logical-document",
            attributes_json='{"source_revision_id":"revision-1"}',
            idempotency_key="fiscal-idempotency",
            principal=principal,
            db=_Db(),
        )
    )

    assert result == cached
