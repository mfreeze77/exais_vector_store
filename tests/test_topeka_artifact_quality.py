from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "scripts" / "release"
sys.path.insert(0, str(RELEASE))


def load_script():
    path = RELEASE / "topeka-code-artifact-quality.py"
    spec = importlib.util.spec_from_file_location("topeka_code_artifact_quality", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["topeka_code_artifact_quality"] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def seed_common_artifacts(root: Path, *, sections: list[dict], expected: list[dict], failures: list[dict] | None = None) -> None:
    write_jsonl(root / "expected-fetch-urls.jsonl", expected)
    write_jsonl(root / "url-manifest.jsonl", expected)
    write_jsonl(root / "sections.jsonl", sections)
    write_jsonl(root / "definitions.jsonl", [])
    write_jsonl(root / "nodes.jsonl", [{"id": "ks-topeka:tmc:root", "type": "code"}])
    write_jsonl(root / "edges.jsonl", [{"source": "ks-topeka:tmc:root", "target": "ks-topeka:tmc:1.05.010", "type": "CONTAINS"}])
    write_jsonl(
        root / "citation-url-map.jsonl",
        [
            {
                "record_type": "section",
                "id": row["id"],
                "source_url": row["source_url"],
                "citation_url": row["source_url"],
            }
            for row in sections
        ],
    )
    failures = failures or []
    write_json(
        root / "manifest.json",
        {"status": "success" if not failures else "partial_with_failures"},
    )
    write_json(
        root / "crawl_report.json",
        {
            "pages_seen": len(expected),
            "pages_fetched": len(sections),
            "pages_failed": len(failures),
            "section_count": len(sections),
            "failures": failures,
        },
    )


def test_quality_gate_passes_complete_json_artifact_set(tmp_path):
    script = load_script()
    expected = [_expected("1.05.010")]
    section = _section("1.05.010")
    seed_common_artifacts(tmp_path, sections=[section], expected=expected)

    report = script.build_quality_report(tmp_path, Path("unused.csv"), {"section"})

    assert report["passed"] is True
    assert report["vectorization_allowed"] is True
    assert report["failure_reasons"] == []


def test_quality_gate_blocks_missing_sections_and_failed_crawl(tmp_path):
    script = load_script()
    expected = [_expected("1.05.010"), _expected("1.10.010")]
    seed_common_artifacts(
        tmp_path,
        sections=[_section("1.05.010")],
        expected=expected,
        failures=[{"url": "https://topeka.municipal.codes/TMC/1.10.010", "error": "publisher challenge page returned"}],
    )

    report = script.build_quality_report(tmp_path, Path("unused.csv"), {"section"})

    assert report["passed"] is False
    assert report["vectorization_allowed"] is False
    assert "missing_required_section_urls" in report["failure_reasons"]
    assert "crawl_report_has_failures" in report["failure_reasons"]
    assert report["section_coverage"]["missing"] == 1


def _expected(citation: str) -> dict:
    return {
        "level": "Section",
        "id": citation,
        "citation": citation,
        "name": "Test",
        "url": f"https://topeka.municipal.codes/TMC/{citation}",
    }


def _section(citation: str) -> dict:
    return {
        "id": f"ks-topeka:tmc:{citation}",
        "citation": citation,
        "title": "Test",
        "source_url": f"https://topeka.municipal.codes/TMC/{citation}",
        "text": "A real section body.",
    }
