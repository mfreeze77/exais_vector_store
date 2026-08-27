from __future__ import annotations

import asyncio

from svs_api import main as api_main
from svs_common.schemas import DocumentIngestRequest, IngestionJobResponse, Principal


class _Db:
    def __init__(self):
        self.committed = False

    def commit(self):
        self.committed = True


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
