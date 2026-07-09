from __future__ import annotations

from types import SimpleNamespace

import pytest

from svs_common.providers import (
    GenericEndpointEmbeddingProvider,
    HashEmbeddingProvider,
    ProviderConfigurationError,
    provider_config_status,
    provider_for,
)
from svs_common.ingestion import embedding_profile_config, validate_embedding_provider_response


def settings(**overrides):
    values = {
        "openai_api_key": None,
        "voyage_api_key": None,
        "cohere_api_key": None,
        "tei_endpoint_url": None,
        "runpod_embedding_endpoint_url": None,
        "runpod_api_key": None,
        "infinity_endpoint_url": None,
        "self_hosted_model_endpoint_url": None,
        "self_hosted_model_api_key": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_openai_provider_missing_key_fails_instead_of_hashing():
    with pytest.raises(ProviderConfigurationError, match="OPENAI_API_KEY"):
        provider_for("openai", settings=settings(openai_api_key=""))


def test_unknown_provider_fails_instead_of_hashing():
    with pytest.raises(ProviderConfigurationError, match="unknown embedding provider"):
        provider_for("not-a-provider", settings=settings())


def test_hash_mock_provider_is_only_returned_when_explicitly_selected():
    provider = provider_for("hash_mock", settings=settings())

    assert isinstance(provider, HashEmbeddingProvider)


def test_provider_status_reports_required_env_names_without_values():
    status = provider_config_status("openai", settings=settings(openai_api_key=""))

    assert status.configured is False
    assert status.required_env == ("OPENAI_API_KEY",)
    assert "OPENAI_API_KEY" in (status.reason or "")
    assert "sk-" not in (status.reason or "")


def test_provider_status_marks_configured_openai_key():
    status = provider_config_status("openai", settings=settings(openai_api_key="sk-test-not-real"))

    assert status.configured is True
    assert status.required_env == ("OPENAI_API_KEY",)


def test_runpod_provider_status_reports_secret_reference_without_value():
    status = provider_config_status(
        "runpod",
        settings=settings(
            runpod_embedding_endpoint_url="https://api.runpod.ai/v2/endpoint/runsync",
            runpod_api_key="not-a-real-runtime-token",
        ),
    )

    assert status.configured is True
    assert status.required_env == ("RUNPOD_EMBEDDING_ENDPOINT_URL",)
    assert status.auth_secret_ref == "envref://RUNPOD_API_KEY"
    assert "not-a-real-runtime-token" not in repr(status)


def test_runpod_serverless_alias_and_self_hosted_provider_status():
    runpod = provider_config_status(
        "runpod_serverless",
        settings=settings(runpod_embedding_endpoint_url="https://api.runpod.ai/v2/endpoint/runsync"),
    )
    self_hosted = provider_config_status(
        "self_hosted",
        settings=settings(
            self_hosted_model_endpoint_url="https://models.internal",
            self_hosted_model_api_key="runtime-value-not-returned",
        ),
    )

    assert runpod.configured is True
    assert runpod.required_env == ("RUNPOD_EMBEDDING_ENDPOINT_URL",)
    assert self_hosted.configured is True
    assert self_hosted.required_env == ("SELF_HOSTED_MODEL_ENDPOINT_URL",)
    assert self_hosted.auth_secret_ref == "envref://SELF_HOSTED_MODEL_API_KEY"
    assert "runtime-value-not-returned" not in repr(self_hosted)


def test_huggingface_tei_alias_uses_tei_endpoint():
    runtime_settings = settings(tei_endpoint_url="http://tei.internal:8080")
    status = provider_config_status("huggingface_tei", settings=runtime_settings)
    provider = provider_for("huggingface_tei", settings=runtime_settings)

    assert status.configured is True
    assert status.required_env == ("TEI_ENDPOINT_URL",)
    assert isinstance(provider, GenericEndpointEmbeddingProvider)
    assert provider.provider == "huggingface_tei"


def test_ingestion_rejects_unknown_embedding_profile():
    with pytest.raises(ProviderConfigurationError, match="Unknown embedding profile"):
        embedding_profile_config("missing_profile", {})


def test_ingestion_rejects_real_profile_backed_by_hash_response():
    with pytest.raises(ProviderConfigurationError, match="returned hash_mock vectors"):
        validate_embedding_provider_response("openai_text_embedding_3_small_1536", "openai", "hash_mock")


def test_ingestion_allows_explicit_hash_profile_response():
    validate_embedding_provider_response("hash_mock_1536", "hash_mock", "hash_mock")
