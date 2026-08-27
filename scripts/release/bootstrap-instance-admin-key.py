#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import secrets
from typing import Any
import uuid


ROOT = Path(__file__).resolve().parents[2]
API_KEY_PREFIX = "svs_live_"


DEFAULT_ADMIN_SCOPES = (
    "admin:read",
    "api_keys:read",
    "api_keys:write",
    "vector_stores:read",
    "vector_stores:write",
    "documents:write",
    "retrieval:read",
)


@dataclass(frozen=True)
class BootstrapConfig:
    database_url: str
    api_key_pepper: str
    tenant_id: str
    tenant_name: str
    tenant_slug: str
    business_instance_id: str
    business_name: str
    business_slug: str
    user_id: str
    user_email: str
    user_display_name: str
    group_id: str
    group_name: str
    group_slug: str
    knowledge_base_id: str
    knowledge_base_name: str
    knowledge_base_slug: str
    label: str
    scopes: tuple[str, ...]
    max_security_level: int
    expires_at: int | None = None
    ensure_records: bool = True
    print_secret: bool = False
    secret_output: Path | None = None


def parse_scope_list(value: str | None) -> tuple[str, ...]:
    scopes = tuple(scope.strip() for scope in (value or "").split(",") if scope.strip())
    if not scopes:
        raise ValueError("at least one API-key scope is required")
    return scopes


def validate_max_security_level(value: int) -> int:
    if value < 0 or value > 5:
        raise ValueError("max security level must be between 0 and 5")
    return value


def redact_api_key(value: str) -> str:
    return value[:9] + "..." + value[-6:] if len(value) > 16 else "<redacted>"


def generate_api_key() -> str:
    return API_KEY_PREFIX + secrets.token_urlsafe(32)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:24]}"


def api_key_hash(raw_key: str, pepper: str) -> str:
    return hashlib.sha256((raw_key + ":" + pepper).encode("utf-8")).hexdigest()


def validate_secret_output_path(path: Path | None, *, repo_root: Path = ROOT) -> Path | None:
    if path is None:
        return None
    resolved = path.expanduser().resolve()
    root = repo_root.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return resolved
    raise ValueError(f"secret output path must be outside the repository: {resolved}")


def normalize_database_url(value: str) -> str:
    return value.replace("postgresql+psycopg://", "postgresql://")


def set_bootstrap_rls_context(conn: Any, config: BootstrapConfig) -> None:
    conn.execute("select set_config('svs.tenant_id', %s, true)", (config.tenant_id,))
    conn.execute("select set_config('svs.business_instance_id', %s, true)", (config.business_instance_id,))
    conn.execute("select set_config('svs.max_security_level', %s, true)", (str(config.max_security_level),))


def ensure_minimum_instance_records(conn: Any, config: BootstrapConfig) -> None:
    conn.execute(
        """
        INSERT INTO tenants(id, name, slug)
        VALUES (%s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (config.tenant_id, config.tenant_name, config.tenant_slug),
    )
    conn.execute(
        """
        INSERT INTO business_instances(id, tenant_id, name, slug)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (config.business_instance_id, config.tenant_id, config.business_name, config.business_slug),
    )
    conn.execute(
        """
        INSERT INTO users(id, tenant_id, email, display_name)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (config.user_id, config.tenant_id, config.user_email, config.user_display_name),
    )
    conn.execute(
        """
        INSERT INTO groups(id, tenant_id, business_instance_id, name, slug)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (config.group_id, config.tenant_id, config.business_instance_id, config.group_name, config.group_slug),
    )
    conn.execute(
        """
        INSERT INTO group_memberships(tenant_id, group_id, user_id, role)
        VALUES (%s, %s, %s, 'owner')
        ON CONFLICT DO NOTHING
        """,
        (config.tenant_id, config.group_id, config.user_id),
    )
    conn.execute(
        """
        INSERT INTO knowledge_bases(id, tenant_id, business_instance_id, name, slug)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (
            config.knowledge_base_id,
            config.tenant_id,
            config.business_instance_id,
            config.knowledge_base_name,
            config.knowledge_base_slug,
        ),
    )


def bootstrap_first_admin_key(
    conn: Any,
    config: BootstrapConfig,
    *,
    raw_key: str | None = None,
    key_id: str | None = None,
) -> tuple[dict[str, Any], str]:
    validate_max_security_level(config.max_security_level)
    set_bootstrap_rls_context(conn, config)
    if config.ensure_records:
        ensure_minimum_instance_records(conn, config)

    raw = raw_key or generate_api_key()
    created_key_id = key_id or new_id("key")
    expires_sql = "to_timestamp(%s)" if config.expires_at is not None else "NULL"
    params: tuple[Any, ...]
    if config.expires_at is not None:
        params = (
            created_key_id,
            config.tenant_id,
            config.business_instance_id,
            config.user_id,
            api_key_hash(raw, config.api_key_pepper),
            config.label,
            list(config.scopes),
            config.max_security_level,
            config.expires_at,
        )
    else:
        params = (
            created_key_id,
            config.tenant_id,
            config.business_instance_id,
            config.user_id,
            api_key_hash(raw, config.api_key_pepper),
            config.label,
            list(config.scopes),
            config.max_security_level,
        )
    conn.execute(
        f"""
        INSERT INTO api_keys(
          id, tenant_id, business_instance_id, user_id, key_hash, label,
          scopes, max_security_level, expires_at, status
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, {expires_sql}, 'active')
        """,
        params,
    )
    if hasattr(conn, "commit"):
        conn.commit()
    metadata = {
        "id": created_key_id,
        "label": config.label,
        "tenant_id": config.tenant_id,
        "business_instance_id": config.business_instance_id,
        "user_id": config.user_id,
        "scopes": list(config.scopes),
        "max_security_level": config.max_security_level,
        "redacted_value": redact_api_key(raw),
    }
    if config.expires_at is not None:
        metadata["expires_at"] = config.expires_at
    return metadata, raw


def write_secret_output(path: Path, metadata: dict[str, Any], raw_key: str) -> None:
    payload = {
        "api_key": raw_key,
        "metadata": metadata,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bootstrap the first customer-instance admin API key with owner DB credentials."
    )
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--api-key-pepper", default=os.getenv("SVS_API_KEY_PEPPER"))
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--tenant-name", required=True)
    parser.add_argument("--tenant-slug", required=True)
    parser.add_argument("--business-instance-id", required=True)
    parser.add_argument("--business-name", required=True)
    parser.add_argument("--business-slug", required=True)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--user-email", required=True)
    parser.add_argument("--user-display-name", required=True)
    parser.add_argument("--group-id", required=True)
    parser.add_argument("--group-name", default="Admins")
    parser.add_argument("--group-slug", default="admins")
    parser.add_argument("--knowledge-base-id", required=True)
    parser.add_argument("--knowledge-base-name", required=True)
    parser.add_argument("--knowledge-base-slug", required=True)
    parser.add_argument("--label", default="bootstrap-admin")
    parser.add_argument("--scopes", default=",".join(DEFAULT_ADMIN_SCOPES))
    parser.add_argument("--max-security-level", type=int, default=5)
    parser.add_argument("--expires-at", type=int)
    parser.add_argument("--skip-record-bootstrap", action="store_true")
    parser.add_argument("--print-secret", action="store_true")
    parser.add_argument("--secret-output", type=Path)
    return parser


def config_from_args(args: argparse.Namespace) -> BootstrapConfig:
    if not args.database_url:
        raise ValueError("DATABASE_URL or --database-url is required")
    if not args.api_key_pepper:
        raise ValueError("SVS_API_KEY_PEPPER or --api-key-pepper is required")
    secret_output = validate_secret_output_path(args.secret_output)
    if not args.print_secret and secret_output is None:
        raise ValueError("provide --secret-output outside the repo or use --print-secret")
    return BootstrapConfig(
        database_url=normalize_database_url(args.database_url),
        api_key_pepper=args.api_key_pepper,
        tenant_id=args.tenant_id,
        tenant_name=args.tenant_name,
        tenant_slug=args.tenant_slug,
        business_instance_id=args.business_instance_id,
        business_name=args.business_name,
        business_slug=args.business_slug,
        user_id=args.user_id,
        user_email=args.user_email,
        user_display_name=args.user_display_name,
        group_id=args.group_id,
        group_name=args.group_name,
        group_slug=args.group_slug,
        knowledge_base_id=args.knowledge_base_id,
        knowledge_base_name=args.knowledge_base_name,
        knowledge_base_slug=args.knowledge_base_slug,
        label=args.label,
        scopes=parse_scope_list(args.scopes),
        max_security_level=validate_max_security_level(args.max_security_level),
        expires_at=args.expires_at,
        ensure_records=not args.skip_record_bootstrap,
        print_secret=bool(args.print_secret),
        secret_output=secret_output,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        config = config_from_args(parser.parse_args(argv))
    except ValueError as exc:
        parser.error(str(exc))

    import psycopg

    with psycopg.connect(config.database_url) as conn:
        metadata, raw_key = bootstrap_first_admin_key(conn, config)

    if config.secret_output:
        write_secret_output(config.secret_output, metadata, raw_key)
        metadata = {**metadata, "secret_output": str(config.secret_output)}

    output = dict(metadata)
    if config.print_secret:
        output["api_key"] = raw_key
    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
