from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "scripts" / "release"
sys.path.insert(0, str(RELEASE))


def load_script():
    path = RELEASE / "topeka-code-combine-batches.py"
    spec = importlib.util.spec_from_file_location("topeka_code_combine_batches", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["topeka_code_combine_batches"] = module
    spec.loader.exec_module(module)
    return module


def test_combine_batches_dedupes_manifest_graph_and_copies_evidence(tmp_path):
    script = load_script()
    root = tmp_path / "batches"
    write_batch(root / "batch-001", "1.05.010", "First section.", raw_name="1.05.010")
    write_batch(root / "batch-002", "1.05.020", "Second section.", raw_name="1.05.020")
    later_nodes = read_jsonl(root / "batch-002" / "nodes.jsonl")
    for row in later_nodes:
        if row["id"] == "ks-topeka:tmc:1.05.010":
            row["type"] = "subsection"
    write_jsonl(root / "batch-002" / "nodes.jsonl", later_nodes)
    output = tmp_path / "combined"

    result = script.combine_batches(root, output)

    manifest = read_json(output / "manifest.json")
    crawl_report = read_json(output / "crawl_report.json")
    expected_rows = read_jsonl(output / "expected-fetch-urls.jsonl")
    manifest_rows = read_jsonl(output / "url-manifest.jsonl")
    nodes = read_jsonl(output / "nodes.jsonl")
    edges = read_jsonl(output / "edges.jsonl")

    assert result["batch_count"] == 2
    assert manifest["status"] == "success"
    assert manifest["counts"]["sections"] == 2
    assert manifest["counts"]["expected_fetch_urls"] == 2
    assert manifest["counts"]["raw_html_files"] == 2
    assert manifest["counts"]["network_files"] == 2
    assert crawl_report["pages_fetched"] == 2
    assert crawl_report["fetcher"] == "decodo-batch-combined"
    assert [row["citation"] for row in expected_rows] == ["1.05.010", "1.05.020"]
    assert all(row["fetch_required"] for row in expected_rows)
    assert {row["citation"] for row in manifest_rows if row.get("fetch_required")} == {"1.05.010", "1.05.020"}
    assert {row["id"]: row for row in nodes}["ks-topeka:tmc:1.05.010"]["type"] == "section"
    assert len([edge for edge in edges if edge["source"] == "ks-topeka:tmc:root" and edge["target"] == "ks-topeka:tmc:1"]) == 1
    assert (output / "raw" / "1.05.010.html").is_file()
    assert (output / "network" / "1.05.020.json").is_file()


def test_combine_batches_rejects_duplicate_section_content_conflict(tmp_path):
    script = load_script()
    root = tmp_path / "batches"
    write_batch(root / "batch-001", "1.05.010", "First section.", content_hash="a" * 64, raw_name="first")
    write_batch(root / "batch-002", "1.05.010", "Changed section.", content_hash="b" * 64, raw_name="second")

    with pytest.raises(script.CombineError, match="duplicate section id"):
        script.combine_batches(root, tmp_path / "combined")


def write_batch(
    batch: Path,
    citation: str,
    text: str,
    *,
    content_hash: str | None = None,
    raw_name: str,
) -> None:
    batch.mkdir(parents=True)
    section_id = f"ks-topeka:tmc:{citation}"
    section_url = f"https://topeka.municipal.codes/TMC/{citation}"
    section = {
        "id": section_id,
        "citation": citation,
        "title": f"{citation} title",
        "source_url": section_url,
        "text": text,
        "blocks": [{"order": 0, "kind": "paragraph", "text": text}],
        "references": [],
        "ordinance_history": [],
        "definitions": [],
        "content_hash": content_hash or citation.replace(".", "").ljust(64, "0")[:64],
        "source_html_hash": citation.replace(".", "").ljust(64, "1")[:64],
    }
    manifest_rows = [
        manifest_row("Code", "TMC", "ks-topeka:tmc:root", "https://topeka.municipal.codes/TMC", 1, False),
        manifest_row("Title", "1", "ks-topeka:tmc:1", "https://topeka.municipal.codes/TMC/1", 2, False),
        manifest_row("Chapter", "1.05", "ks-topeka:tmc:1.05", "https://topeka.municipal.codes/TMC/1.05", 3, False),
        manifest_row("Section", "1.05.010", "ks-topeka:tmc:1.05.010", "https://topeka.municipal.codes/TMC/1.05.010", 4, citation == "1.05.010"),
        manifest_row("Section", "1.05.020", "ks-topeka:tmc:1.05.020", "https://topeka.municipal.codes/TMC/1.05.020", 5, citation == "1.05.020"),
    ]
    nodes = [
        {
            "id": row["node_id"],
            "type": row["parser_page_type"],
            "label": row["citation"],
            "properties": {
                "source_url": row["url"],
                "citation_url": row["url"],
                "citation": row["citation"],
                "title": row["name"],
                "manifest_level": row["level"],
                "manifest_row_number": row["row_number"],
            },
        }
        for row in manifest_rows
    ]
    edges = [
        edge("ks-topeka:tmc:root", "ks-topeka:tmc:1", 1),
        edge("ks-topeka:tmc:1", "ks-topeka:tmc:1.05", 2),
        edge("ks-topeka:tmc:1.05", "ks-topeka:tmc:1.05.010", 3),
        edge("ks-topeka:tmc:1.05", "ks-topeka:tmc:1.05.020", 4),
    ]
    write_jsonl(batch / "sections.jsonl", [section])
    write_jsonl(batch / "definitions.jsonl", [])
    write_jsonl(batch / "nodes.jsonl", nodes)
    write_jsonl(batch / "edges.jsonl", edges)
    write_jsonl(
        batch / "citation-url-map.jsonl",
        [
            {"record_type": "page", "id": section_id, "source_url": section_url, "citation_url": section_url},
            {"record_type": "section", "id": section_id, "source_url": section_url, "citation_url": section_url, "content_hash": section["content_hash"]},
        ],
    )
    write_jsonl(batch / "url-manifest.jsonl", manifest_rows)
    write_jsonl(batch / "expected-fetch-urls.jsonl", [row for row in manifest_rows if row["citation"] == citation])
    write_json(batch / "manifest.json", {"schema_version": "1.0", "status": "success"})
    write_json(
        batch / "crawl_report.json",
        {
            "started_at": "2026-08-28T00:00:00Z",
            "finished_at": "2026-08-28T00:01:00Z",
            "root_url": "https://topeka.municipal.codes/TMC",
            "pages_seen": 1,
            "pages_fetched": 1,
            "pages_failed": 0,
            "section_count": 1,
            "definition_count": 0,
            "node_count": len(nodes),
            "edge_count": len(edges),
            "failures": [],
            "fetcher": "fixture",
        },
    )
    write_json(
        batch / "quality-report.json",
        {
            "passed": True,
            "section_coverage": {"missing": 0},
            "crawl_report": {"pages_failed": 0},
        },
    )
    (batch / "raw").mkdir()
    (batch / "network").mkdir()
    (batch / "raw" / f"{raw_name}.html").write_text("<html>code</html>", encoding="utf-8")
    (batch / "network" / f"{raw_name}.json").write_text("[]", encoding="utf-8")


def manifest_row(level: str, citation: str, node_id: str, url: str, row_number: int, fetch_required: bool) -> dict:
    return {
        "level": level,
        "id": citation,
        "citation": citation,
        "name": f"{citation} name",
        "node_id": node_id,
        "parent_title": "1" if level in {"Chapter", "Section"} else "",
        "parent_title_name": "Title 1",
        "parent_chapter": "1.05" if level == "Section" else "",
        "url": url,
        "parser_page_type": level.lower(),
        "fetch_required": fetch_required,
        "row_number": row_number,
    }


def edge(source: str, target: str, order: int) -> dict:
    return {
        "id": f"{source}>{target}",
        "source": source,
        "target": target,
        "type": "CONTAINS",
        "properties": {"source": "url_manifest", "order": order},
    }


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
