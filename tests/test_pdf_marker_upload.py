from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from svs_api import main as api_main
from svs_common.marker_client import MarkerRunpodError, pdf_source_id
from svs_common.schemas import Principal


class FakeUpload:
    filename = "Panel Schedule.pdf"
    content_type = "application/pdf"


class FakeObjectStore:
    def __init__(self) -> None:
        self.writes: list[tuple[str, bytes, str]] = []

    def put_bytes(self, key: str, body: bytes, content_type: str = "application/octet-stream") -> str:
        self.writes.append((key, body, content_type))
        return key


def run(coro):
    return asyncio.run(coro)


def principal() -> Principal:
    return Principal(
        tenant_id="ten_test",
        business_instance_id="biz_test",
        user_id="usr_test",
        max_security_level=3,
        scopes=["documents:write"],
    )


def test_marker_pdf_upload_request_builds_pdf_markdown_ingest(monkeypatch: pytest.MonkeyPatch):
    raw_pdf = b"%PDF-1.4 panel schedule"
    fake_store = FakeObjectStore()

    class FakeMarkerClient:
        async def process_pdf_bytes(self, *, filename, pdf_bytes, job_id_callback=None):
            assert filename == "Panel Schedule.pdf"
            assert pdf_bytes == raw_pdf
            if job_id_callback:
                job_id_callback("job-xyz")
            return {
                "text": "<!-- page: 7 -->\n# Panel Schedule\nCircuit rows",
                "pages": 7,
                "output_format": "markdown",
                "metadata": {
                    "marker_version": "test",
                    "api_key": "must-not-copy",
                    "secret_note": "must-not-copy",
                },
            }

    monkeypatch.setattr(api_main, "MarkerRunpodClient", lambda: FakeMarkerClient())
    monkeypatch.setattr(api_main, "ObjectStore", lambda: fake_store)

    req = run(
        api_main.marker_pdf_upload_request(
            file=FakeUpload(),
            content_bytes=raw_pdf,
            title=None,
            mode="auto_detect_v1",
            vector_store_id="vs_test",
            knowledge_base_id="kb_test",
            security_level=2,
            principal=principal(),
            source_uri="https://budget.kansas.gov/fy2027.pdf",
            source_identity="statecivics:logical-document",
            attributes={"source_revision_id": "revision-1"},
            classification="public",
        )
    )

    assert req.vector_store_id == "vs_test"
    assert req.knowledge_base_id == "kb_test"
    assert req.filename == "Panel-Schedule.md"
    assert req.mime_type == "text/markdown"
    assert req.mode == "pdf_markdown_external_v1"
    assert req.source_trust == "external_pdf_parser"
    assert req.source_uri == "https://budget.kansas.gov/fy2027.pdf"
    assert req.source_identity == "statecivics:logical-document"
    assert req.classification == "public"
    assert "<!-- page: 7 -->" in req.content
    assert req.attributes["source_revision_id"] == "revision-1"
    assert req.attributes["source_pdf_id"] == pdf_source_id(raw_pdf)
    assert req.attributes["source_pdf_filename"] == "Panel Schedule.pdf"
    assert req.attributes["pdf_parser"] == "runpod_marker"
    assert req.attributes["marker_job_id"] == "job-xyz"
    assert req.attributes["marker_pages"] == 7
    assert req.attributes["marker_metadata"] == {"marker_version": "test"}
    assert "api_key" not in req.attributes["marker_metadata"]
    assert "secret_note" not in req.attributes["marker_metadata"]

    assert len(fake_store.writes) == 1
    source_key, body, content_type = fake_store.writes[0]
    assert source_key.startswith("tenants/ten_test/business/biz_test/source-pdfs/")
    assert source_key.endswith("/Panel-Schedule.pdf")
    assert body == raw_pdf
    assert content_type == "application/pdf"


def test_upload_attributes_require_a_json_object():
    assert api_main._document_upload_attributes(None) == {}
    assert api_main._document_upload_attributes('{"source_revision_id":"revision-1"}') == {
        "source_revision_id": "revision-1"
    }
    for value in ("not-json", "[]"):
        with pytest.raises(HTTPException) as exc_info:
            api_main._document_upload_attributes(value)
        assert exc_info.value.status_code == 422


def test_marker_pdf_upload_request_reports_missing_config(monkeypatch: pytest.MonkeyPatch):
    class MissingMarkerClient:
        async def process_pdf_bytes(self, **kwargs):
            raise MarkerRunpodError("Marker RunPod transport is not configured")

    monkeypatch.setattr(api_main, "MarkerRunpodClient", lambda: MissingMarkerClient())

    with pytest.raises(HTTPException) as exc_info:
        run(
            api_main.marker_pdf_upload_request(
                file=FakeUpload(),
                content_bytes=b"%PDF",
                title=None,
                mode="auto_detect_v1",
                vector_store_id=None,
                knowledge_base_id=None,
                security_level=1,
                principal=principal(),
            )
        )

    assert exc_info.value.status_code == 503
    assert "not configured" in str(exc_info.value.detail)
