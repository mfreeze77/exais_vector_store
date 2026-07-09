from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def assert_tokens(path: str, tokens: list[str]) -> None:
    body = read(path)
    missing = [token for token in tokens if token not in body]
    assert not missing, f"{path} missing tokens: {missing}"


def test_rm015_external_restore_runbook_documents_external_proof_boundary():
    assert_tokens(
        "runbooks/external-restore-drill.md",
        [
            "RM-015",
            "real backup target",
            "external staging or customer cell",
            "scripts/release/local-restore-drill.py",
            "Do not close RM-015 from local evidence alone",
            "python scripts/release/backup_common.py validate <restore-work-dir>/<bundle>/manifest.json --require-external --print-artifacts",
            "postgres_metadata",
            "qdrant_vectors",
            "opensearch_sparse",
            "object_store",
            "config_metadata",
            "audit_export",
            "checksum_metadata",
            "python scripts/release/cell-access-proof.py --cell <cell-id>",
            "python scripts/release/search-bench.py --cell <cell-id>",
        ],
    )


def test_rm016_corpus_scale_runbook_and_config_cover_required_metrics():
    required = [
        "RM-016",
        "selected corpus",
        "documented production-scale surrogate",
        "ingestion throughput",
        "p95 search latency",
        "p95 context-pack latency",
        "queue freshness",
        "index growth",
        "provider latency",
        "failure modes",
        "python scripts/release/seed-scale.py --cell <cell-id>",
        "python scripts/release/search-bench.py --cell <cell-id>",
        "python scripts/release/observability-smoke.py --cell <cell-id>",
        "/api/v1/retrieval/context-pack",
        "A search-only run is incomplete for RM-016",
    ]
    assert_tokens("runbooks/corpus-scale-load-tests.md", required)

    assert_tokens(
        "load-tests/corpus-scale.yml",
        [
            "rm_id: RM-016",
            "proof_status: packaged_operator_dependent",
            "ingestion_throughput_docs_per_min",
            "p95_search_latency_ms",
            "p95_context_pack_latency_ms",
            "queue_freshness_oldest_age_seconds",
            "index_growth_qdrant_points",
            "index_growth_opensearch_docs",
            "provider_latency_p95_ms",
            "failure_modes",
            "scripts/release/seed-scale.py",
            "scripts/release/search-bench.py",
            "/api/v1/retrieval/context-pack",
        ],
    )


def test_rm017_dns_tls_secrets_runbook_requires_live_domain_evidence():
    assert_tokens(
        "runbooks/dns-tls-secrets.md",
        [
            "RM-017",
            "chosen production domain and cell",
            "cannot claim DNS or TLS without live domain evidence",
            "infra/caddy/Caddyfile",
            "infra/terraform/hetzner-cloud/main.tf",
            "infra/ansible/playbook.yml",
            "python scripts/release/prod-env-preflight.py --env-file <cell-env>",
            "python scripts/release/cell-access-proof.py --cell <cell-id>",
            "sops://...#KEY",
            "age://...#KEY",
            "vault://...#KEY",
            "envref://KEY",
            "SVS_ALLOWED_CORS_ORIGINS",
            "OPENSEARCH_VERIFY_CERTS",
            "nslookup <api-fqdn>",
            "openssl s_client -connect <api-fqdn>:443 -servername <api-fqdn> -showcerts",
            "Until live DNS resolution, HTTPS/TLS health checks, and external",
        ],
    )
