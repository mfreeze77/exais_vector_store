from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Protocol
from urllib.parse import urlsplit


SECRET_MARKERS = ("PASSWORD", "SECRET", "API_KEY", "TOKEN", "PEPPER", "ACCESS_KEY")
SECRET_DSN_KEYS = {"DATABASE_URL", "DATABASE_URL_SYNC", "DATABASE_URL_MIGRATIONS", "SVS_TEST_APP_DSN"}
SECRET_REFERENCE_SCHEMES = {"sops", "age", "vault", "envref"}

_EXTERNAL_REF_RE = re.compile(
    r"^(?P<scheme>sops|age|vault)://(?P<locator>[^#\s]+)#(?P<name>[A-Za-z_][A-Za-z0-9_]*)$"
)
_ENVREF_RE = re.compile(r"^envref://(?P<name>[A-Za-z_][A-Za-z0-9_]*)$")


@dataclass(frozen=True)
class SecretIssue:
    code: str
    keys: tuple[str, ...]


@dataclass(frozen=True)
class SecretReference:
    scheme: str
    locator: str
    name: str


class SecretCommandResult(Protocol):
    returncode: int
    stdout: str | None


SecretCommandRunner = Callable[[list[str]], SecretCommandResult]


class SecretResolutionError(RuntimeError):
    def __init__(self, code: str, reference: SecretReference):
        self.code = code
        self.reference = reference
        super().__init__(f"{code} {reference.scheme} {reference.name}")


def _run_secret_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


class SecretResolver:
    def __init__(
        self,
        *,
        base_dir: Path,
        environ: Mapping[str, str] | None = None,
        command_runner: SecretCommandRunner | None = None,
        sops_binary: str | None = None,
        vault_binary: str | None = None,
    ) -> None:
        self.base_dir = base_dir
        self.environ = environ if environ is not None else os.environ
        self.command_runner = command_runner or _run_secret_command
        self.sops_binary = sops_binary or self.environ.get("SVS_SOPS_BIN") or "sops"
        self.vault_binary = vault_binary or self.environ.get("SVS_VAULT_BIN") or "vault"

    def resolve(self, reference: SecretReference) -> str:
        if reference.scheme == "envref":
            value = self.environ.get(reference.name)
            if value is None:
                raise SecretResolutionError("MISSING_ENV_REFERENCE", reference)
            return _validate_resolved_secret(value, reference)
        if reference.scheme in {"sops", "age"}:
            locator = Path(reference.locator)
            if not locator.is_absolute():
                locator = self.base_dir / locator
            args = [
                self.sops_binary,
                "--decrypt",
                "--extract",
                f'["{reference.name}"]',
                str(locator),
            ]
            return self._resolve_command(args, reference)
        if reference.scheme == "vault":
            args = [
                self.vault_binary,
                "kv",
                "get",
                f"-field={reference.name}",
                reference.locator,
            ]
            return self._resolve_command(args, reference)
        raise SecretResolutionError("UNSUPPORTED_SECRET_SCHEME", reference)

    def _resolve_command(self, args: list[str], reference: SecretReference) -> str:
        try:
            result = self.command_runner(args)
        except OSError as exc:
            raise SecretResolutionError("SECRET_RESOLVER_UNAVAILABLE", reference) from exc
        if result.returncode != 0:
            raise SecretResolutionError("SECRET_RESOLUTION_FAILED", reference)
        value = result.stdout or ""
        if value.endswith("\r\n"):
            value = value[:-2]
        elif value.endswith("\n"):
            value = value[:-1]
        return _validate_resolved_secret(value, reference)


def resolve_secret_values(
    values: Mapping[str, str],
    resolver: SecretResolver,
) -> tuple[dict[str, str], tuple[str, ...]]:
    resolved = dict(values)
    resolved_keys: list[str] = []
    for key in sorted(values):
        value = values[key]
        reference = parse_secret_reference(value)
        if reference is None:
            if looks_like_secret_reference(value):
                malformed = SecretReference(
                    scheme=value.strip().partition("://")[0] or "unknown",
                    locator="",
                    name=key,
                )
                raise SecretResolutionError("INVALID_SECRET_REFERENCE", malformed)
            continue
        resolved[key] = resolver.resolve(reference)
        resolved_keys.append(key)
    return resolved, tuple(resolved_keys)


def _validate_resolved_secret(value: str, reference: SecretReference) -> str:
    if not value:
        raise SecretResolutionError("EMPTY_RESOLVED_SECRET", reference)
    if "\x00" in value or "\n" in value or "\r" in value:
        raise SecretResolutionError("INVALID_RESOLVED_SECRET", reference)
    if looks_like_secret_reference(value):
        raise SecretResolutionError("UNRESOLVED_SECRET_REFERENCE", reference)
    return value


def is_secret_key(key: str) -> bool:
    normalized = key.upper()
    return normalized in SECRET_DSN_KEYS or any(marker in normalized for marker in SECRET_MARKERS)


def looks_like_secret_reference(value: str | None) -> bool:
    if value is None:
        return False
    scheme, sep, _rest = value.strip().partition("://")
    return bool(sep) and scheme in SECRET_REFERENCE_SCHEMES


def parse_secret_reference(value: str | None) -> SecretReference | None:
    if value is None:
        return None
    normalized = value.strip()
    envref_match = _ENVREF_RE.match(normalized)
    if envref_match:
        return SecretReference(scheme="envref", locator="", name=envref_match.group("name"))
    external_match = _EXTERNAL_REF_RE.match(normalized)
    if external_match:
        return SecretReference(
            scheme=external_match.group("scheme"),
            locator=external_match.group("locator"),
            name=external_match.group("name"),
        )
    return None


def is_secret_reference(value: str | None) -> bool:
    return parse_secret_reference(value) is not None


def _has_embedded_url_password(value: str) -> bool:
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return False
    return parsed.password not in {None, ""}


def _secret_reference_issue(key: str, value: str, *, require_external: bool) -> SecretIssue | None:
    if looks_like_secret_reference(value):
        if parse_secret_reference(value) is None:
            return SecretIssue("INVALID_SECRET_REFERENCE", (key,))
        return None
    if _has_embedded_url_password(value):
        return SecretIssue("EMBEDDED_SECRET", (key,))
    if require_external and is_secret_key(key) and value.strip():
        return SecretIssue("PLAINTEXT_SECRET", (key,))
    return None


def validate_secret_references(values: Mapping[str, str], *, require_external: bool = True) -> list[SecretIssue]:
    issues: list[SecretIssue] = []
    for key in sorted(values):
        value = values[key]
        issue = _secret_reference_issue(key, value, require_external=require_external)
        if issue is not None:
            issues.append(issue)
    return _dedupe_issues(issues)


def _dedupe_issues(issues: list[SecretIssue]) -> list[SecretIssue]:
    seen: set[tuple[str, tuple[str, ...]]] = set()
    deduped: list[SecretIssue] = []
    for issue in issues:
        identity = (issue.code, issue.keys)
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(issue)
    return deduped
