import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "release" / "qdrant-chaos-repair.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("qdrant_chaos_repair", SCRIPT)
qdrant_chaos_repair = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(qdrant_chaos_repair)


def test_parse_point_rows_ignores_non_tuple_noise():
    output = """
$ psql command
svs_biz_default|99c55616-8ed1-506f-bd22-64c7cc83a413
invalid row
svs_biz_default|0e2d3fb5-5fe4-5556-8e71-bf2b7af35a88
[exit 0]
"""

    assert qdrant_chaos_repair.parse_point_rows(output) == [
        ("svs_biz_default", "99c55616-8ed1-506f-bd22-64c7cc83a413"),
        ("svs_biz_default", "0e2d3fb5-5fe4-5556-8e71-bf2b7af35a88"),
    ]


def test_group_points_by_collection_preserves_point_ids():
    rows = [
        ("svs_biz_default", "p1"),
        ("svs_biz_other", "p2"),
        ("svs_biz_default", "p3"),
    ]

    assert qdrant_chaos_repair.group_points_by_collection(rows) == {
        "svs_biz_default": ["p1", "p3"],
        "svs_biz_other": ["p2"],
    }


def test_vector_store_filter_matches_qdrant_payload_shape():
    assert qdrant_chaos_repair.vector_store_filter("vs_123") == {
        "must": [{"key": "vector_store_id", "match": {"value": "vs_123"}}]
    }
