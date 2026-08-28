from pathlib import Path

from topeka_code_scraper.graph import GraphBuilder
from topeka_code_scraper.parser import MunicipalCodeParser
from topeka_code_scraper.url_manifest import (
    load_url_manifest,
    manifest_graph,
    merge_graphs,
    parse_level_filter,
    read_url_manifest,
    write_url_manifest_artifacts,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_url_manifest_filters_section_fetch_urls_and_builds_contains_graph(tmp_path):
    manifest = tmp_path / "urls.csv"
    manifest.write_text(
        "\n".join(
            [
                "level,id,citation,name,parent_title,parent_title_name,parent_chapter,url",
                "Code,,TMC,Topeka Municipal Code (root),,,,https://topeka.municipal.codes/TMC",
                "Title,18,18,Title 18 Development Code,18,Title 18 Development Code,,https://topeka.municipal.codes/TMC/18",
                "Chapter,18.55,18.55,Definitions,18,Title 18 Development Code,,https://topeka.municipal.codes/TMC/18.55",
                "Section,18.55.010,18.55.010,Definitions.,18,Title 18 Development Code,18.55,https://topeka.municipal.codes/TMC/18.55.010",
                "Subsection,AxB_ArtXIII_1_1,AxB Art. XIII § 1 § 1,Section 1. Definitions,AxB,,,https://topeka.municipal.codes/TMC/AxB_ArtXIII_1_1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    all_entries = read_url_manifest(manifest)
    fetch_entries = load_url_manifest(manifest, fetch_levels=parse_level_filter("Section,Subsection"))
    nodes, edges = manifest_graph(all_entries)
    contains = {(edge.source, edge.target) for edge in edges if edge.type == "CONTAINS"}

    assert [entry.url for entry in fetch_entries] == [
        "https://topeka.municipal.codes/TMC/18.55.010",
        "https://topeka.municipal.codes/TMC/AxB_ArtXIII_1_1",
    ]
    assert ("ks-topeka:tmc:root", "ks-topeka:tmc:18") in contains
    assert ("ks-topeka:tmc:18", "ks-topeka:tmc:18.55") in contains
    assert ("ks-topeka:tmc:18.55", "ks-topeka:tmc:18.55.010") in contains
    assert any(node.id == "ks-topeka:tmc:AxB_ArtXIII_1_1" for node in nodes)


def test_manifest_merge_preserves_parsed_section_content_properties():
    parser = MunicipalCodeParser()
    page = parser.parse(
        "https://topeka.municipal.codes/TMC/18.55.010",
        (FIXTURES / "section.html").read_text(encoding="utf-8"),
        forced_page_type="section",
        forced_citation="18.55.010",
        forced_title="Definitions.",
    )
    manifest_nodes, manifest_edges = manifest_graph(
        [
            _entry("Code", "TMC", "Topeka Municipal Code", "https://topeka.municipal.codes/TMC", 2),
            _entry("Section", "18.55.010", "Definitions.", "https://topeka.municipal.codes/TMC/18.55.010", 3),
        ]
    )
    parsed_nodes, parsed_edges = GraphBuilder().build([page])

    nodes, edges = merge_graphs(manifest_nodes, manifest_edges, parsed_nodes, parsed_edges)
    section_node = next(node for node in nodes if node.id == "ks-topeka:tmc:18.55.010")

    assert page.section is not None
    assert section_node.properties["content_hash"] == page.section.content_hash
    assert section_node.properties["manifest_level"] == "Section"
    assert "CONTAINS" in {edge.type for edge in edges}
    assert "DEFINES" in {edge.type for edge in edges}


def test_url_manifest_artifacts_are_written_and_added_to_manifest(tmp_path):
    entries = [
        _entry("Code", "TMC", "Topeka Municipal Code", "https://topeka.municipal.codes/TMC", 2),
        _entry("Section", "18.55.010", "Definitions.", "https://topeka.municipal.codes/TMC/18.55.010", 3),
    ]
    (tmp_path / "manifest.json").write_text('{"files":{},"counts":{}}', encoding="utf-8")

    stats = write_url_manifest_artifacts(tmp_path, entries, entries[1:])
    manifest = __import__("json").loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    url_rows = (tmp_path / "url-manifest.jsonl").read_text(encoding="utf-8").splitlines()
    fetch_rows = (tmp_path / "expected-fetch-urls.jsonl").read_text(encoding="utf-8").splitlines()

    assert stats == {"expected_fetch_urls": 1, "url_manifest_rows": 2}
    assert len(url_rows) == 2
    assert len(fetch_rows) == 1
    assert manifest["files"]["url_manifest"] == "url-manifest.jsonl"
    assert manifest["files"]["expected_fetch_urls"] == "expected-fetch-urls.jsonl"
    assert manifest["counts"]["expected_fetch_urls"] == 1


def _entry(level: str, citation: str, name: str, url: str, row_number: int):
    from topeka_code_scraper.url_manifest import UrlManifestEntry

    return UrlManifestEntry(
        level=level,
        id=citation,
        citation=citation,
        name=name,
        parent_title="",
        parent_title_name="",
        parent_chapter="",
        url=url,
        row_number=row_number,
    )
