import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "release" / "prod-env-preflight.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("prod_env_preflight", SCRIPT)
prod_env_preflight = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules["prod_env_preflight"] = prod_env_preflight
spec.loader.exec_module(prod_env_preflight)


def valid_env() -> dict[str, str]:
    return {
        "SVS_ENV": "prod",
        "SVS_PRODUCT_VERSION": "0.9.8-production-candidate",
        "SVS_VERSION": "0.9.8-production-candidate",
        "SVS_REGISTRY_PREFIX": "registry.internal/exais",
        "SVS_RELEASE_CHANNEL": "stable",
        "SVS_CELL_ENV_FILE": "/opt/exais/vector-store/.env.cell",
        "SVS_DEV_MODE": "false",
        "POSTGRES_USER": "svs_owner",
        "POSTGRES_PASSWORD": "sops://configs/cell-secrets.example.sops.yaml#POSTGRES_PASSWORD",
        "POSTGRES_DB": "svs",
        "POSTGRES_APP_USER": "svs_app",
        "POSTGRES_APP_PASSWORD": "sops://configs/cell-secrets.example.sops.yaml#POSTGRES_APP_PASSWORD",
        "DATABASE_URL": "sops://configs/cell-secrets.example.sops.yaml#DATABASE_URL",
        "DATABASE_URL_SYNC": "sops://configs/cell-secrets.example.sops.yaml#DATABASE_URL_SYNC",
        "DATABASE_URL_MIGRATIONS": "sops://configs/cell-secrets.example.sops.yaml#DATABASE_URL_MIGRATIONS",
        "REDIS_URL": "redis://redis:6379/0",
        "QDRANT_URL": "http://qdrant:6333",
        "QDRANT_COLLECTION_PREFIX": "svs_",
        "SVS_DENSE_BACKEND": "qdrant",
        "SVS_SPARSE_BACKEND": "postgres_fts",
        "S3_ENDPOINT_URL": "https://object-storage.internal.invalid",
        "S3_ACCESS_KEY_ID": "sops://configs/cell-secrets.example.sops.yaml#S3_ACCESS_KEY_ID",
        "S3_SECRET_ACCESS_KEY": "sops://configs/cell-secrets.example.sops.yaml#S3_SECRET_ACCESS_KEY",
        "S3_BUCKET": "exai-vector-store-prod",
        "S3_REGION": "us-east-1",
        "DEFAULT_EMBEDDING_PROVIDER": "openai",
        "OPENAI_API_KEY": "envref://OPENAI_API_KEY",
        "MODEL_GATEWAY_URL": "http://model-gateway:8081",
        "SVS_API_KEY_PEPPER": "age://configs/cell-secrets.example.sops.yaml#SVS_API_KEY_PEPPER",
        "SVS_ALLOWED_CORS_ORIGINS": "https://admin.internal.invalid,https://api.internal.invalid",
        "SVS_INDEX_STRICT": "true",
        "SVS_OBJECT_STORE_STRICT": "true",
        "OPENSEARCH_URL": "https://opensearch.internal.invalid:9200",
        "OPENSEARCH_VERIFY_CERTS": "true",
        "SVS_API_PORT": "18080",
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


def issue_codes(issues):
    return {issue.code for issue in issues}


def test_valid_production_env_passes_preflight():
    issues = prod_env_preflight.validate_env(valid_env(), "0.9.8-production-candidate")

    assert issues == []


def test_preflight_rejects_plaintext_secret_values_and_embedded_url_passwords():
    values = valid_env()
    values["POSTGRES_PASSWORD"] = "owner-not-real-64-characters-aaaaaaaaaaaaaaaaaaaaaaaa"
    values["DATABASE_URL"] = "postgresql+psycopg://svs_app:app-pass@postgres:5432/svs"

    codes = issue_codes(prod_env_preflight.validate_env(values, "0.9.8-production-candidate"))

    assert "PLAINTEXT_SECRET" in codes
    assert "EMBEDDED_SECRET" in codes


def test_preflight_rejects_dev_mode_placeholders_versions_and_ports():
    values = valid_env()
    values["SVS_DEV_MODE"] = "true"
    values["SVS_VERSION"] = "latest"
    values["SVS_REGISTRY_PREFIX"] = "localhost:5000/expertaiservices"
    values["POSTGRES_PASSWORD"] = "replace-with-owner-secret"
    values["SVS_ADMIN_UI_PORT"] = values["SVS_API_PORT"]
    del values["DATABASE_URL"]

    codes = issue_codes(prod_env_preflight.validate_env(values, "0.9.8-production-candidate"))

    assert {"DEV_MODE_ENABLED", "BAD_VERSION", "LATEST_TAG", "LOCAL_REGISTRY_PREFIX", "PLACEHOLDER", "PORT_COLLISION", "MISSING"} <= codes


def test_preflight_report_prints_names_not_secret_values():
    values = valid_env()
    values["POSTGRES_PASSWORD"] = "replace-with-owner-secret"
    values["OPENAI_API_KEY"] = "sk-should-not-appear"
    issues = prod_env_preflight.validate_env(values, "0.9.8-production-candidate")

    report = prod_env_preflight.render_report(Path("prod.env"), values, issues, "0.9.8-production-candidate")

    assert "POSTGRES_PASSWORD" in report
    assert "OPENAI_API_KEY" in report
    assert "replace-with-owner-secret" not in report
    assert "sk-should-not-appear" not in report


def test_reference_paths_with_example_do_not_trigger_placeholder_detection():
    value = "sops://configs/cell-secrets.example.sops.yaml#POSTGRES_PASSWORD"

    assert prod_env_preflight.has_placeholder("POSTGRES_PASSWORD", value) is False


def test_database_url_reference_locator_is_not_parsed_as_runtime_dsn():
    values = valid_env()
    values["DATABASE_URL"] = "vault://kv/svs_owner/customer-001#DATABASE_URL"

    issues = prod_env_preflight.validate_env(values, "0.9.8-production-candidate")

    assert "RUNTIME_DSN_USES_OWNER" not in issue_codes(issues)
