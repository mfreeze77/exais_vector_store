from __future__ import annotations

import atexit
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "svs_common"))

from svs_common.secrets import (  # noqa: E402
    SecretCommandRunner,
    SecretIssue,
    SecretResolver,
    resolve_secret_values,
    validate_secret_references,
)

LOCAL_ENVIRONMENTS = {"local", "dev", "development", "test", "testing", "ci"}
ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class RuntimeSecretEnv:
    reference_path: Path
    runtime_path: Path
    resolved_keys: tuple[str, ...]


class SecretRuntimeError(RuntimeError):
    def __init__(self, issues: list[SecretIssue]):
        self.issues = tuple(issues)
        summary = "; ".join(f"{issue.code} {','.join(issue.keys)}" for issue in issues)
        super().__init__(summary)


_RUNTIME_ENVS: dict[Path, RuntimeSecretEnv] = {}


def read_reference_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        normalized = value.strip()
        if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in {"'", '"'}:
            normalized = normalized[1:-1]
        values[key.strip()] = normalized
    return values


def is_production_environment(values: Mapping[str, str]) -> bool:
    return (values.get("SVS_ENV") or "").strip().lower() not in LOCAL_ENVIRONMENTS


def prepare_runtime_secret_env(
    reference_path: Path,
    *,
    environ: Mapping[str, str] | None = None,
    command_runner: SecretCommandRunner | None = None,
    temp_parent: Path | None = None,
) -> RuntimeSecretEnv | None:
    source = reference_path.resolve()
    values = read_reference_env(source)
    if not is_production_environment(values):
        return None
    cached = _RUNTIME_ENVS.get(source)
    if cached is not None and cached.runtime_path.exists():
        return cached

    issues = validate_secret_references(values, require_external=True)
    if issues:
        raise SecretRuntimeError(issues)

    runtime_environ = environ if environ is not None else os.environ
    resolver = SecretResolver(
        base_dir=ROOT,
        environ=runtime_environ,
        command_runner=command_runner,
    )
    resolved, resolved_keys = resolve_secret_values(values, resolver)
    if not resolved_keys:
        return None
    conflicting_overrides = sorted(
        key
        for key in resolved_keys
        if key in runtime_environ and runtime_environ[key] != resolved[key]
    )
    if conflicting_overrides:
        raise SecretRuntimeError(
            [SecretIssue("PROCESS_SECRET_OVERRIDE", (key,)) for key in conflicting_overrides]
        )

    parent = str(temp_parent.resolve()) if temp_parent is not None else None
    runtime_dir = Path(tempfile.mkdtemp(prefix="exais-secrets-", dir=parent))
    runtime_path = runtime_dir / ".env.runtime"
    try:
        os.chmod(runtime_dir, 0o700)
        resolved["SVS_CELL_ENV_FILE"] = str(runtime_path.resolve())
        _write_runtime_env(runtime_path, resolved)
        runtime = RuntimeSecretEnv(source, runtime_path, resolved_keys)
        _RUNTIME_ENVS[source] = runtime
        return runtime
    except BaseException:
        _remove_runtime_dir(runtime_dir)
        raise


def runtime_env_path(reference_path: Path, **kwargs) -> Path:
    runtime = prepare_runtime_secret_env(reference_path, **kwargs)
    return runtime.runtime_path if runtime is not None else reference_path


def cleanup_runtime_secret_env(reference_path: Path | None = None) -> None:
    if reference_path is None:
        sources = list(_RUNTIME_ENVS)
    else:
        sources = [reference_path.resolve()]
    for source in sources:
        runtime = _RUNTIME_ENVS.get(source)
        if runtime is None:
            continue
        _remove_runtime_dir(runtime.runtime_path.parent)
        _RUNTIME_ENVS.pop(source, None)


def _remove_runtime_dir(path: Path) -> None:
    try:
        shutil.rmtree(path)
    except FileNotFoundError:
        pass


def _write_runtime_env(path: Path, values: Mapping[str, str]) -> None:
    lines = [
        "# Ephemeral resolved cell environment. Never commit or retain this file.",
        "# Generated from validated secret references for one release command.",
    ]
    for key in sorted(values):
        if not ENV_KEY_RE.fullmatch(key):
            raise SecretRuntimeError([SecretIssue("INVALID_ENV_KEY", (key,))])
        lines.append(f"{key}={_quote_env_value(values[key], key)}")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(lines) + "\n")
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    os.chmod(path, 0o600)


def _quote_env_value(value: str, key: str) -> str:
    if "\x00" in value or "\n" in value or "\r" in value:
        raise SecretRuntimeError([SecretIssue("INVALID_ENV_VALUE", (key,))])
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "$$")
    return f'"{escaped}"'


atexit.register(cleanup_runtime_secret_env)
