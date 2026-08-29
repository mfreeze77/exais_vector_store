from svs_common.schemas import ChunkRecord, RetrievalScope
import pytest

from svs_common.security import (
    ExpertInteractionSensitiveDataError,
    chunk_allowed_by_scope,
    sanitize_expert_interaction_data,
)

def test_security_level_blocks_high_chunk():
    chunk = ChunkRecord(id="c", document_id="d", ordinal=0, text="secret", security_level=4)
    scope = RetrievalScope(tenant_id="t", business_instance_id="b", max_security_level=3)
    assert not chunk_allowed_by_scope(chunk, scope)

def test_group_required():
    chunk = ChunkRecord(id="c", document_id="d", ordinal=0, text="team", security_level=2, allowed_groups=["eng"])
    scope = RetrievalScope(tenant_id="t", business_instance_id="b", max_security_level=2, groups=["sales"])
    assert not chunk_allowed_by_scope(chunk, scope)
    scope.groups = ["eng"]
    assert chunk_allowed_by_scope(chunk, scope)


def test_expert_interaction_guard_redacts_nested_pii_and_secret_assignments():
    guarded, metadata = sanitize_expert_interaction_data({
        "comment": "Reply to caller@example.test at 785-555-1212",
        "details": ["api_key=not-a-real-but-sensitive-value"],
    })

    assert guarded == {
        "comment": "Reply to [REDACTED_EMAIL] at [REDACTED_PHONE]",
        "details": ["api_key=[REDACTED_SECRET]"],
    }
    assert {item["type"] for item in metadata["redactions"]} == {
        "email",
        "phone",
        "secret_assignment",
    }


def test_expert_interaction_guard_rejects_secret_bearing_structured_keys():
    with pytest.raises(ExpertInteractionSensitiveDataError, match="sensitive field"):
        sanitize_expert_interaction_data({"authorization": "Bearer not-for-storage"})


@pytest.mark.parametrize(
    "sensitive_key",
    [
        "client_secret",
        "clientSecret",
        "oauth_client_secret",
        "aws_secret_access_key",
        "AWSSecretAccessKey",
        "secret_access_key",
        "access_token",
        "session-token",
        "apiKey",
        "privateKey",
        "caller@example.test",
        "785-555-1212",
        "123-45-6789",
    ],
)
def test_expert_interaction_guard_rejects_compound_secret_and_pii_json_keys(sensitive_key):
    with pytest.raises(ExpertInteractionSensitiveDataError, match="sensitive field"):
        sanitize_expert_interaction_data({"safe": {sensitive_key: "value"}})


def test_expert_interaction_guard_rejects_unsupported_nested_values():
    with pytest.raises(ExpertInteractionSensitiveDataError, match="unsupported value"):
        sanitize_expert_interaction_data({"value": object()})
