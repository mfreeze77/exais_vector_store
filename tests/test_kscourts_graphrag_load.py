from __future__ import annotations

import argparse
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release" / "kscourts-graphrag-load.py"
MIGRATION = ROOT / "migrations" / "versions" / "002_graphrag_staging.py"


def load_module():
    spec = importlib.util.spec_from_file_location("kscourts_graphrag_load", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _args() -> argparse.Namespace:
    return argparse.Namespace(
        tenant_id="ten_ks",
        business_instance_id="biz_ks",
        vector_store_id="vs_ks",
        batch_size=2,
        no_replace=False,
        dry_run=True,
    )


def test_graphrag_loader_prepares_tenant_scoped_rows_and_skips_dangling_edges():
    module = load_module()
    nodes = [
        {"id": "node_opinion_a", "type": "opinion", "key": "doc-a", "label": "Doc A", "attributes": {"document_id": "doc_a"}, "provenance": []},
        {"id": "node_opinion_b", "type": "opinion", "key": "doc-b", "label": "Doc B", "attributes": {"document_id": "doc_b"}, "provenance": []},
    ]
    edges = [
        {"id": "edge_ok", "type": "same_docket", "source": "node_opinion_a", "target": "node_opinion_b", "attributes": {}, "provenance": {}},
        {"id": "edge_skip", "type": "same_docket", "source": "node_opinion_a", "target": "node_missing", "attributes": {}, "provenance": {}},
    ]

    node_rows = module.node_params(nodes, _args())
    edge_rows, skipped = module.edge_params(edges, {row["id"] for row in node_rows}, _args())

    assert {row["tenant_id"] for row in node_rows} == {"ten_ks"}
    assert {row["business_instance_id"] for row in node_rows} == {"biz_ks"}
    assert {row["vector_store_id"] for row in node_rows} == {"vs_ks"}
    assert [row["id"] for row in edge_rows] == ["edge_ok"]
    assert skipped == 1


def test_graphrag_loader_dry_run_reports_replacement_counts():
    module = load_module()
    args = _args()
    nodes = [
        {"id": "node_a", "type": "opinion", "key": "doc-a", "label": "Doc A", "attributes": {}, "provenance": []},
    ]
    edges = [
        {"id": "edge_a", "type": "source_document", "source": "node_a", "target": "node_a", "attributes": {}, "provenance": {}},
    ]

    result = module.load_graph(args, nodes, edges)

    assert result == {
        "dry_run": True,
        "nodes": 1,
        "edges": 1,
        "skipped_edges": 0,
        "replaced": True,
    }


def test_graphrag_staging_migration_declares_rls_scope():
    source = MIGRATION.read_text(encoding="utf-8")

    assert "ALTER TABLE graph_nodes ENABLE ROW LEVEL SECURITY" in source
    assert "ALTER TABLE graph_edges ENABLE ROW LEVEL SECURITY" in source
    assert "ALTER TABLE graph_nodes FORCE ROW LEVEL SECURITY" in source
    assert "ALTER TABLE graph_edges FORCE ROW LEVEL SECURITY" in source
    assert "tenant_id = svs_current_tenant_id()" in source
    assert "business_instance_id = svs_current_business_instance_id()" in source
