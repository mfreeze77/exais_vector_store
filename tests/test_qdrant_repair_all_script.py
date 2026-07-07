import importlib.util
import sys
from pathlib import Path

from svs_common.schemas import ReindexRequest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "release" / "qdrant-repair-all.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("qdrant_repair_all", SCRIPT)
qdrant_repair_all = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(qdrant_repair_all)


def test_parse_point_rows_ignores_command_noise():
    output = """
$ docker-compose exec postgres psql
svs_biz_default|99c55616-8ed1-506f-bd22-64c7cc83a413
invalid row
svs_biz_default|0e2d3fb5-5fe4-5556-8e71-bf2b7af35a88
[exit 0]
"""

    assert qdrant_repair_all.parse_point_rows(output) == [
        ("svs_biz_default", "99c55616-8ed1-506f-bd22-64c7cc83a413"),
        ("svs_biz_default", "0e2d3fb5-5fe4-5556-8e71-bf2b7af35a88"),
    ]


def test_repair_all_advances_cursor_until_api_reports_clean(monkeypatch):
    calls = []
    responses = [
        {"processed": 2, "details": {"has_more": True, "last_chunk_id": "chk_2"}},
        {"processed": 2, "details": {"has_more": True, "last_chunk_id": "chk_4"}},
        {"processed": 1, "details": {"has_more": False, "last_chunk_id": "chk_5"}},
    ]

    def fake_api_json(method, url, payload, timeout=120, cell="local"):
        calls.append(payload)
        return responses.pop(0)

    monkeypatch.setattr(qdrant_repair_all, "api_json", fake_api_json)

    iterations, total = qdrant_repair_all.repair_all("local", "http://api", "vs_123", 2, 30)

    assert iterations == 3
    assert total == 5
    assert calls == [
        {"vector_store_id": "vs_123", "batch_size": 2, "force": True},
        {"vector_store_id": "vs_123", "batch_size": 2, "force": True, "after_chunk_id": "chk_2"},
        {"vector_store_id": "vs_123", "batch_size": 2, "force": True, "after_chunk_id": "chk_4"},
    ]


def test_reindex_request_accepts_repair_all_cursor():
    req = ReindexRequest(vector_store_id="vs_123", batch_size=25, force=True, after_chunk_id="chk_25")

    assert req.after_chunk_id == "chk_25"
