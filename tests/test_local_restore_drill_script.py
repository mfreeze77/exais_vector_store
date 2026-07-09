import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "release" / "local-restore-drill.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("local_restore_drill", SCRIPT)
local_restore_drill = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(local_restore_drill)

from backup_common import validate_backup_manifest  # noqa: E402


def test_drill_env_values_assign_distinct_ports():
    values = local_restore_drill.drill_env_values("restore-src", "localhost:5000/expertaiservices", 28080)

    assert values["SVS_CELL_NAME"] == "restore-src"
    assert values["SVS_API_PORT"] == "28080"
    assert values["SVS_MODEL_GATEWAY_PORT"] == "28081"
    assert values["SVS_ADMIN_UI_PORT"] == "28082"
    assert values["SVS_POSTGRES_PORT"] == "28084"
    assert values["SVS_PUBLIC_API_BASE"] == "http://localhost:28080"
    assert values["SVS_ALLOWED_CORS_ORIGINS"] == "http://localhost:28082,http://localhost:28080"


def test_restore_doc_contains_token_in_each_section():
    doc = local_restore_drill.restore_doc(7, 3, "token-abc")

    assert doc["attributes"]["force_async"] is True
    assert doc["mode"] == "markdown_docs_v1"
    assert doc["content"].count("token-abc") == 3
    assert "restore-proof-7-2" in doc["content"]


def test_restore_drill_writes_shared_backup_manifest(tmp_path):
    (tmp_path / "svs.dump").write_text("dump\n", encoding="utf-8")

    local_restore_drill.write_backup_manifest(
        tmp_path,
        {
            "source_cell": "restore-src",
            "restore_cell": "restore",
            "vector_store_id": "vs_test",
            "source_sql_counts": {"active_chunks": 1, "indexed_chunks": 1},
            "source_qdrant_count": 1,
            "collections": ["chunks_default"],
        },
    )

    report = validate_backup_manifest(tmp_path / "manifest.json")

    assert report.ok
    assert "qdrant_vectors" in report.artifact_kinds
    assert (tmp_path / "restore-drill-manifest.json").is_file()
