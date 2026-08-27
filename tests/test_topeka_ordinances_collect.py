from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "release" / "topeka-ordinances-collect.py"
sys.path.insert(0, str(SCRIPT.parent))


def load_module():
    spec = importlib.util.spec_from_file_location("topeka_ordinances_collect", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["topeka_ordinances_collect"] = module
    spec.loader.exec_module(module)
    return module


def test_collect_ordinances_discovers_official_pdfs_and_writes_citations(tmp_path):
    module = load_module()
    html = """
    <html><body>
      <a href="/files/assets/public/v/1/city-clerk/documents/ordinances/ordinance-20345.pdf">
        Ordinance No. 20345 - Amend zoning regulations
      </a>
      <a href="https://example.test/ordinance-99999.pdf">not official</a>
      <a href="/community/ordinances/index.php">not a pdf</a>
    </body></html>
    """

    def fake_download(url: str, *, timeout: int) -> bytes:
        assert "20345" in url
        assert timeout == 9
        return b"%PDF-1.4 ordinance 20345"

    summary = module.collect_ordinances(
        source_url="https://topeka.gov/community/ordinances/index.php",
        html=html,
        output_dir=tmp_path,
        limit=0,
        timeout=9,
        downloader=fake_download,
    )

    assert summary["status"] == "success"
    assert summary["ordinance_count"] == 1
    manifest = (tmp_path / "manifests" / "ordinances.jsonl").read_text(encoding="utf-8")
    citation_map = (tmp_path / "citation-url-map.jsonl").read_text(encoding="utf-8")
    assert "20345" in manifest
    assert "https://topeka.gov/files/assets/public/v/1/city-clerk/documents/ordinances/ordinance-20345.pdf" in citation_map
    assert (tmp_path / "raw" / "pdfs" / "20345.pdf").exists()
