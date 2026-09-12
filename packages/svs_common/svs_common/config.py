from __future__ import annotations
from functools import lru_cache
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    svs_env: str = 'local'
    svs_product_version: str = '0.9.8-production-candidate'
    # Dev-mode header principals are intentionally off by default. Local .env files
    # can turn this on, but production-like environments fail startup if they do.
    svs_dev_mode: bool = False
    svs_dev_tenant_id: str = 'ten_dev'
    svs_dev_business_instance_id: str = 'biz_dev'
    svs_dev_user_id: str = 'usr_dev'
    svs_dev_groups: str = 'grp_admin,grp_eng,admins,engineering'
    svs_dev_roles: str = 'owner,admin'
    svs_dev_max_security_level: int = 5
    svs_api_key_pepper: str = 'change-me-in-prod'

    # Runtime app code must connect with a non-owner NOSUPERUSER/NOBYPASSRLS role.
    # DATABASE_URL_SYNC is reserved for migrations/bootstrap with the owner role.
    database_url: str = 'postgresql+psycopg://svs_app:svs_app_dev_password@localhost:5432/svs'
    database_url_sync: str = 'postgresql://svs_owner:svs_owner_dev_password@localhost:5432/svs'
    redis_url: str = 'redis://localhost:6379/0'

    qdrant_url: str = 'http://localhost:6333'
    qdrant_api_key: str | None = None
    qdrant_collection_prefix: str = 'svs_'
    opensearch_url: str = 'http://localhost:9200'
    opensearch_user: str = 'admin'
    opensearch_password: str = 'admin'
    opensearch_index_prefix: str = 'svs_'
    opensearch_verify_certs: bool = True

    # Production consistency defaults. Strict dense indexing is intentionally on;
    # sparse search defaults to Postgres FTS so mini/micro cells do not need a JVM.
    svs_index_strict: bool = True
    svs_index_version: str = ''
    svs_dense_backend: str = 'qdrant'
    svs_sparse_backend: str = 'postgres_fts'  # postgres_fts | opensearch
    svs_ingest_inline_max_bytes: int = 262144
    svs_enable_postgres_sparse_fallback: bool = True
    svs_reindex_batch_size: int = 250
    svs_expiration_batch_size: int = 100

    # Operational controls.
    svs_default_rate_limit_per_minute: int = 120
    svs_admin_rate_limit_per_minute: int = 30
    svs_vector_store_file_add_rate_limit_per_minute: int = 300
    svs_idempotency_ttl_hours: int = 24
    svs_request_body_limit_bytes: int = 50 * 1024 * 1024
    svs_allowed_cors_origins: str = 'http://localhost:3000,http://localhost:8080'

    # Object storage. In local/micro cells this falls back to the filesystem; in
    # production object-store strictness can be enabled so artifact writes fail closed.
    s3_endpoint_url: str | None = 'http://localhost:9000'
    s3_access_key_id: str = 'svs_minio'
    s3_secret_access_key: str = 'svs_minio_password'
    s3_bucket: str = 'svs-local'
    s3_region: str = 'us-east-1'
    svs_local_object_store_path: str = './.svs-object-store'
    svs_object_store_strict: bool = False

    default_embedding_provider: str = 'hash_mock'
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    openai_embedding_model: str = 'text-embedding-3-small'
    openai_embedding_dimensions: int = 1536
    model_gateway_url: str = 'http://localhost:8081'
    expert_chat_timeout_sec: float = 120.0
    tei_endpoint_url: str | None = None
    infinity_endpoint_url: str | None = None
    self_hosted_model_endpoint_url: str | None = None
    self_hosted_model_api_key: str | None = None
    runpod_embedding_endpoint_url: str | None = None
    runpod_api_key: str | None = None
    runpod_endpoint_id: str | None = None
    marker_runpod_api_key: str | None = None
    marker_runpod_endpoint_id: str | None = None
    marker_mode: str = 'remote'
    marker_timeout_sec: int = 1800
    marker_poll_interval_sec: int = 3
    marker_max_attempts: int = 2
    marker_retry_backoff_sec: int = 5
    embedding_max_attempts: int = 5
    embedding_retry_backoff_sec: float = 1.0
    # wall clock from the first attempt, covering request time AND sleep (F2)
    embedding_retry_deadline_sec: float = 300.0
    # a ReadTimeout may already have been processed and billed upstream (F6)
    embedding_max_timeout_retries: int = 2
    voyage_api_key: str | None = None
    cohere_api_key: str | None = None
    jina_api_key: str | None = None

    @property
    def is_local_env(self) -> bool:
        return (self.svs_env or '').strip().lower() in {'local', 'dev', 'development', 'test', 'testing', 'ci'}

    @property
    def cors_origins(self) -> list[str]:
        return [x.strip() for x in self.svs_allowed_cors_origins.split(',') if x.strip()]

    @property
    def dev_groups(self) -> list[str]:
        return [x.strip() for x in self.svs_dev_groups.split(',') if x.strip()]

    @property
    def dev_roles(self) -> list[str]:
        return [x.strip() for x in self.svs_dev_roles.split(',') if x.strip()]

    @property
    def local_object_store_root(self) -> Path:
        return Path(self.svs_local_object_store_path)

    def validate_for_startup(self) -> None:
        """Fail closed for production-like runtime settings."""
        if self.is_local_env:
            return
        errors: list[str] = []
        weak_peppers = {'', 'change-me-in-prod', 'changeme', 'dev', 'local'}
        if self.svs_dev_mode:
            errors.append('SVS_DEV_MODE must be false when SVS_ENV is not local/dev/test/ci')
        if self.svs_api_key_pepper.strip().lower() in weak_peppers:
            errors.append('SVS_API_KEY_PEPPER must be set to a strong secret when SVS_ENV is not local/dev/test/ci')
        if any(origin == '*' for origin in self.cors_origins):
            errors.append('SVS_ALLOWED_CORS_ORIGINS must not include * outside local/dev/test/ci')
        if self.opensearch_url.startswith('https://') and not self.opensearch_verify_certs:
            errors.append('OPENSEARCH_VERIFY_CERTS must not be false for HTTPS OpenSearch outside local/dev/test/ci')
        if errors:
            raise RuntimeError('Unsafe SVS startup configuration: ' + '; '.join(errors))

    # Backward-compatible names used by older service entrypoints/tests.
    def validate_runtime_guards(self) -> None:
        self.validate_for_startup()

    def validate_runtime_safety(self) -> None:
        self.validate_for_startup()


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_for_startup()
    return settings


def validate_production_guardrails(settings: Settings | None = None) -> None:
    """Compatibility helper for services/tests that validate runtime Settings."""
    (settings or get_settings()).validate_for_startup()
