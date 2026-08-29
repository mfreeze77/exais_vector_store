from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from svs_common import expert_llm
from svs_common.expert_llm import ExpertChatGatewayError, complete_expert_chat
from svs_common.model_registry import (
    ModelRegistryConfigurationError,
    model_registry,
    resolve_expert_chat_profiles,
)
from svs_common.providers import (
    AnthropicChatProvider,
    ChatProviderResult,
    FixtureChatProvider,
    OpenAICompatibleChatProvider,
    ProviderConfigStatus,
    ProviderConfigurationError,
    chat_provider_for,
)
from svs_common.schemas import (
    ExpertChatCompletionRequest,
    ExpertChatMessage,
    ExpertModelPolicy,
)
import svs_common.providers as providers_mod
from svs_model_gateway import main as gateway_main


def _request(
    policy_id: str = "fixture_expert_chat_v1",
    *,
    security_level: int = 1,
    allow_fallback: bool = True,
) -> ExpertChatCompletionRequest:
    return ExpertChatCompletionRequest(
        messages=[
            ExpertChatMessage(role="system", content="Answer only from supplied context."),
            ExpertChatMessage(role="user", content="What is home rule?"),
        ],
        model_policy=ExpertModelPolicy(
            policy_id=policy_id,
            allow_fallback=allow_fallback,
        ),
        security_level=security_level,
        max_output_tokens=300,
        temperature=0.0,
    )


def _chat_settings(**overrides):
    values = {
        "svs_env": "test",
        "is_local_env": True,
        "openai_api_key": None,
        "anthropic_api_key": None,
        "self_hosted_model_endpoint_url": None,
        "self_hosted_model_api_key": None,
        "expert_chat_timeout_sec": 12.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_complete_expert_chat_has_the_shared_typed_contract():
    signature = inspect.signature(complete_expert_chat)

    assert list(signature.parameters) == ["req"]
    assert signature.return_annotation == "ExpertChatCompletionResponse"


def test_registry_resolves_default_policy_without_mixing_embedding_profiles():
    registry = model_registry()
    candidates = resolve_expert_chat_profiles(ExpertModelPolicy(policy_id="default_expert_chat_v1"))
    no_fallback = resolve_expert_chat_profiles(
        ExpertModelPolicy(policy_id="default_expert_chat_v1", allow_fallback=False)
    )

    assert [profile_id for profile_id, _ in candidates] == [
        "private_qwen3_32b_expert",
        "openai_gpt_5_5_expert",
        "anthropic_claude_sonnet_5_expert",
    ]
    assert [profile_id for profile_id, _ in no_fallback] == ["private_qwen3_32b_expert"]
    assert registry["models"]["hash_mock_1536"]["kind"] == "embedding"
    assert "hash_mock_1536" not in registry["chat_models"]


def test_registry_rejects_chat_profile_without_a_valid_security_ceiling():
    registry = {
        "chat_policies": {
            "invalid_security_policy": {
                "preferred_model_profile_id": "invalid_security_profile",
                "fallback_model_profile_ids": [],
                "allow_fallback": False,
            }
        },
        "chat_models": {
            "invalid_security_profile": {
                "kind": "chat",
                "provider": "fixture",
                "model": "fixture",
                "max_security_level": 6,
            }
        },
    }

    with pytest.raises(ModelRegistryConfigurationError, match="max_security_level"):
        resolve_expert_chat_profiles(
            ExpertModelPolicy(policy_id="invalid_security_policy"),
            registry=registry,
        )


def test_fixture_gateway_completion_is_deterministic_and_truthfully_not_fallback():
    req = _request()

    first = asyncio.run(gateway_main.expert_chat(req))
    second = asyncio.run(gateway_main.expert_chat(req))

    assert first.content == second.content
    assert first.usage == second.usage
    assert first.model_profile_id == second.model_profile_id
    assert first.content.startswith("[fixture:")
    assert first.content.endswith("What is home rule?")
    assert first.provider == "fixture"
    assert first.model == "deterministic-expert-fixture-v1"
    assert first.model_profile_id == "fixture_expert_chat_v1"
    assert first.usage.input_tokens > 0
    assert first.usage.output_tokens > 0
    assert first.usage.total_tokens == first.usage.input_tokens + first.usage.output_tokens
    assert first.fallback.occurred is False
    assert first.fallback.from_model_profile_id is None
    assert first.fallback.reason is None
    assert [attempt.status for attempt in first.fallback.attempts] == ["succeeded"]


def test_fixture_profile_is_denied_outside_local_test_environments(monkeypatch):
    monkeypatch.setattr(gateway_main, "settings", _chat_settings(svs_env="production", is_local_env=False))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(gateway_main.expert_chat(_request()))

    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "expert_chat_provider_unavailable"
    assert exc.value.detail["attempts"][0]["error_code"] == "local_only_provider_denied"


def test_security_policy_denies_external_fallback_for_regulated_content(monkeypatch):
    monkeypatch.setattr(
        gateway_main,
        "settings",
        _chat_settings(openai_api_key="test-value-not-returned"),
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(gateway_main.expert_chat(_request("default_expert_chat_v1", security_level=4)))

    attempts = exc.value.detail["attempts"]
    assert exc.value.status_code == 503
    assert [attempt["model_profile_id"] for attempt in attempts] == [
        "private_qwen3_32b_expert",
        "openai_gpt_5_5_expert",
        "anthropic_claude_sonnet_5_expert",
    ]
    assert attempts[0]["error_code"] == "provider_unconfigured"
    assert attempts[1]["error_code"] == "security_policy_denied"
    assert "test-value-not-returned" not in str(exc.value.detail)


def test_gateway_records_runtime_fallback_only_after_preferred_failure(monkeypatch):
    class _FailingProvider:
        provider = "primary"

        async def complete(self, messages, model, *, max_output_tokens, temperature):
            raise httpx.ConnectError("provider unavailable")

    class _FallbackProvider:
        provider = "fallback"

        async def complete(self, messages, model, *, max_output_tokens, temperature):
            return ChatProviderResult(
                content="Fallback answer",
                model="fallback-model-revision",
                usage={"input_tokens": 8, "output_tokens": 2, "total_tokens": 10},
                finish_reason="stop",
            )

    candidates = [
        ("primary_profile", {"kind": "chat", "provider": "primary", "model": "primary-model", "max_security_level": 5}),
        ("fallback_profile", {"kind": "chat", "provider": "fallback", "model": "fallback-model", "max_security_level": 5}),
    ]
    monkeypatch.setattr(gateway_main, "resolve_expert_chat_profiles", lambda policy: candidates)
    monkeypatch.setattr(
        gateway_main,
        "chat_provider_config_status",
        lambda provider, settings: ProviderConfigStatus(provider=provider, configured=True),
    )
    monkeypatch.setattr(
        gateway_main,
        "chat_provider_for",
        lambda provider, settings: _FailingProvider() if provider == "primary" else _FallbackProvider(),
    )

    response = asyncio.run(gateway_main.expert_chat(_request("test_policy")))

    assert response.provider == "fallback"
    assert response.model == "fallback-model-revision"
    assert response.model_profile_id == "fallback_profile"
    assert response.requested_model_profile_id == "primary_profile"
    assert response.usage.total_tokens == 10
    assert response.fallback.occurred is True
    assert response.fallback.from_model_profile_id == "primary_profile"
    assert response.fallback.reason == "preferred_provider_failed"
    assert [attempt.status for attempt in response.fallback.attempts] == ["failed", "succeeded"]
    assert response.fallback.attempts[0].error_code == "ConnectError"


def test_gateway_records_unconfigured_preferred_as_fallback_reason(monkeypatch):
    class _OpenAISuccess:
        provider = "openai"

        async def complete(self, messages, model, *, max_output_tokens, temperature):
            return ChatProviderResult(
                content="Policy-selected answer",
                model=model,
                usage={"input_tokens": 4, "output_tokens": 3, "total_tokens": 7},
            )

    monkeypatch.setattr(
        gateway_main,
        "settings",
        _chat_settings(openai_api_key="test-value-not-returned"),
    )
    monkeypatch.setattr(gateway_main, "chat_provider_for", lambda provider, settings: _OpenAISuccess())

    response = asyncio.run(gateway_main.expert_chat(_request("default_expert_chat_v1")))

    assert response.provider == "openai"
    assert response.requested_model_profile_id == "private_qwen3_32b_expert"
    assert response.model_profile_id == "openai_gpt_5_5_expert"
    assert response.fallback.occurred is True
    assert response.fallback.reason == "preferred_provider_unavailable"
    assert [attempt.status for attempt in response.fallback.attempts] == ["unavailable", "succeeded"]


def test_complete_expert_chat_posts_only_typed_policy_to_internal_gateway(monkeypatch):
    expected = asyncio.run(gateway_main.expert_chat(_request())).model_dump(mode="json")
    captured = {}

    class _Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return expected

    class _Client:
        def __init__(self, *, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, json):
            captured["url"] = url
            captured["json"] = json
            return _Response()

    monkeypatch.setattr(expert_llm, "get_settings", lambda: SimpleNamespace(
        model_gateway_url="http://model-gateway:8081/",
        expert_chat_timeout_sec=17.0,
    ))
    monkeypatch.setattr(expert_llm.httpx, "AsyncClient", _Client)

    response = asyncio.run(complete_expert_chat(_request()))

    assert response.model_dump(mode="json") == expected
    assert captured["url"] == "http://model-gateway:8081/internal/models/expert-chat"
    assert captured["timeout"] == 17.0
    assert captured["json"]["model_policy"] == {
        "policy_id": "fixture_expert_chat_v1",
        "gateway": "model_gateway",
        "preferred_model_profile_id": None,
        "fallback_model_profile_ids": [],
        "allow_fallback": True,
    }
    assert "provider" not in captured["json"]
    assert "model" not in captured["json"]


def test_complete_expert_chat_rejects_malformed_gateway_response(monkeypatch):
    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"provider": "fixture"}

    class _Client:
        def __init__(self, *, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, json):
            return _Response()

    monkeypatch.setattr(expert_llm, "get_settings", lambda: SimpleNamespace(
        model_gateway_url="http://model-gateway:8081",
        expert_chat_timeout_sec=17.0,
    ))
    monkeypatch.setattr(expert_llm.httpx, "AsyncClient", _Client)

    with pytest.raises(ExpertChatGatewayError, match="invalid_model_gateway_response"):
        asyncio.run(complete_expert_chat(_request()))


def test_complete_expert_chat_normalizes_gateway_json_decode_failure(monkeypatch):
    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            raise ValueError("malformed body must not escape")

    class _Client:
        def __init__(self, *, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, json):
            return _Response()

    monkeypatch.setattr(expert_llm, "get_settings", lambda: SimpleNamespace(
        model_gateway_url="http://model-gateway:8081",
        expert_chat_timeout_sec=17.0,
    ))
    monkeypatch.setattr(expert_llm.httpx, "AsyncClient", _Client)

    with pytest.raises(ExpertChatGatewayError) as exc:
        asyncio.run(complete_expert_chat(_request()))

    assert exc.value.code == "invalid_model_gateway_response"
    assert "malformed body" not in str(exc.value)


def test_chat_provider_factory_supports_fixture_openai_anthropic_and_private_without_affecting_embedding_factory():
    settings = _chat_settings(
        openai_api_key="test-openai-value",
        anthropic_api_key="test-anthropic-value",
        self_hosted_model_endpoint_url="http://private-models.internal/v1",
        self_hosted_model_api_key="test-private-value",
    )

    fixture = chat_provider_for("fixture", settings)
    openai = chat_provider_for("openai", settings)
    anthropic = chat_provider_for("anthropic", settings)
    private = chat_provider_for("openai_compatible_private", settings)

    assert isinstance(fixture, FixtureChatProvider)
    assert isinstance(openai, OpenAICompatibleChatProvider)
    assert openai.provider == "openai"
    assert openai.endpoint_url == "https://api.openai.com/v1"
    assert isinstance(anthropic, AnthropicChatProvider)
    assert isinstance(private, OpenAICompatibleChatProvider)
    assert private.provider == "openai_compatible_private"
    assert private.endpoint_url == "http://private-models.internal/v1"


def test_openai_compatible_chat_adapter_normalizes_content_usage_and_request(monkeypatch):
    captured = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "model": "served-model-revision",
                "choices": [{"message": {"content": "Grounded answer"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
            }

    class _Client:
        def __init__(self, *, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, json):
            captured.update({"url": url, "headers": headers, "json": json})
            return _Response()

    monkeypatch.setattr(providers_mod.httpx, "AsyncClient", _Client)
    provider = OpenAICompatibleChatProvider(
        "openai_compatible_private",
        "http://private-models.internal/v1",
        "secret-not-returned",
        timeout_seconds=9.0,
    )

    result = asyncio.run(provider.complete(
        _request().messages,
        "configured-model",
        max_output_tokens=500,
        temperature=0.25,
    ))

    assert captured["url"] == "http://private-models.internal/v1/chat/completions"
    assert captured["headers"] == {"Authorization": "Bearer secret-not-returned"}
    assert captured["json"] == {
        "model": "configured-model",
        "messages": [message.model_dump(mode="json") for message in _request().messages],
        "max_tokens": 500,
        "temperature": 0.25,
    }
    assert result.content == "Grounded answer"
    assert result.model == "served-model-revision"
    assert result.usage == {"input_tokens": 11, "output_tokens": 3, "total_tokens": 14}
    assert result.finish_reason == "stop"
    assert "secret-not-returned" not in repr(result)


def test_openai_gpt_5_chat_adapter_uses_current_token_parameter_and_omits_temperature(monkeypatch):
    captured = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "model": "gpt-5.5-2026-04-23",
                "choices": [{"message": {"content": "Grounded answer"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 11, "completion_tokens": 3, "total_tokens": 14},
            }

    class _Client:
        def __init__(self, *, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, json):
            captured["json"] = json
            return _Response()

    monkeypatch.setattr(providers_mod.httpx, "AsyncClient", _Client)
    provider = OpenAICompatibleChatProvider("openai", "https://api.openai.com/v1", "secret")

    asyncio.run(provider.complete(
        _request().messages,
        "gpt-5.5-2026-04-23",
        max_output_tokens=500,
        temperature=0.0,
    ))

    assert captured["json"]["max_completion_tokens"] == 500
    assert "max_tokens" not in captured["json"]
    assert "temperature" not in captured["json"]


def test_anthropic_chat_adapter_normalizes_native_messages_response(monkeypatch):
    captured = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "model": "claude-sonnet-5",
                "content": [{"type": "text", "text": "Grounded answer"}],
                "usage": {"input_tokens": 12, "output_tokens": 3},
                "stop_reason": "end_turn",
            }

    class _Client:
        def __init__(self, *, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, json):
            captured.update({"url": url, "headers": headers, "json": json})
            return _Response()

    monkeypatch.setattr(providers_mod.httpx, "AsyncClient", _Client)
    provider = AnthropicChatProvider("secret-not-returned", timeout_seconds=9.0)

    result = asyncio.run(provider.complete(
        _request().messages,
        "claude-sonnet-5",
        max_output_tokens=500,
        temperature=0.0,
    ))

    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "secret-not-returned"
    assert captured["json"] == {
        "model": "claude-sonnet-5",
        "max_tokens": 500,
        "messages": [{"role": "user", "content": "What is home rule?"}],
        "system": "Answer only from supplied context.",
    }
    assert result.content == "Grounded answer"
    assert result.model == "claude-sonnet-5"
    assert result.usage == {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15}
    assert result.finish_reason == "end_turn"
    assert "secret-not-returned" not in repr(result)


@pytest.mark.parametrize(
    ("response_body", "json_error"),
    [
        (None, ValueError("malformed provider JSON")),
        ({"choices": []}, None),
        ({"choices": [{"message": {"content": None}}]}, None),
        (
            {
                "choices": [{"message": {"content": "answer"}}],
                "usage": {"prompt_tokens": "not-a-number"},
            },
            None,
        ),
    ],
)
def test_openai_compatible_chat_adapter_normalizes_malformed_responses(
    monkeypatch,
    response_body,
    json_error,
):
    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            if json_error is not None:
                raise json_error
            return response_body

    class _Client:
        def __init__(self, *, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, json):
            return _Response()

    monkeypatch.setattr(providers_mod.httpx, "AsyncClient", _Client)
    provider = OpenAICompatibleChatProvider("openai", "https://provider.invalid/v1", "secret")

    with pytest.raises(ProviderConfigurationError) as exc:
        asyncio.run(provider.complete(
            _request().messages,
            "configured-model",
            max_output_tokens=100,
            temperature=0.0,
        ))

    assert "malformed provider JSON" not in str(exc.value)
    assert "not-a-number" not in str(exc.value)


def test_gateway_falls_back_after_malformed_provider_json(monkeypatch):
    class _MalformedResponse:
        def raise_for_status(self):
            return None

        def json(self):
            raise ValueError("provider response body must remain private")

    class _Client:
        def __init__(self, *, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, json):
            return _MalformedResponse()

    candidates = [
        ("primary_profile", {"kind": "chat", "provider": "openai", "model": "primary", "max_security_level": 5}),
        ("fallback_profile", {"kind": "chat", "provider": "fixture", "model": "fixture", "max_security_level": 5}),
    ]
    monkeypatch.setattr(providers_mod.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(gateway_main, "resolve_expert_chat_profiles", lambda policy: candidates)
    monkeypatch.setattr(
        gateway_main,
        "chat_provider_config_status",
        lambda provider, settings: ProviderConfigStatus(provider=provider, configured=True),
    )
    monkeypatch.setattr(gateway_main, "settings", _chat_settings(openai_api_key="configured-not-returned"))

    response = asyncio.run(gateway_main.expert_chat(_request("test_policy")))

    assert response.provider == "fixture"
    assert response.fallback.occurred is True
    assert response.fallback.reason == "preferred_provider_failed"
    assert [attempt.status for attempt in response.fallback.attempts] == ["failed", "succeeded"]
    assert response.fallback.attempts[0].error_code == "ProviderConfigurationError"
    assert "provider response body" not in response.model_dump_json()


def test_gateway_returns_safe_503_when_malformed_usage_exhausts_policy(monkeypatch):
    class _MalformedUsageResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "choices": [{"message": {"content": "answer"}}],
                "usage": {"prompt_tokens": "not-a-number"},
            }

    class _Client:
        def __init__(self, *, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url, *, headers, json):
            return _MalformedUsageResponse()

    candidates = [
        ("only_profile", {"kind": "chat", "provider": "openai", "model": "only", "max_security_level": 5}),
    ]
    monkeypatch.setattr(providers_mod.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(gateway_main, "resolve_expert_chat_profiles", lambda policy: candidates)
    monkeypatch.setattr(
        gateway_main,
        "chat_provider_config_status",
        lambda provider, settings: ProviderConfigStatus(provider=provider, configured=True),
    )
    monkeypatch.setattr(gateway_main, "settings", _chat_settings(openai_api_key="configured-not-returned"))

    with pytest.raises(HTTPException) as exc:
        asyncio.run(gateway_main.expert_chat(_request("test_policy")))

    assert exc.value.status_code == 503
    assert exc.value.detail["code"] == "expert_chat_provider_unavailable"
    assert exc.value.detail["attempts"][0]["status"] == "failed"
    assert exc.value.detail["attempts"][0]["error_code"] == "ProviderConfigurationError"
    assert "not-a-number" not in str(exc.value.detail)


def test_model_gateway_openapi_names_internal_expert_chat_contract():
    schema = gateway_main.app.openapi()
    operation = schema["paths"]["/internal/models/expert-chat"]["post"]

    assert operation["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ExpertChatCompletionRequest"
    }
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ExpertChatCompletionResponse"
    }
