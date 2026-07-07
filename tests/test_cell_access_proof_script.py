import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "release" / "cell-access-proof.py"
ADMIN_VITE_CONFIG = Path(__file__).resolve().parents[1] / "apps" / "admin_ui" / "vite.config.ts"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("cell_access_proof", SCRIPT)
cell_access_proof = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules["cell_access_proof"] = cell_access_proof
spec.loader.exec_module(cell_access_proof)


def test_access_targets_use_requested_cell_env(monkeypatch):
    monkeypatch.setattr(cell_access_proof, "read_env", lambda cell: {"SVS_ADMIN_UI_PORT": "23080"})
    monkeypatch.setattr(cell_access_proof, "api_base", lambda cell: f"http://{cell}.internal:28080")

    targets = cell_access_proof.access_targets("customer-001")

    assert [(target.name, target.host_url, target.cell_url) for target in targets] == [
        ("api", "http://customer-001.internal:28080/readyz", "http://api:8080/readyz"),
        ("admin-ui", "http://localhost:23080/", "http://admin-ui:3000/"),
    ]


def test_access_proof_script_does_not_hardcode_local_network():
    body = SCRIPT.read_text(encoding="utf-8")

    assert "exais-vector-store-local_default" not in body
    assert "compose_network_name(cell)" in body


def test_admin_vite_allows_cell_service_host():
    body = ADMIN_VITE_CONFIG.read_text(encoding="utf-8")

    assert "'admin-ui'" in body
    assert "allowedHosts: true" not in body


def test_label_name_is_shell_friendly():
    assert cell_access_proof.label_name("admin-ui") == "ADMIN_UI"
