from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "svs_common"))
sys.path.insert(0, str(ROOT / "scripts" / "release"))

from secret_runtime import (  # noqa: E402
    SecretRuntimeError,
    _quote_env_value,
    cleanup_runtime_secret_env,
    prepare_runtime_secret_env,
)
from svs_common.secrets import (  # noqa: E402
    SecretResolutionError,
    SecretResolver,
    parse_secret_reference,
    resolve_secret_values,
)


@pytest.fixture(autouse=True)
def clean_runtime_secret_cache():
    cleanup_runtime_secret_env()
    yield
    cleanup_runtime_secret_env()


def reference(value: str):
    parsed = parse_secret_reference(value)
    assert parsed is not None
    return parsed


def test_resolver_supports_env_sops_age_and_vault_without_printing(capsys, tmp_path):
    calls = []

    def runner(args):
        calls.append(args)
        value = "vault-value\n" if args[0] == "vault" else "encrypted-file-value\n"
        return SimpleNamespace(returncode=0, stdout=value)

    resolver = SecretResolver(
        base_dir=tmp_path,
        environ={"DIRECT_SECRET": "environment-value"},
        command_runner=runner,
    )

    assert resolver.resolve(reference("envref://DIRECT_SECRET")) == "environment-value"
    assert resolver.resolve(reference("sops://secrets/customer.sops.yaml#API_KEY")) == "encrypted-file-value"
    assert resolver.resolve(reference("age://secrets/customer.sops.yaml#PASSWORD")) == "encrypted-file-value"
    assert resolver.resolve(reference("vault://kv/exais/customer#TOKEN")) == "vault-value"

    assert calls[0][:4] == ["sops", "--decrypt", "--extract", '["API_KEY"]']
    assert calls[1][:4] == ["sops", "--decrypt", "--extract", '["PASSWORD"]']
    assert calls[2] == ["vault", "kv", "get", "-field=TOKEN", "kv/exais/customer"]
    assert capsys.readouterr().out == ""


def test_resolution_failures_are_name_only_and_discard_command_output(tmp_path):
    leaked_value = "secret-command-output-must-not-appear"
    resolver = SecretResolver(
        base_dir=tmp_path,
        environ={},
        command_runner=lambda args: SimpleNamespace(returncode=1, stdout=leaked_value),
    )

    with pytest.raises(SecretResolutionError) as exc_info:
        resolver.resolve(reference("vault://kv/exais/customer#DATABASE_URL"))

    rendered = str(exc_info.value)
    assert "SECRET_RESOLUTION_FAILED" in rendered
    assert "DATABASE_URL" in rendered
    assert leaked_value not in rendered


@pytest.mark.parametrize("value", ["", "line-one\n", "line-one\nline-two", "envref://SECOND_SECRET"])
def test_env_resolution_rejects_empty_multiline_and_chained_values(value, tmp_path):
    resolver = SecretResolver(base_dir=tmp_path, environ={"FIRST_SECRET": value})

    with pytest.raises(SecretResolutionError):
        resolver.resolve(reference("envref://FIRST_SECRET"))


def test_resolve_secret_values_rejects_malformed_reference_without_value_leak(tmp_path):
    bad_value = "sops://missing-fragment"
    resolver = SecretResolver(base_dir=tmp_path, environ={})

    with pytest.raises(SecretResolutionError) as exc_info:
        resolve_secret_values({"POSTGRES_PASSWORD": bad_value}, resolver)

    assert exc_info.value.code == "INVALID_SECRET_REFERENCE"
    assert bad_value not in str(exc_info.value)


def test_production_references_materialize_with_restricted_permissions_and_cleanup(tmp_path, capsys):
    source = tmp_path / ".env.cell"
    source.write_text(
        "\n".join(
            [
                "SVS_ENV=prod",
                "SVS_CELL_ENV_FILE=/operator/reference.env",
                "POSTGRES_PASSWORD=envref://RUNTIME_DB_PASSWORD",
                "PUBLIC_SETTING=visible",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    runtime_parent = tmp_path / "runtime"
    runtime_parent.mkdir()

    runtime = prepare_runtime_secret_env(
        source,
        environ={"RUNTIME_DB_PASSWORD": "resolved-db-password"},
        temp_parent=runtime_parent,
    )

    assert runtime is not None
    assert runtime.resolved_keys == ("POSTGRES_PASSWORD",)
    assert runtime.runtime_path.parent.parent == runtime_parent
    assert "resolved-db-password" not in source.read_text(encoding="utf-8")
    body = runtime.runtime_path.read_text(encoding="utf-8")
    assert 'POSTGRES_PASSWORD="resolved-db-password"' in body
    assert f'SVS_CELL_ENV_FILE="{runtime.runtime_path.resolve()}"' in body
    if os.name != "nt":
        assert stat.S_IMODE(runtime.runtime_path.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(runtime.runtime_path.stat().st_mode) == 0o600
    assert capsys.readouterr().out == ""

    cached = prepare_runtime_secret_env(
        source,
        environ={"RUNTIME_DB_PASSWORD": "resolved-db-password"},
        temp_parent=runtime_parent,
    )
    assert cached == runtime

    cleanup_runtime_secret_env(source)
    assert not runtime.runtime_path.parent.exists()


def test_plaintext_production_secret_fails_without_artifact_or_value_leak(tmp_path):
    raw_secret = "plaintext-value-must-not-appear"
    source = tmp_path / ".env.cell"
    source.write_text(f"SVS_ENV=prod\nPOSTGRES_PASSWORD={raw_secret}\n", encoding="utf-8")
    runtime_parent = tmp_path / "runtime"
    runtime_parent.mkdir()

    with pytest.raises(SecretRuntimeError) as exc_info:
        prepare_runtime_secret_env(source, temp_parent=runtime_parent)

    assert "PLAINTEXT_SECRET POSTGRES_PASSWORD" in str(exc_info.value)
    assert raw_secret not in str(exc_info.value)
    assert list(runtime_parent.iterdir()) == []


def test_process_secret_override_cannot_bypass_resolved_reference(tmp_path):
    source = tmp_path / ".env.cell"
    source.write_text(
        "SVS_ENV=prod\nPOSTGRES_PASSWORD=envref://RUNTIME_DB_PASSWORD\n",
        encoding="utf-8",
    )

    with pytest.raises(SecretRuntimeError) as exc_info:
        prepare_runtime_secret_env(
            source,
            environ={
                "RUNTIME_DB_PASSWORD": "approved-value",
                "POSTGRES_PASSWORD": "conflicting-value",
            },
            temp_parent=tmp_path,
        )

    assert "PROCESS_SECRET_OVERRIDE POSTGRES_PASSWORD" in str(exc_info.value)
    assert "approved-value" not in str(exc_info.value)
    assert "conflicting-value" not in str(exc_info.value)


def test_local_cell_env_is_not_materialized(tmp_path):
    source = tmp_path / ".env.cell"
    source.write_text(
        "SVS_ENV=local\nOPENAI_API_KEY=local-development-value\n",
        encoding="utf-8",
    )

    assert prepare_runtime_secret_env(source, temp_parent=tmp_path) is None
    assert list(tmp_path.iterdir()) == [source]


@pytest.mark.parametrize(
    ("value", "encoded"),
    [
        ("plain", '"plain"'),
        ("a$b", '"a$$b"'),
        ('a"b', '"a\\"b"'),
        ("a'b", '"a\'b"'),
        ("ends\\", '"ends\\\\"'),
        ("a\\'b", '"a\\\\\'b"'),
        (" spaces # = ", '" spaces # = "'),
    ],
)
def test_runtime_env_values_use_compose_safe_escaping(value, encoded):
    assert _quote_env_value(value, "SECRET_VALUE") == encoded
