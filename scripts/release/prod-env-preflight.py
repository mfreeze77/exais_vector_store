from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from release_common import ROOT, version

sys.path.insert(0, str(ROOT / "packages" / "svs_common"))
from svs_common.secrets import is_secret_key, looks_like_secret_reference, validate_secret_references


LOCAL_ENVS = {"local", "dev", "development", "test", "testing", "ci"}
PLACEHOLDER_MARKERS = (
    "replace-with",
    "change-me",
    "changeme",
    "example",
    "dev_password",
    "svs_owner_dev_password",
    "svs_app_dev_password",
    "svs_minio_password",
)

REQUIRED_KEYS = {
    "SVS_ENV",
    "SVS_PRODUCT_VERSION",
    "SVS_VERSION",
    "SVS_REGISTRY_PREFIX",
    "SVS_RELEASE_CHANNEL",
    "SVS_CELL_ENV_FILE",
    "SVS_DEV_MODE",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_DB",
    "POSTGRES_APP_USER",
    "POSTGRES_APP_PASSWORD",
    "DATABASE_URL",
    "DATABASE_URL_SYNC",
    "DATABASE_URL_MIGRATIONS",
    "REDIS_URL",
    "QDRANT_URL",
    "QDRANT_COLLECTION_PREFIX",
    "SVS_DENSE_BACKEND",
    "SVS_SPARSE_BACKEND",
    "S3_ENDPOINT_URL",
    "S3_ACCESS_KEY_ID",
    "S3_SECRET_ACCESS_KEY",
    "S3_BUCKET",
    "S3_REGION",
    "DEFAULT_EMBEDDING_PROVIDER",
    "MODEL_GATEWAY_URL",
    "SVS_API_KEY_PEPPER",
    "SVS_ALLOWED_CORS_ORIGINS",
    "SVS_BIND_IP",
    "SVS_INDEX_STRICT",
    "SVS_OBJECT_STORE_STRICT",
}

PORT_KEYS = [
    "SVS_API_PORT",
    "SVS_MODEL_GATEWAY_PORT",
    "SVS_ADMIN_UI_PORT",
    "SVS_INSTANCE_AGENT_PORT",
    "SVS_POSTGRES_PORT",
    "SVS_REDIS_PORT",
    "SVS_QDRANT_HTTP_PORT",
    "SVS_QDRANT_GRPC_PORT",
    "SVS_MINIO_PORT",
    "SVS_MINIO_CONSOLE_PORT",
]

PROVIDER_REQUIREMENTS = {
    "anthropic": ["ANTHROPIC_API_KEY"],
    "openai": ["OPENAI_API_KEY"],
    "runpod": ["RUNPOD_API_KEY", "RUNPOD_EMBEDDING_ENDPOINT_URL"],
    "voyage": ["VOYAGE_API_KEY"],
    "cohere": ["COHERE_API_KEY"],
    "jina": ["JINA_API_KEY"],
    "tei": ["TEI_ENDPOINT_URL"],
    "infinity": ["INFINITY_ENDPOINT_URL"],
}


@dataclass(frozen=True)
class Issue:
    code: str
    keys: tuple[str, ...]


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = strip_quotes(value.strip())
    return values


def strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def is_blank(value: str | None) -> bool:
    return value is None or value.strip() == ""


def has_placeholder(key: str, value: str | None) -> bool:
    if value is None:
        return False
    normalized = value.strip().lower()
    if not normalized:
        return False
    if looks_like_secret_reference(value):
        return False
    if is_secret_key(key) and normalized in {"admin", "password", "secret", "token", "key"}:
        return True
    return any(marker in normalized for marker in PLACEHOLDER_MARKERS)


def bool_value(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def is_public_bind(value: str | None) -> bool:
    normalized = (value or "").strip().lower()
    return normalized in {"0.0.0.0", "::", "[::]", ""}


def provider_requirements(provider: str) -> list[str]:
    normalized = provider.strip().lower().replace("_", "-")
    return PROVIDER_REQUIREMENTS.get(normalized, [])


def validate_ports(values: dict[str, str]) -> list[Issue]:
    issues: list[Issue] = []
    seen: dict[int, str] = {}
    for key in PORT_KEYS:
        value = values.get(key)
        if is_blank(value):
            issues.append(Issue("MISSING", (key,)))
            continue
        try:
            port = int(str(value))
        except ValueError:
            issues.append(Issue("INVALID_PORT", (key,)))
            continue
        if port < 1 or port > 65535:
            issues.append(Issue("INVALID_PORT", (key,)))
            continue
        if port in seen:
            issues.append(Issue("PORT_COLLISION", (seen[port], key)))
        else:
            seen[port] = key
    return issues


def validate_env(values: dict[str, str], expected_version: str, *, allow_local_registry: bool = False) -> list[Issue]:
    issues: list[Issue] = []
    for key in sorted(REQUIRED_KEYS):
        if is_blank(values.get(key)):
            issues.append(Issue("MISSING", (key,)))

    svs_env = (values.get("SVS_ENV") or "").strip().lower()
    if svs_env in LOCAL_ENVS:
        issues.append(Issue("LOCAL_ENV", ("SVS_ENV",)))
    if bool_value(values.get("SVS_DEV_MODE")):
        issues.append(Issue("DEV_MODE_ENABLED", ("SVS_DEV_MODE",)))
    if (values.get("SVS_RELEASE_CHANNEL") or "").strip().lower() in {"", "dev", "local", "test", "latest"}:
        issues.append(Issue("BAD_RELEASE_CHANNEL", ("SVS_RELEASE_CHANNEL",)))

    for key in ("SVS_VERSION", "SVS_PRODUCT_VERSION"):
        value = values.get(key)
        if value and value != expected_version:
            issues.append(Issue("BAD_VERSION", (key,)))
        if (value or "").strip().lower() == "latest":
            issues.append(Issue("LATEST_TAG", (key,)))

    registry = (values.get("SVS_REGISTRY_PREFIX") or "").strip()
    registry_host = registry.split("/", 1)[0].lower()
    if not registry or "/" not in registry:
        issues.append(Issue("BAD_REGISTRY_PREFIX", ("SVS_REGISTRY_PREFIX",)))
    if not allow_local_registry and (registry_host.startswith("localhost") or registry_host.startswith("127.") or registry_host.startswith("0.0.0.0")):
        issues.append(Issue("LOCAL_REGISTRY_PREFIX", ("SVS_REGISTRY_PREFIX",)))
    if registry.endswith(":latest") or ":latest/" in registry:
        issues.append(Issue("LATEST_TAG", ("SVS_REGISTRY_PREFIX",)))

    if any(origin.strip() == "*" for origin in (values.get("SVS_ALLOWED_CORS_ORIGINS") or "").split(",")):
        issues.append(Issue("WILDCARD_CORS", ("SVS_ALLOWED_CORS_ORIGINS",)))
    if is_public_bind(values.get("SVS_BIND_IP")):
        issues.append(Issue("PUBLIC_COMPOSE_BIND", ("SVS_BIND_IP",)))
    if (values.get("OPENSEARCH_URL") or "").startswith("https://") and not bool_value(values.get("OPENSEARCH_VERIFY_CERTS")):
        issues.append(Issue("TLS_VERIFY_DISABLED", ("OPENSEARCH_VERIFY_CERTS",)))
    if not bool_value(values.get("SVS_OBJECT_STORE_STRICT")):
        issues.append(Issue("OBJECT_STORE_NOT_STRICT", ("SVS_OBJECT_STORE_STRICT",)))

    if (values.get("POSTGRES_APP_USER") or "") and values.get("POSTGRES_APP_USER") == values.get("POSTGRES_USER"):
        issues.append(Issue("APP_DB_ROLE_IS_OWNER", ("POSTGRES_APP_USER", "POSTGRES_USER")))
    runtime_dsn = values.get("DATABASE_URL") or ""
    if not looks_like_secret_reference(runtime_dsn) and "svs_owner" in runtime_dsn:
        issues.append(Issue("RUNTIME_DSN_USES_OWNER", ("DATABASE_URL",)))

    provider = (values.get("DEFAULT_EMBEDDING_PROVIDER") or "").strip().lower()
    if provider in {"hash_mock", "mock", "fake"}:
        issues.append(Issue("MOCK_PROVIDER", ("DEFAULT_EMBEDDING_PROVIDER",)))
    required_provider_keys = provider_requirements(provider)
    for key in required_provider_keys:
        if is_blank(values.get(key)):
            issues.append(Issue("MISSING_PROVIDER_SETTING", (key,)))

    required_secret_keys = {key for key in REQUIRED_KEYS if is_secret_key(key)} | set(required_provider_keys)
    for key, value in values.items():
        if has_placeholder(key, value):
            issues.append(Issue("PLACEHOLDER", (key,)))
        elif key in required_secret_keys and is_secret_key(key) and is_blank(value):
            issues.append(Issue("MISSING_SECRET", (key,)))

    for issue in validate_secret_references(values, require_external=True):
        issues.append(Issue(issue.code, issue.keys))

    issues.extend(validate_ports(values))
    return dedupe_issues(issues)


def dedupe_issues(issues: list[Issue]) -> list[Issue]:
    seen: set[tuple[str, tuple[str, ...]]] = set()
    deduped: list[Issue] = []
    for issue in issues:
        key = (issue.code, issue.keys)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(issue)
    return deduped


def checked_keys(values: dict[str, str]) -> list[str]:
    return sorted(set(values) | REQUIRED_KEYS | set(PORT_KEYS))


def render_report(env_path: Path, values: dict[str, str], issues: list[Issue], expected_version: str) -> str:
    lines = [
        "Production env preflight",
        f"env_file={env_path}",
        f"expected_version={expected_version}",
        "Checked variable names:",
    ]
    for key in checked_keys(values):
        lines.append(f"- {key}")
    lines.append(f"Issue count: {len(issues)}")
    for issue in issues:
        lines.append(f"FAIL {issue.code} {','.join(issue.keys)}")
    lines.append("PREFLIGHT FAILED" if issues else "PREFLIGHT PASS")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Secret-safe preflight for production cell env files.")
    parser.add_argument("--env-file", required=True)
    parser.add_argument("--expected-version", default=version())
    parser.add_argument("--allow-local-registry", action="store_true")
    args = parser.parse_args()

    env_path = Path(args.env_file)
    if not env_path.is_absolute():
        env_path = ROOT / env_path
    values = read_env_file(env_path)
    issues = validate_env(values, args.expected_version, allow_local_registry=args.allow_local_registry)
    print(render_report(env_path, values, issues, args.expected_version), end="")
    raise SystemExit(1 if issues else 0)


if __name__ == "__main__":
    main()
