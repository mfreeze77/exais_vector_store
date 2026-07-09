from __future__ import annotations

import argparse
import sys
from pathlib import Path

from release_common import DEFAULT_CELL, DEFAULT_REGISTRY_PREFIX, env_file, project_name, release_dir, version

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "svs_common"))
from svs_common.secrets import SecretIssue, is_secret_key, is_secret_reference, validate_secret_references

OPERATOR_IMPORT_KEYS = {
    "DEFAULT_EMBEDDING_PROVIDER",
    "OPENAI_API_KEY",
    "OPENAI_EMBEDDING_MODEL",
    "OPENAI_EMBEDDING_DIMENSIONS",
    "TEI_ENDPOINT_URL",
    "INFINITY_ENDPOINT_URL",
    "RUNPOD_EMBEDDING_ENDPOINT_URL",
    "RUNPOD_API_KEY",
    "RUNPOD_ENDPOINT_ID",
    "MARKER_RUNPOD_API_KEY",
    "MARKER_RUNPOD_ENDPOINT_ID",
    "MARKER_MODE",
    "MARKER_TIMEOUT_SEC",
    "MARKER_POLL_INTERVAL_SEC",
    "MARKER_MAX_ATTEMPTS",
    "MARKER_RETRY_BACKOFF_SEC",
    "VOYAGE_API_KEY",
    "COHERE_API_KEY",
    "JINA_API_KEY",
}


PRODUCTION_REFERENCE_OPTIONAL_KEYS = {
    "OPENSEARCH_PASSWORD",
    "QDRANT_API_KEY",
    "RUNPOD_API_KEY",
    "MARKER_RUNPOD_API_KEY",
    "VOYAGE_API_KEY",
    "COHERE_API_KEY",
    "JINA_API_KEY",
}


def read_source_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        raise FileNotFoundError(f"source env file not found: {path}")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        values[key.strip()] = value
    return values


def build_env(cell: str, registry_prefix: str, api_port: int) -> dict[str, str]:
    cell_env = env_file(cell).resolve().as_posix()
    return {
        "SVS_CELL_NAME": cell,
        "SVS_CELL_PROJECT": project_name(cell),
        "SVS_CELL_ENV_FILE": cell_env,
        "SVS_VERSION": version(),
        "SVS_PRODUCT_VERSION": version(),
        "SVS_REGISTRY_PREFIX": registry_prefix.rstrip("/"),
        "SVS_RELEASE_CHANNEL": "local-registry",
        "SVS_ENV": "local",
        "SVS_DEV_MODE": "true",
        "SVS_DEV_TENANT_ID": "ten_dev",
        "SVS_DEV_BUSINESS_INSTANCE_ID": "biz_dev",
        "SVS_DEV_USER_ID": "usr_dev",
        "SVS_DEV_GROUPS": "grp_admin,grp_eng,admins,engineering",
        "SVS_DEV_ROLES": "owner,admin",
        "SVS_DEV_MAX_SECURITY_LEVEL": "5",
        "POSTGRES_USER": "svs_owner",
        "POSTGRES_PASSWORD": "svs_owner_dev_password",
        "POSTGRES_DB": "svs",
        "POSTGRES_APP_USER": "svs_app",
        "POSTGRES_APP_PASSWORD": "svs_app_dev_password",
        "DATABASE_URL": "postgresql+psycopg://svs_app:svs_app_dev_password@postgres:5432/svs",
        "DATABASE_URL_SYNC": "postgresql://svs_owner:svs_owner_dev_password@postgres:5432/svs",
        "DATABASE_URL_MIGRATIONS": "postgresql://svs_owner:svs_owner_dev_password@postgres:5432/svs",
        "SVS_TEST_APP_DSN": "postgresql://svs_app:svs_app_dev_password@postgres:5432/svs",
        "SVS_TEST_QDRANT_URL": "http://qdrant:6333",
        "SVS_TEST_QDRANT_OUTAGE_URL": "http://127.0.0.1:65534",
        "REDIS_URL": "redis://redis:6379/0",
        "QDRANT_URL": "http://qdrant:6333",
        "QDRANT_API_KEY": "",
        "QDRANT_COLLECTION_PREFIX": "svs_",
        "OPENSEARCH_URL": "http://opensearch:9200",
        "OPENSEARCH_USER": "admin",
        "OPENSEARCH_PASSWORD": "admin",
        "OPENSEARCH_INDEX_PREFIX": "svs_",
        "OPENSEARCH_VERIFY_CERTS": "true",
        "S3_ENDPOINT_URL": "http://minio:9000",
        "S3_ACCESS_KEY_ID": "svs_minio",
        "S3_SECRET_ACCESS_KEY": "svs_minio_password",
        "S3_BUCKET": "exai-vector-store-local",
        "S3_REGION": "us-east-1",
        "SVS_LOCAL_OBJECT_STORE_PATH": "/data/object-store",
        "SVS_OBJECT_STORE_STRICT": "false",
        "DEFAULT_EMBEDDING_PROVIDER": "hash_mock",
        "OPENAI_API_KEY": "",
        "OPENAI_EMBEDDING_MODEL": "text-embedding-3-small",
        "OPENAI_EMBEDDING_DIMENSIONS": "1536",
        "MODEL_GATEWAY_URL": "http://model-gateway:8081",
        "TEI_ENDPOINT_URL": "",
        "INFINITY_ENDPOINT_URL": "",
        "RUNPOD_EMBEDDING_ENDPOINT_URL": "",
        "RUNPOD_API_KEY": "",
        "RUNPOD_ENDPOINT_ID": "",
        "MARKER_RUNPOD_API_KEY": "",
        "MARKER_RUNPOD_ENDPOINT_ID": "",
        "MARKER_MODE": "remote",
        "MARKER_TIMEOUT_SEC": "1800",
        "MARKER_POLL_INTERVAL_SEC": "3",
        "MARKER_MAX_ATTEMPTS": "2",
        "MARKER_RETRY_BACKOFF_SEC": "5",
        "VOYAGE_API_KEY": "",
        "COHERE_API_KEY": "",
        "JINA_API_KEY": "",
        "SVS_API_KEY_PEPPER": "change-me-in-prod",
        "SVS_ALLOWED_CORS_ORIGINS": f"http://localhost:13080,http://localhost:{api_port}",
        "SVS_PUBLIC_API_BASE": f"http://localhost:{api_port}",
        "SVS_INSTANCE_MANIFEST": "/app/instances/dev/instance.yaml",
        "SVS_SPARSE_BACKEND": "postgres_fts",
        "SVS_DENSE_BACKEND": "qdrant",
        "SVS_INDEX_STRICT": "true",
        "SVS_INGEST_INLINE_MAX_BYTES": "262144",
        "SVS_DEFAULT_RATE_LIMIT_PER_MINUTE": "120",
        "SVS_ADMIN_RATE_LIMIT_PER_MINUTE": "30",
        "SVS_IDEMPOTENCY_TTL_HOURS": "24",
        "SVS_REQUEST_BODY_LIMIT_BYTES": "52428800",
        "SVS_REINDEX_BATCH_SIZE": "1000",
        "SVS_WORKER_POLL_SECONDS": "0.05",
        "SVS_API_PORT": str(api_port),
        "SVS_MODEL_GATEWAY_PORT": "18081",
        "SVS_ADMIN_UI_PORT": "13080",
        "SVS_INSTANCE_AGENT_PORT": "18090",
        "SVS_POSTGRES_PORT": "15432",
        "SVS_REDIS_PORT": "16379",
        "SVS_QDRANT_HTTP_PORT": "16333",
        "SVS_QDRANT_GRPC_PORT": "16334",
        "SVS_MINIO_PORT": "19000",
        "SVS_MINIO_CONSOLE_PORT": "19001",
    }


def build_production_reference_env(
    cell: str,
    registry_prefix: str,
    api_port: int,
    *,
    public_api_base: str = "https://api.expertaiservices.com",
    admin_origin: str = "https://admin.expertaiservices.com",
) -> dict[str, str]:
    cell_env = env_file(cell).resolve().as_posix()
    return {
        "SVS_CELL_NAME": cell,
        "SVS_CELL_PROJECT": project_name(cell),
        "SVS_CELL_ENV_FILE": cell_env,
        "SVS_VERSION": version(),
        "SVS_PRODUCT_VERSION": version(),
        "SVS_REGISTRY_PREFIX": registry_prefix.rstrip("/"),
        "SVS_RELEASE_CHANNEL": "prod",
        "SVS_ENV": "prod",
        "SVS_DEV_MODE": "false",
        "SVS_DEV_TENANT_ID": "",
        "SVS_DEV_BUSINESS_INSTANCE_ID": "",
        "SVS_DEV_USER_ID": "",
        "SVS_DEV_GROUPS": "",
        "SVS_DEV_ROLES": "",
        "SVS_DEV_MAX_SECURITY_LEVEL": "0",
        "POSTGRES_USER": "svs_owner",
        "POSTGRES_PASSWORD": "",
        "POSTGRES_DB": "svs",
        "POSTGRES_APP_USER": "svs_app",
        "POSTGRES_APP_PASSWORD": "",
        "DATABASE_URL": "",
        "DATABASE_URL_SYNC": "",
        "DATABASE_URL_MIGRATIONS": "",
        "REDIS_URL": "redis://redis:6379/0",
        "QDRANT_URL": "http://qdrant:6333",
        "QDRANT_API_KEY": "",
        "QDRANT_COLLECTION_PREFIX": "svs_",
        "OPENSEARCH_URL": "https://opensearch.expertaiservices.internal:9200",
        "OPENSEARCH_USER": "admin",
        "OPENSEARCH_PASSWORD": "",
        "OPENSEARCH_INDEX_PREFIX": "svs_",
        "OPENSEARCH_VERIFY_CERTS": "true",
        "S3_ENDPOINT_URL": "https://object-storage.expertaiservices.internal",
        "S3_ACCESS_KEY_ID": "",
        "S3_SECRET_ACCESS_KEY": "",
        "S3_BUCKET": "exai-vector-store-prod",
        "S3_REGION": "us-east-1",
        "SVS_LOCAL_OBJECT_STORE_PATH": "/var/lib/svs/object-store",
        "SVS_OBJECT_STORE_STRICT": "true",
        "DEFAULT_EMBEDDING_PROVIDER": "openai",
        "OPENAI_API_KEY": "",
        "OPENAI_EMBEDDING_MODEL": "text-embedding-3-small",
        "OPENAI_EMBEDDING_DIMENSIONS": "1536",
        "MODEL_GATEWAY_URL": "http://model-gateway:8081",
        "TEI_ENDPOINT_URL": "",
        "INFINITY_ENDPOINT_URL": "",
        "RUNPOD_EMBEDDING_ENDPOINT_URL": "",
        "RUNPOD_API_KEY": "",
        "RUNPOD_ENDPOINT_ID": "",
        "MARKER_RUNPOD_API_KEY": "",
        "MARKER_RUNPOD_ENDPOINT_ID": "",
        "MARKER_MODE": "remote",
        "MARKER_TIMEOUT_SEC": "1800",
        "MARKER_POLL_INTERVAL_SEC": "3",
        "MARKER_MAX_ATTEMPTS": "2",
        "MARKER_RETRY_BACKOFF_SEC": "5",
        "VOYAGE_API_KEY": "",
        "COHERE_API_KEY": "",
        "JINA_API_KEY": "",
        "SVS_API_KEY_PEPPER": "",
        "SVS_ALLOWED_CORS_ORIGINS": f"{admin_origin},{public_api_base}",
        "SVS_PUBLIC_API_BASE": public_api_base,
        "SVS_INSTANCE_MANIFEST": "/opt/exais/vector-store/instance.yaml",
        "SVS_SPARSE_BACKEND": "postgres_fts",
        "SVS_DENSE_BACKEND": "qdrant",
        "SVS_INDEX_STRICT": "true",
        "SVS_INGEST_INLINE_MAX_BYTES": "262144",
        "SVS_DEFAULT_RATE_LIMIT_PER_MINUTE": "120",
        "SVS_ADMIN_RATE_LIMIT_PER_MINUTE": "30",
        "SVS_IDEMPOTENCY_TTL_HOURS": "24",
        "SVS_REQUEST_BODY_LIMIT_BYTES": "52428800",
        "SVS_REINDEX_BATCH_SIZE": "1000",
        "SVS_API_PORT": str(api_port),
        "SVS_MODEL_GATEWAY_PORT": "18081",
        "SVS_ADMIN_UI_PORT": "13080",
        "SVS_INSTANCE_AGENT_PORT": "18090",
        "SVS_POSTGRES_PORT": "15432",
        "SVS_REDIS_PORT": "16379",
        "SVS_QDRANT_HTTP_PORT": "16333",
        "SVS_QDRANT_GRPC_PORT": "16334",
        "SVS_MINIO_PORT": "19000",
        "SVS_MINIO_CONSOLE_PORT": "19001",
    }


def import_operator_values(values: dict[str, str], source_values: dict[str, str]) -> list[str]:
    imported: list[str] = []
    for key in sorted(OPERATOR_IMPORT_KEYS):
        if source_values.get(key):
            values[key] = source_values[key]
            imported.append(key)
    return imported


def import_operator_secret_references(values: dict[str, str], source_values: dict[str, str]) -> tuple[list[str], list[SecretIssue]]:
    issues = validate_secret_references(source_values, require_external=True)
    issue_keys = {key for issue in issues for key in issue.keys}
    imported: list[str] = []
    for key in sorted(source_values):
        value = source_values[key]
        if key in issue_keys or not value:
            continue
        if is_secret_key(key) and is_secret_reference(value):
            values[key] = value
            imported.append(key)
    return imported, issues


def missing_production_reference_keys(values: dict[str, str]) -> list[str]:
    required = {key for key, value in values.items() if is_secret_key(key) and key not in PRODUCTION_REFERENCE_OPTIONAL_KEYS}
    return sorted(key for key in required if not values.get(key))


def write_env(path: Path, values: dict[str, str], *, production: bool = False) -> None:
    if production:
        lines = [
            "# Generated production-reference cell env. Do not commit this file.",
            "# Secret-bearing values must be SOPS/age/Vault/envref references; values are never printed.",
        ]
    else:
        lines = [
            "# Generated local-cell env. Do not commit this file.",
            "# Proof scripts print names only; this file contains local dev values.",
        ]
    for key in sorted(values):
        value = values[key]
        lines.append(f"{key}={value}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a secret-safe local cell env file.")
    parser.add_argument("--cell", default=DEFAULT_CELL)
    parser.add_argument("--registry-prefix", default=DEFAULT_REGISTRY_PREFIX)
    parser.add_argument("--api-port", type=int, default=18080)
    parser.add_argument("--production", action="store_true", help="Generate a production-reference cell env scaffold.")
    parser.add_argument("--public-api-base", default="https://api.expertaiservices.com")
    parser.add_argument("--admin-origin", default="https://admin.expertaiservices.com")
    parser.add_argument(
        "--source-env",
        type=Path,
        help="Optional operator env file whose provider/Marker secret values are copied into the generated cell env. Values are never printed.",
    )
    parser.add_argument(
        "--reference-source-env",
        type=Path,
        help="Optional operator env file whose production secret references are copied into the generated cell env. Raw secret values fail.",
    )
    args = parser.parse_args()
    if args.production and args.source_env:
        parser.error("--source-env copies local raw values; use --reference-source-env with --production")
    if args.production:
        values = build_production_reference_env(
            args.cell,
            args.registry_prefix,
            args.api_port,
            public_api_base=args.public_api_base,
            admin_origin=args.admin_origin,
        )
    else:
        values = build_env(args.cell, args.registry_prefix, args.api_port)
    imported: list[str] = []
    if args.source_env:
        imported = import_operator_values(values, read_source_env(args.source_env))
    reference_imported: list[str] = []
    if args.reference_source_env:
        reference_imported, reference_issues = import_operator_secret_references(values, read_source_env(args.reference_source_env))
        if reference_issues:
            print("Secret reference import failed:")
            for issue in reference_issues:
                print(f"FAIL {issue.code} {','.join(issue.keys)}")
            print("No values printed.")
            raise SystemExit(1)
    if args.production:
        missing_refs = missing_production_reference_keys(values)
        if missing_refs:
            print("Missing production secret references:")
            for key in missing_refs:
                print(f"- {key}")
            print("No values printed.")
            raise SystemExit(1)
    target = env_file(args.cell)
    write_env(target, values, production=args.production)
    print(f"Generated env file: {target}")
    print("Variable names written:")
    for key in sorted(values):
        print(f"- {key}")
    if args.source_env:
        print("Variable names imported from source env:")
        for key in imported:
            print(f"- {key}")
    if args.reference_source_env:
        print("Secret reference names imported from source env:")
        for key in reference_imported:
            print(f"- {key}")
    print("No values printed.")
    print(f"Release directory: {release_dir(args.cell)}")


if __name__ == "__main__":
    main()
