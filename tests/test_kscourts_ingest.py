from __future__ import annotations

import importlib.util
import sys
from argparse import Namespace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release" / "kscourts-ingest.py"
sys.path.insert(0, str(SCRIPT.parent))


def _load_module():
    spec = importlib.util.spec_from_file_location("kscourts_ingest", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["kscourts_ingest"] = module
    spec.loader.exec_module(module)
    return module


def test_marker_fallback_output_preserves_parser_metadata_in_payload():
    ingest = _load_module()
    extraction = ingest.marker_extraction_from_output(
        {
            "text": "# Decision\n\nConverted by Marker",
            "pages": 3,
            "processing_time_seconds": 4.5,
            "output_format": "markdown",
        },
        job_ids=["job-abc"],
        low_text_threshold=5,
    )
    doc = ingest.ManifestDocument(
        row={
            "document_id": "doc-source-1",
            "docket_number": "12345",
            "decision_date": "2026-01-02",
            "court": "Supreme Court",
            "status": "Published",
            "title": "State v. Example",
            "filename": "example.pdf",
            "pdf_url": "https://example.test/example.pdf",
            "saved_path": "data/raw/kscourts-decisions/pdfs/example.pdf",
            "sha256": "abc123",
            "bytes": "1234",
        },
        row_key="row123",
        pdf_path=Path("C:/cases/example.pdf"),
        year="2026",
    )

    payload = ingest.document_payload(
        doc,
        extraction,
        Namespace(knowledge_base_id="kb_dev", security_level=1, force_async=True),
        "vs_test",
    )

    assert payload["mode"] == "pdf_markdown_external_v1"
    assert payload["attributes"]["extraction_parser"] == "runpod_marker"
    assert payload["attributes"]["marker_job_id"] == "job-abc"
    assert payload["attributes"]["marker_pages"] == 3
    assert payload["attributes"]["marker_processing_time_seconds"] == 4.5
    assert payload["attributes"]["docket_number"] == "12345"


def test_poll_counts_accepts_drained_jobs_when_unique_document_count_is_lower(monkeypatch):
    ingest = _load_module()

    def fake_psql(cell, sql, *, tuples_only=False):
        assert cell == "ks-state-civics"
        assert tuples_only is True
        return "0|0|16470|116043|116043"

    monkeypatch.setattr(ingest, "psql", fake_psql)

    counts = ingest.poll_counts(
        "ks-state-civics",
        "vs_a0d3ac76893e4f6f83bf2992",
        expected_new_docs=16714,
        timeout_seconds=1,
    )

    assert counts == {
        "failed_jobs": 0,
        "active_jobs": 0,
        "documents": 16470,
        "active_chunks": 116043,
        "indexed_chunks": 116043,
    }
