from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "scripts" / "release"
sys.path.insert(0, str(RELEASE))


def load_script():
    path = RELEASE / "topeka-code-workbench-project.py"
    spec = importlib.util.spec_from_file_location("topeka_code_workbench_project", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["topeka_code_workbench_project"] = module
    spec.loader.exec_module(module)
    return module


def test_projection_creates_stable_component_tree(tmp_path):
    script = load_script()
    seed_topeka_artifacts(tmp_path)

    first = script.build_workbench_projection(tmp_path)
    second = script.build_workbench_projection(tmp_path)

    assert first["manifest"]["quality"]["passed"] is True
    by_key = {row["source_component_key"]: row for row in first["components"]}
    assert by_key["ks-topeka:tmc:1"]["type"] == "title"
    assert by_key["ks-topeka:tmc:1.05"]["parent_source_component_key"] == "ks-topeka:tmc:1"
    assert by_key["ks-topeka:tmc:1.05.010"]["parent_source_component_key"] == "ks-topeka:tmc:1.05"

    block = by_key["ks-topeka:tmc:1.05.010:marker:a"]
    assert block["type"] == "paragraph"
    assert block["citation"] == "1.05.010(a)"
    assert block["parent_source_component_key"] == "ks-topeka:tmc:1.05.010"
    assert len(block["content_hash"]) == 64

    assert by_key["ks-topeka:tmc:1.05.010:definition:city"]["type"] == "definition"
    assert first["canonical_document"]["schema"] == script.CANONICAL_DOCUMENT_SCHEMA
    assert first["canonical_document"]["body"][0]["id"] == by_key["ks-topeka:tmc:root"]["workbench_component_id"]
    assert first["canonical_document"]["documentId"] == second["canonical_document"]["documentId"]
    assert first["canonical_document"]["versionId"] == second["canonical_document"]["versionId"]


def test_projection_filters_unfetched_manifest_sections(tmp_path):
    script = load_script()
    seed_topeka_artifacts(tmp_path, include_unfetched=True)

    projection = script.build_workbench_projection(tmp_path)

    by_key = {row["source_component_key"]: row for row in projection["components"]}
    assert "ks-topeka:tmc:1.05.010" in by_key
    assert "ks-topeka:tmc:1.05.020" not in by_key
    assert projection["manifest"]["counts"]["source_sections"] == 1
    assert projection["manifest"]["quality"]["passed"] is True


def test_projection_emits_appendix_slices_without_chapters(tmp_path):
    script = load_script()
    seed_topeka_appendix_artifacts(tmp_path)

    projection = script.build_workbench_projection(tmp_path)

    by_key = {row["source_component_key"]: row for row in projection["components"]}
    assert by_key["ks-topeka:tmc:AxA"]["type"] == "appendix"
    assert by_key["ks-topeka:tmc:AxA_ArtI"]["parent_source_component_key"] == "ks-topeka:tmc:AxA"
    assert by_key["ks-topeka:tmc:A1-1"]["parent_source_component_key"] == "ks-topeka:tmc:AxA_ArtI"

    appendix_slices = [row for row in projection["slices"] if row["slice_type"] == "appendix"]
    article_slices = [row for row in projection["slices"] if row["slice_type"] == "article"]
    assert len(appendix_slices) == 1
    assert appendix_slices[0]["slice_key"] == "ks-topeka:tmc:AxA"
    assert appendix_slices[0]["section_component_keys"] == ["ks-topeka:tmc:A1-1"]
    assert len(article_slices) == 1
    assert article_slices[0]["slice_key"] == "ks-topeka:tmc:AxA_ArtI"
    assert article_slices[0]["section_component_keys"] == ["ks-topeka:tmc:A1-1"]


def test_write_projection_outputs_manifest_and_contract_files(tmp_path):
    script = load_script()
    seed_topeka_artifacts(tmp_path)
    output = tmp_path / "workbench"

    projection = script.build_workbench_projection(tmp_path)
    manifest = script.write_workbench_projection(output, projection)

    expected = {
        "canonical-document.json",
        "components.jsonl",
        "component-projection.jsonl",
        "component-relations.jsonl",
        "slices.jsonl",
        "workbench-import-manifest.json",
    }
    assert expected == {path.name for path in output.iterdir() if path.is_file()}
    assert manifest["boundary"].startswith("Projection-only.")
    assert manifest["quality"]["passed"] is True
    assert all(len(row["sha256"]) == 64 and row["bytes"] > 0 for row in manifest["files"].values())
    assert read_json(output / "workbench-import-manifest.json")["projection_schema"] == script.WORKBENCH_PROJECTION_SCHEMA


def seed_topeka_artifacts(root: Path, *, include_unfetched: bool = False) -> None:
    write_jsonl(
        root / "sections.jsonl",
        [
            {
                "id": "ks-topeka:tmc:1.05.010",
                "citation": "1.05.010",
                "title": "Code adoption.",
                "source_url": "https://topeka.municipal.codes/TMC/1.05.010",
                "text": "(a) The code is adopted.\n\n(b) The clerk keeps copies.",
                "blocks": [
                    {"order": 0, "kind": "paragraph", "marker": "(a)", "text": "(a) The code is adopted."},
                    {"order": 1, "kind": "paragraph", "marker": "(b)", "text": "(b) The clerk keeps copies."},
                ],
                "references": [
                    {
                        "citation": "1.05.020",
                        "url": "https://topeka.municipal.codes/TMC/1.05.020",
                        "target_id": "ks-topeka:tmc:1.05.020",
                        "text": "TMC 1.05.020",
                    }
                ],
                "ordinance_history": [{"ordinance": "20243", "section": "1", "date": "4-21-20", "raw": "Ord. 20243 § 1, 4-21-20"}],
                "content_hash": "a" * 64,
                "source_html_hash": "b" * 64,
            }
        ],
    )
    write_jsonl(
        root / "definitions.jsonl",
        [
            {
                "id": "ks-topeka:tmc:1.05.010:definition:city",
                "section_id": "ks-topeka:tmc:1.05.010",
                "section_citation": "1.05.010",
                "term": "City",
                "aliases": [],
                "text": "City means the City of Topeka.",
                "source_url": "https://topeka.municipal.codes/TMC/1.05.010",
                "content_hash": "c" * 64,
            }
        ],
    )
    manifest_rows = [
        _manifest("Code", "TMC", "", "Topeka Municipal Code (root)", "ks-topeka:tmc:root", "https://topeka.municipal.codes/TMC", 2, "code"),
        _manifest("Title", "1", "1", "Title 1 General Provisions", "ks-topeka:tmc:1", "https://topeka.municipal.codes/TMC/1", 3, "title"),
        _manifest("Chapter", "1.05", "1.05", "Code Adoption", "ks-topeka:tmc:1.05", "https://topeka.municipal.codes/TMC/1.05", 4, "chapter"),
        _manifest("Section", "1.05.010", "1.05.010", "Code adoption.", "ks-topeka:tmc:1.05.010", "https://topeka.municipal.codes/TMC/1.05.010", 5, "section"),
    ]
    if include_unfetched:
        manifest_rows.append(_manifest("Section", "1.05.020", "1.05.020", "Unfetched.", "ks-topeka:tmc:1.05.020", "https://topeka.municipal.codes/TMC/1.05.020", 6, "section"))
    write_jsonl(root / "url-manifest.jsonl", manifest_rows)
    write_jsonl(
        root / "nodes.jsonl",
        [
            {
                "id": row["node_id"],
                "type": row["parser_page_type"],
                "label": f"{row['citation']} {row['name']}".strip(),
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
        ],
    )
    edges = [
        _edge("ks-topeka:tmc:root", "ks-topeka:tmc:1", 1),
        _edge("ks-topeka:tmc:1", "ks-topeka:tmc:1.05", 2),
        _edge("ks-topeka:tmc:1.05", "ks-topeka:tmc:1.05.010", 3),
    ]
    if include_unfetched:
        edges.append(_edge("ks-topeka:tmc:1.05", "ks-topeka:tmc:1.05.020", 4))
    write_jsonl(root / "edges.jsonl", edges)
    write_json(root / "crawl_report.json", {"pages_fetched": 1, "pages_failed": 0, "section_count": 1, "fetcher": "fixture"})
    write_json(root / "quality-report.json", {"passed": True, "vectorization_allowed": True})


def seed_topeka_appendix_artifacts(root: Path) -> None:
    section = {
        "id": "ks-topeka:tmc:A1-1",
        "citation": "A1-1",
        "title": "Sec. A1-1. Charter power.",
        "source_url": "https://topeka.municipal.codes/TMC/A1-1",
        "text": "The city may exercise home rule powers.",
        "blocks": [{"order": 0, "kind": "paragraph", "text": "The city may exercise home rule powers."}],
        "references": [],
        "ordinance_history": [],
        "content_hash": "d" * 64,
        "source_html_hash": "e" * 64,
    }
    write_jsonl(root / "sections.jsonl", [section])
    write_jsonl(root / "definitions.jsonl", [])
    manifest_rows = [
        _manifest("Code", "TMC", "", "Topeka Municipal Code (root)", "ks-topeka:tmc:root", "https://topeka.municipal.codes/TMC", 2, "code"),
        _manifest("Appendix", "AxA", "AxA", "Appendix A: Compilation of Charter Ordinances", "ks-topeka:tmc:AxA", "https://topeka.municipal.codes/TMC/AxA", 3, "appendix"),
        _manifest("Article", "AxA Art. I", "AxA_ArtI", "Article I. Home Rule", "ks-topeka:tmc:AxA_ArtI", "https://topeka.municipal.codes/TMC/AxA_ArtI", 4, "article"),
        _manifest("Section", "A1-1", "A1-1", "Sec. A1-1. Charter power.", "ks-topeka:tmc:A1-1", "https://topeka.municipal.codes/TMC/A1-1", 5, "section"),
    ]
    write_jsonl(root / "url-manifest.jsonl", manifest_rows)
    write_jsonl(
        root / "nodes.jsonl",
        [
            {
                "id": row["node_id"],
                "type": row["parser_page_type"],
                "label": f"{row['citation']} {row['name']}".strip(),
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
        ],
    )
    write_jsonl(
        root / "edges.jsonl",
        [
            _edge("ks-topeka:tmc:root", "ks-topeka:tmc:AxA", 1),
            _edge("ks-topeka:tmc:AxA", "ks-topeka:tmc:AxA_ArtI", 2),
            _edge("ks-topeka:tmc:AxA_ArtI", "ks-topeka:tmc:A1-1", 3),
        ],
    )
    write_json(root / "crawl_report.json", {"pages_fetched": 1, "pages_failed": 0, "section_count": 1, "fetcher": "fixture"})
    write_json(root / "quality-report.json", {"passed": True, "vectorization_allowed": True})


def _manifest(level: str, citation: str, row_id: str, name: str, node_id: str, url: str, row_number: int, parser_page_type: str) -> dict:
    return {
        "level": level,
        "citation": citation,
        "id": row_id,
        "name": name,
        "node_id": node_id,
        "url": url,
        "row_number": row_number,
        "parser_page_type": parser_page_type,
    }


def _edge(source: str, target: str, order: int) -> dict:
    return {"source": source, "target": target, "type": "CONTAINS", "properties": {"order": order}}


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
