from svs_common.secrets import (
    is_secret_reference,
    parse_secret_reference,
    validate_secret_references,
)


def issue_codes(issues):
    return {issue.code for issue in issues}


def test_accepts_supported_secret_reference_schemes():
    values = {
        "POSTGRES_PASSWORD": "sops://configs/cell-secrets.example.sops.yaml#POSTGRES_PASSWORD",
        "DATABASE_URL": "age://configs/cell-secrets.example.sops.yaml#DATABASE_URL",
        "OPENAI_API_KEY": "vault://kv/exais/customer-001#OPENAI_API_KEY",
        "SVS_API_KEY_PEPPER": "envref://SVS_API_KEY_PEPPER",
    }

    assert validate_secret_references(values) == []
    assert is_secret_reference(values["POSTGRES_PASSWORD"])
    parsed = parse_secret_reference(values["OPENAI_API_KEY"])
    assert parsed is not None
    assert parsed.scheme == "vault"
    assert parsed.locator == "kv/exais/customer-001"
    assert parsed.name == "OPENAI_API_KEY"


def test_rejects_plaintext_secret_values_without_disclosure():
    raw_secret = "raw-secret-should-not-appear"

    issues = validate_secret_references({"POSTGRES_PASSWORD": raw_secret})

    assert issue_codes(issues) == {"PLAINTEXT_SECRET"}
    assert "POSTGRES_PASSWORD" in repr(issues)
    assert raw_secret not in repr(issues)


def test_rejects_embedded_url_passwords_without_disclosure():
    dsn = "postgresql://svs_app:app-pass@postgres:5432/svs"

    issues = validate_secret_references({"DATABASE_URL": dsn})

    assert issue_codes(issues) == {"EMBEDDED_SECRET"}
    assert "DATABASE_URL" in repr(issues)
    assert "app-pass" not in repr(issues)


def test_rejects_malformed_reference_names_only():
    malformed = "sops://configs/cell-secrets.example.sops.yaml"

    issues = validate_secret_references({"POSTGRES_PASSWORD": malformed})

    assert issue_codes(issues) == {"INVALID_SECRET_REFERENCE"}
    assert "POSTGRES_PASSWORD" in repr(issues)
    assert malformed not in repr(issues)


def test_blank_optional_secret_value_is_not_a_reference_error():
    issues = validate_secret_references({"QDRANT_API_KEY": ""})

    assert issues == []
