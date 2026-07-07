from __future__ import annotations

from types import SimpleNamespace

import pytest

from svs_common.providers import (
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


def test_ingestion_rejects_unknown_embedding_profile():
    with pytest.raises(ProviderConfigurationError, match="Unknown embedding profile"):
        embedding_profile_config("missing_profile", {})


def test_ingestion_rejects_real_profile_backed_by_hash_response():
    with pytest.raises(ProviderConfigurationError, match="returned hash_mock vectors"):
        validate_embedding_provider_response("openai_text_embedding_3_small_1536", "openai", "hash_mock")


def test_ingestion_allows_explicit_hash_profile_response():
    validate_embedding_provider_response("hash_mock_1536", "hash_mock", "hash_mock")
