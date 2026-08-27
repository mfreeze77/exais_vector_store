from pathlib import Path

from topeka_code_scraper.graph import GraphBuilder
from topeka_code_scraper.parser import MunicipalCodeParser

FIXTURES = Path(__file__).parent / "fixtures"


def test_graph_contains_reference_definition_and_ordinance_edges():
    parser = MunicipalCodeParser()
    title = parser.parse(
        "https://topeka.municipal.codes/TMC/18",
        (FIXTURES / "title.html").read_text(encoding="utf-8"),
    )
    section = parser.parse(
        "https://topeka.municipal.codes/TMC/18.55.010",
        (FIXTURES / "section.html").read_text(encoding="utf-8"),
    )
    nodes, edges = GraphBuilder().build([title, section])
    edge_types = {edge.type for edge in edges}
    assert "REFERENCES" in edge_types
    assert "DEFINES" in edge_types
    assert "HAS_ORDINANCE_HISTORY" in edge_types
    section_node = next(node for node in nodes if node.id == "ks-topeka:tmc:18.55.010")
    definition_node = next(node for node in nodes if node.type == "definition")
    history_edge = next(edge for edge in edges if edge.type == "HAS_ORDINANCE_HISTORY")
    definition_edge = next(edge for edge in edges if edge.type == "DEFINES")
    history_edges = [edge for edge in edges if edge.type == "HAS_ORDINANCE_HISTORY"]

    assert section_node.properties["citation_url"] == "https://topeka.municipal.codes/TMC/18.55.010"
    assert definition_node.properties["citation_url"] == "https://topeka.municipal.codes/TMC/18.55.010"
    assert history_edge.properties["citation_url"] == "https://topeka.municipal.codes/TMC/18.55.010"
    assert definition_edge.properties["source_url"] == "https://topeka.municipal.codes/TMC/18.55.010"
    assert len(history_edges) == len(section.section.ordinance_history)
