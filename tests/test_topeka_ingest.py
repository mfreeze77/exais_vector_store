from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "scripts" / "release"
sys.path.insert(0, str(RELEASE))


def load_script(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, RELEASE / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_codified_ingest_maps_section_citation_url_to_source_uri(tmp_path):
    module = load_script("topeka_code_ingest", "topeka-code-ingest.py")
    section = {
        "id": "ks-topeka:tmc:18.55.010",
        "jurisdiction_id": "ks-topeka",
        "code": "TMC",
        "citation": "18.55.010",
        "title": "Definitions",
        "source_url": "https://topeka.municipal.codes/TMC/18.55.010",
        "text": "Structure means anything constructed or erected.",
        "content_hash": "abc123",
        "source_html_hash": "html123",
        "version": {"ordinance": "20345", "passed_date": "2025-01-01"},
    }
    write_jsonl(tmp_path / "sections.jsonl", [section])
    write_jsonl(tmp_path / "citation-url-map.jsonl", [{
        "record_type": "section",
        "id": section["id"],
        "citation_url": section["source_url"],
        "source_url": section["source_url"],
    }])

    payloads = module.load_section_payloads(tmp_path, vector_store_id="vs_topeka", knowledge_base_id="kb", security_level=2)

    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["mode"] == "markdown_docs_v1"
    assert payload["source_uri"] == "https://topeka.municipal.codes/TMC/18.55.010"
    assert payload["attributes"]["citation_url"] == payload["source_uri"]
    assert payload["attributes"]["version_ordinance"] == "20345"
    assert payload["security_level"] == 2


def test_codified_ingest_fails_when_citation_map_is_missing_section(tmp_path):
    module = load_script("topeka_code_ingest_missing", "topeka-code-ingest.py")
    write_jsonl(tmp_path / "sections.jsonl", [{"id": "section-1", "citation": "1.01.010", "title": "Missing", "source_url": "https://topeka.municipal.codes/TMC/1.01.010", "text": "x"}])
    write_jsonl(tmp_path / "citation-url-map.jsonl", [])

    with pytest.raises(ValueError, match="missing section rows"):
        module.load_section_payloads(tmp_path, vector_store_id="vs", knowledge_base_id="kb", security_level=1)


def test_codified_ingest_idempotency_key_is_vector_store_specific():
    module = load_script("topeka_code_ingest_idempotency", "topeka-code-ingest.py")
    payload = {
        "vector_store_id": "vs_one",
        "source_uri": "https://topeka.municipal.codes/TMC/18.55.010",
        "attributes": {"content_hash": "abc123"},
    }
    same_source_other_store = {
        **payload,
        "vector_store_id": "vs_two",
    }

    assert module.ingest_idempotency_key(payload) == module.ingest_idempotency_key(payload)
    assert module.ingest_idempotency_key(payload) != module.ingest_idempotency_key(same_source_other_store)


def test_ordinance_ingest_uses_pdf_url_and_precomputed_markdown(tmp_path):
    module = load_script("topeka_ordinance_pdf_ingest", "topeka-ordinance-pdf-ingest.py")
    manifest = tmp_path / "manifests" / "ordinances.jsonl"
    markdown = tmp_path / "extracted" / "20345.md"
    markdown.parent.mkdir(parents=True)
    markdown.write_text("# Ordinance 20345\n\nAmending section 18.55.010.", encoding="utf-8")
    write_jsonl(manifest, [{
        "id": "ord-20345",
        "ordinance_number": "20345",
        "title": "Ordinance No. 20345",
        "category": "ordinance",
        "year": "2025",
        "pdf_url": "https://topeka.gov/ordinance-20345.pdf",
        "saved_path": "raw/pdfs/20345.pdf",
        "sha256": "pdfhash",
        "byte_count": 1200,
    }])

    payloads, skipped = module.load_ordinance_payloads(
        manifest,
        extracted_dir=tmp_path / "extracted",
        vector_store_id="vs_topeka",
        knowledge_base_id="kb",
        security_level=1,
        allow_missing_markdown=False,
    )

    assert skipped == []
    assert payloads[0]["mode"] == "pdf_markdown_external_v1"
    assert payloads[0]["source_uri"] == "https://topeka.gov/ordinance-20345.pdf"
    assert payloads[0]["attributes"]["extraction_source"] == "precomputed_markdown"


def test_ordinance_ingest_reports_missing_markdown_as_external_marker_precondition(tmp_path):
    module = load_script("topeka_ordinance_pdf_ingest_missing", "topeka-ordinance-pdf-ingest.py")
    manifest = tmp_path / "manifests" / "ordinances.jsonl"
    write_jsonl(manifest, [{"id": "ord-1", "pdf_url": "https://topeka.gov/ord-1.pdf"}])

    with pytest.raises(ValueError, match="Run the external RunPod Marker"):
        module.load_ordinance_payloads(
            manifest,
            extracted_dir=tmp_path / "extracted",
            vector_store_id="vs",
            knowledge_base_id="kb",
            security_level=1,
            allow_missing_markdown=False,
        )


def test_common_docker_network_transport_targets_cell_api_service(monkeypatch):
    common = load_script("topeka_pipeline_common_transport", "topeka_pipeline_common.py")
    captured = {}

    def fake_run(args, *, input, stdout, stderr, timeout):
        captured["args"] = args
        captured["input"] = input
        captured["timeout"] = timeout
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=b'{"ok": true}\n200\n')

    monkeypatch.setattr(common.shutil, "which", lambda name: "docker" if name == "docker" else None)
    monkeypatch.setattr(common.subprocess, "run", fake_run)

    result = common.api_json(
        "POST",
        "http://127.0.0.1:28080",
        "/api/v1/documents/ingest",
        {"x": 1},
        headers={"Content-Type": "application/json", "Authorization": "Bearer secret"},
        timeout=7,
        cell="ks-state-civics",
        transport="docker-network",
    )

    assert result == {"ok": True}
    assert captured["timeout"] == 7
    assert captured["input"] == b'{"x": 1}'
    assert "--network" in captured["args"]
    assert "exais-vector-store-ks-state-civics_default" in captured["args"]
    assert captured["args"][-1] == "http://api:8080/api/v1/documents/ingest"


def test_common_docker_network_transport_uses_direct_http_without_docker_cli(monkeypatch):
    common = load_script("topeka_pipeline_common_direct_transport", "topeka_pipeline_common.py")
    captured = {}

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"ok": true}'

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(common.shutil, "which", lambda name: None)
    monkeypatch.setattr(common.request, "urlopen", fake_urlopen)

    result = common.api_json(
        "POST",
        "http://127.0.0.1:28080",
        "/api/v1/documents/ingest",
        {"x": 1},
        headers={"Content-Type": "application/json"},
        timeout=7,
        cell="ks-state-civics",
        transport="docker-network",
    )

    assert result == {"ok": True}
    assert captured == {
        "method": "POST",
        "timeout": 7,
        "url": "http://api:8080/api/v1/documents/ingest",
    }
