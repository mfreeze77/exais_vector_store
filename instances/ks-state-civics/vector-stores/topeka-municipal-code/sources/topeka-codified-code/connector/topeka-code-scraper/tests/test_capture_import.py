import json
from pathlib import Path

from topeka_code_scraper.capture_import import import_capture_manifest
from topeka_code_scraper.exporter import export_corpus


FIXTURES = Path(__file__).parent / "fixtures"


def test_capture_manifest_imports_operator_html_and_exports_artifacts(tmp_path):
    html_path = tmp_path / "captures" / "18.55.010.html"
    html_path.parent.mkdir()
    html_path.write_text((FIXTURES / "section.html").read_text(encoding="utf-8"), encoding="utf-8")
    capture_manifest = tmp_path / "captures.jsonl"
    capture_manifest.write_text(
        json.dumps({
            "url": "https://topeka.municipal.codes/TMC/18.55.010",
            "html_path": "captures/18.55.010.html",
            "status_code": 200,
            "retrieved_at": "2026-08-28T00:00:00+00:00",
            "source": "operator_authorized_route",
        })
        + "\n",
        encoding="utf-8",
    )

    pages, nodes, edges, report = import_capture_manifest(
        capture_manifest,
        raw_dir=tmp_path / "output" / "raw",
        network_dir=tmp_path / "output" / "network",
    )
    export_corpus(tmp_path / "output", pages, nodes, edges, report)

    section_rows = _jsonl(tmp_path / "output" / "sections.jsonl")
    citation_rows = _jsonl(tmp_path / "output" / "citation-url-map.jsonl")
    manifest = json.loads((tmp_path / "output" / "manifest.json").read_text(encoding="utf-8"))

    assert report.fetcher == "capture_manifest"
    assert report.pages_fetched == 1
    assert report.pages_failed == 0
    assert section_rows[0]["source_url"] == "https://topeka.municipal.codes/TMC/18.55.010"
    assert any(row["record_type"] == "section" for row in citation_rows)
    assert manifest["status"] == "success"
    assert list((tmp_path / "output" / "raw").glob("18.55.010.*.html"))
    assert list((tmp_path / "output" / "network").glob("18.55.010.*.network.json"))


def test_capture_manifest_rejects_challenge_capture(tmp_path):
    capture_manifest = tmp_path / "captures.jsonl"
    capture_manifest.write_text(
        json.dumps({
            "url": "https://topeka.municipal.codes/TMC/1.10.010",
            "html": "<html><script src='https://challenges.cloudflare.com/x'></script></html>",
            "status_code": 403,
            "headers": {"cf-mitigated": "challenge"},
        })
        + "\n",
        encoding="utf-8",
    )

    pages, _nodes, _edges, report = import_capture_manifest(capture_manifest)

    assert pages == []
    assert report.pages_fetched == 0
    assert report.pages_failed == 1
    assert "publisher challenge page returned" in report.failures[0]["error"]


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
