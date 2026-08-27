from pathlib import Path

from topeka_code_scraper.parser import MunicipalCodeParser

FIXTURES = Path(__file__).parent / "fixtures"


def test_section_is_clean_and_graph_ready():
    html = (FIXTURES / "section.html").read_text(encoding="utf-8")
    page = MunicipalCodeParser().parse("https://topeka.municipal.codes/TMC/18.55.010", html)

    assert page.page_type == "section"
    assert page.citation == "18.55.010"
    assert page.section is not None
    assert "Disclaimer" not in page.section.text
    assert page.section.version is not None
    assert page.section.version.ordinance == "20671"
    assert len(page.section.references) == 1
    assert page.section.references[0].citation is None  # chapter ref, not section-level citation
    assert len(page.definitions) == 2
    assert page.definitions[0].term == "Accessory dwelling unit"
    assert "Additional text" in page.definitions[0].text
    assert page.section.ordinance_history[0].ordinance == "20500"
    assert all(item.ordinance.isdigit() for item in page.section.ordinance_history)
    assert {item.ordinance for item in page.section.ordinance_history}.isdisjoint({"inate", "ordinance", "and"})
    assert "Use | Allowed" in page.section.text
    assert len(page.section.tables) == 1
    assert any(asset.type == "attachment" for asset in page.section.assets)


def test_nested_toc_edges_and_virtual_divisions_are_extracted():
    html = (FIXTURES / "title.html").read_text(encoding="utf-8")
    page = MunicipalCodeParser().parse("https://topeka.municipal.codes/TMC/18", html)
    assert page.page_type == "title"
    division = next(node for node in page.toc_nodes if node.type == "division")
    chapter = next(node for node in page.toc_nodes if node.id.endswith("18.55"))
    section = next(node for node in page.toc_nodes if node.id.endswith("18.55.010"))
    assert division.id.startswith("ks-topeka:tmc:18:division:")
    assert any(edge.source == division.id and edge.target == chapter.id for edge in page.toc_edges)
    assert any(edge.source == chapter.id and edge.target == section.id for edge in page.toc_edges)
