from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Mapping
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
