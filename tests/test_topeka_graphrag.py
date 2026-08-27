from __future__ import annotations

import argparse
import importlib.util
import json
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


def test_graph_extract_enriches_codified_history_with_official_pdf_edges():
    module = load_script("topeka_code_graphrag_extract", "topeka-code-graphrag-extract.py")
    nodes = [
        {"id": "code", "type": "code", "label": "TMC", "properties": {"citation_url": "https://topeka.municipal.codes/TMC"}},
        {"id": "section-18.55.010", "type": "section", "label": "18.55.010 Definitions", "properties": {"citation_url": "https://topeka.municipal.codes/TMC/18.55.010"}},
        {"id": "definition-structure", "type": "definition", "label": "Structure", "properties": {"citation_url": "https://topeka.municipal.codes/TMC/18.55.010"}},
        {"id": "ordinance-20345", "type": "ordinance", "label": "Ordinance 20345", "properties": {"ordinance": "20345"}},
    ]
    edges = [
        {"id": "e-contains", "source": "code", "target": "section-18.55.010", "type": "CONTAINS", "properties": {"citation_url": "https://topeka.municipal.codes/TMC"}},
        {"id": "e-ref", "source": "section-18.55.010", "target": "code", "type": "REFERENCES", "properties": {"citation_url": "https://topeka.municipal.codes/TMC/18.55.010"}},
        {"id": "e-def", "source": "section-18.55.010", "target": "definition-structure", "type": "DEFINES", "properties": {"citation_url": "https://topeka.municipal.codes/TMC/18.55.010"}},
        {"id": "e-hist", "source": "section-18.55.010", "target": "ordinance-20345", "type": "HAS_ORDINANCE_HISTORY", "properties": {"raw": "Ord. No. 20345 amended this section.", "citation_url": "https://topeka.municipal.codes/TMC/18.55.010"}},
    ]
    ordinance_rows = [{
        "ordinance_number": "20345",
        "title": "Ordinance No. 20345",
        "category": "ordinance",
        "year": "2025",
        "pdf_url": "https://topeka.gov/ordinance-20345.pdf",
        "sha256": "pdfhash",
    }]

    enriched_nodes, enriched_edges, summary = module.enrich_graph_with_ordinances(nodes, edges, ordinance_rows)

    assert summary["ordinance_pdf_nodes_added"] == 1
    assert summary["ordinance_section_edges_added"] == 1
    assert any(node["type"] == "ordinance_pdf" and node["properties"]["citation_url"].endswith("20345.pdf") for node in enriched_nodes)
    assert any(edge["type"] == "ORDINANCE_AMENDS_SECTION" and edge["target"] == "section-18.55.010" for edge in enriched_edges)


def test_graph_eval_requires_core_edges_citations_and_ordinance_edges():
    extract = load_script("topeka_code_graphrag_extract_eval", "topeka-code-graphrag-extract.py")
    eval_module = load_script("topeka_code_graphrag_eval", "topeka-code-graphrag-eval.py")
    nodes = [
        {"id": "code", "type": "code", "label": "TMC", "properties": {"citation_url": "https://topeka.municipal.codes/TMC"}},
        {"id": "section", "type": "section", "label": "Section", "properties": {"citation_url": "https://topeka.municipal.codes/TMC/1"}},
        {"id": "definition", "type": "definition", "label": "Definition", "properties": {"citation_url": "https://topeka.municipal.codes/TMC/1"}},
        {"id": "ordinance", "type": "ordinance", "label": "Ordinance 20345", "properties": {"ordinance": "20345"}},
    ]
    edges = [
        {"id": "contains", "source": "code", "target": "section", "type": "CONTAINS", "properties": {"citation_url": "https://topeka.municipal.codes/TMC"}},
        {"id": "refs", "source": "section", "target": "code", "type": "REFERENCES", "properties": {"citation_url": "https://topeka.municipal.codes/TMC/1"}},
        {"id": "defines", "source": "section", "target": "definition", "type": "DEFINES", "properties": {"citation_url": "https://topeka.municipal.codes/TMC/1"}},
        {"id": "hist", "source": "section", "target": "ordinance", "type": "HAS_ORDINANCE_HISTORY", "properties": {"raw": "amended", "citation_url": "https://topeka.municipal.codes/TMC/1"}},
    ]
    enriched_nodes, enriched_edges, _summary = extract.enrich_graph_with_ordinances(nodes, edges, [{
        "ordinance_number": "20345",
        "pdf_url": "https://topeka.gov/ordinance-20345.pdf",
        "title": "Ordinance No. 20345",
    }])

    proof = eval_module.build_eval(enriched_nodes, enriched_edges)

    assert proof["passed"] is True
    assert proof["edge_types"]["ORDINANCE_AMENDS_SECTION"] == 1


def test_graph_load_dry_run_validates_without_direct_db_writes():
    module = load_script("topeka_code_graphrag_load", "topeka-code-graphrag-load.py")

    result = module.load_graph(
        api_base="http://api.test",
        graph_api_path=None,
        headers={},
        vector_store_id="vs_topeka",
        nodes=[{"id": "a"}, {"id": "b"}],
        edges=[{"id": "ab", "source": "a", "target": "b"}],
        dry_run=True,
        timeout=1,
    )

    assert result["status"] == "dry_run"
    assert result["nodes"] == 2
    assert result["edges"] == 1


def test_graph_load_fails_closed_without_supported_api_path():
    module = load_script("topeka_code_graphrag_load_blocked", "topeka-code-graphrag-load.py")

    with pytest.raises(RuntimeError, match="forbids that for Topeka"):
        module.load_graph(
            api_base="http://api.test",
            graph_api_path=None,
            headers={},
            vector_store_id="vs_topeka",
            nodes=[{"id": "a"}, {"id": "b"}],
            edges=[{"id": "ab", "source": "a", "target": "b"}],
            dry_run=False,
            timeout=1,
        )


def test_recall_eval_dry_run_has_five_current_and_five_history_queries():
    module = load_script("topeka_code_recall_eval", "topeka-code-recall-eval.py")

    proof = module.dry_run_eval()

    assert proof["passed"] is True
    assert proof["categories"] == {"current_code": 5, "amendment_history": 5}
    assert len(proof["queries"]) == 10
