from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "release" / "generate-cell-env.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("generate_cell_env", SCRIPT)
generate_cell_env = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules["generate_cell_env"] = generate_cell_env
spec.loader.exec_module(generate_cell_env)


def test_import_operator_values_copies_allowlisted_secrets_only():
    values = generate_cell_env.build_env("unit", "localhost:5000/expertaiservices", 18080)
    imported = generate_cell_env.import_operator_values(
        values,
        {
            "OPENAI_API_KEY": "sk-test-not-real",
            "RUNPOD_API_KEY": "rp-test-not-real",
            "UNRELATED_SECRET": "do-not-copy",
        },
    )

    assert "OPENAI_API_KEY" in imported
    assert "RUNPOD_API_KEY" in imported
    assert "UNRELATED_SECRET" not in imported
    assert values["OPENAI_API_KEY"] == "sk-test-not-real"
    assert "UNRELATED_SECRET" not in values


def test_write_output_lists_names_not_values(tmp_path, capsys):
    source = tmp_path / ".env"
    source.write_text("OPENAI_API_KEY=sk-should-not-print\n", encoding="utf-8")
    values = generate_cell_env.build_env("unit", "localhost:5000/expertaiservices", 18080)
    imported = generate_cell_env.import_operator_values(values, generate_cell_env.read_source_env(source))

    print("Variable names imported from source env:")
    for key in imported:
        print(f"- {key}")
    print("No values printed.")

    output = capsys.readouterr().out
    assert "OPENAI_API_KEY" in output
    assert "sk-should-not-print" not in output
