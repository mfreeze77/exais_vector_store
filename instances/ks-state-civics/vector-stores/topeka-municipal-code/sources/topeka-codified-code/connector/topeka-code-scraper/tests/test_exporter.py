import json
from pathlib import Path

from topeka_code_scraper.exporter import export_corpus
from topeka_code_scraper.graph import GraphBuilder
from topeka_code_scraper.parser import MunicipalCodeParser


FIXTURES = Path(__file__).parent / "fixtures"


def test_export_writes_citation_url_map(tmp_path):
    page = MunicipalCodeParser().parse(
        "https://topeka.municipal.codes/TMC/18.55.010",
        (FIXTURES / "section.html").read_text(encoding="utf-8"),
    )
    nodes, edges = GraphBuilder().build([page])
    report = _report_for(page, nodes, edges)

    export_corpus(tmp_path, [page], nodes, edges, report)

    rows = [
        json.loads(line)
        for line in (tmp_path / "citation-url-map.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    section = next(row for row in rows if row["record_type"] == "section")
    definition = next(row for row in rows if row["record_type"] == "definition")
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

    assert section["id"] == "ks-topeka:tmc:18.55.010"
    assert section["citation_url"] == "https://topeka.municipal.codes/TMC/18.55.010"
    assert section["source_url"] == section["citation_url"]
    assert definition["citation_url"] == section["citation_url"]
    assert manifest["status"] == "success"
    assert manifest["files"]["citation_url_map"] == "citation-url-map.jsonl"
    assert manifest["counts"]["citation_urls"] == len(rows)


def _report_for(page, nodes, edges):
    from datetime import UTC, datetime

    from topeka_code_scraper.models import CrawlReport

    now = datetime.now(UTC)
    return CrawlReport(
        started_at=now,
        finished_at=now,
        root_url="https://topeka.municipal.codes/TMC",
        pages_seen=1,
        pages_fetched=1,
        pages_failed=0,
        section_count=1 if page.section else 0,
        definition_count=len(page.definitions),
        node_count=len(nodes),
        edge_count=len(edges),
        failures=[],
    )
