from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "release" / "live-provider-validation.py"
sys.path.insert(0, str(SCRIPT.parent))
spec = importlib.util.spec_from_file_location("live_provider_validation", SCRIPT)
live_provider_validation = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules["live_provider_validation"] = live_provider_validation
spec.loader.exec_module(live_provider_validation)


def _args(*items: str):
    return live_provider_validation.build_parser().parse_args(list(items))


def _run(args, env):
    return live_provider_validation.run_validation(args, env=env)


def test_missing_provider_inputs_do_not_claim_live_proof():
    report = _run(_args("--providers", "openai,runpod,tei,infinity,self_hosted"), env={})

    assert report["live_proof_claimed"] is False
    assert report["gateway_live_proof_claimed"] is False
    assert report["proof_status"] == "skipped_no_live_provider_calls"
    assert set(report["unavailable_or_unconfigured_providers"]) == {
        "openai",
        "runpod",
        "tei",
        "infinity",
        "self_hosted",
    }
    rendered = json.dumps(report)
    assert "OPENAI_API_KEY" in rendered
    assert "sk-" not in rendered


def test_envref_without_runtime_value_is_not_treated_as_live_credential():
    report = _run(
        _args("--providers", "openai"),
        env={"OPENAI_API_KEY": "envref://OPENAI_API_KEY"},
    )

    assert report["live_proof_claimed"] is False
    provider = report["providers"][0]
    assert provider["status"] == "skipped_missing_inputs"
    assert provider["required_inputs"][0]["source"] == "envref://OPENAI_API_KEY"
    assert provider["required_inputs"][0]["issue"] == "secret_reference_unresolved"


def test_unapproved_or_policy_denied_providers_are_not_called(monkeypatch: pytest.MonkeyPatch):
    def fail_gateway_call(*_args, **_kwargs):
        pytest.fail("gateway call should not happen for denied providers")

    monkeypatch.setattr(live_provider_validation, "post_gateway_json", fail_gateway_call)

    unapproved = _run(
        _args(
            "--providers",
            "openai",
            "--approved-providers",
            "runpod",
            "--gateway-url",
            "http://gateway.invalid",
        ),
        env={"OPENAI_API_KEY": "sk-test-secret-value"},
    )
    policy_denied = _run(
        _args(
            "--providers",
            "openai",
            "--approved-providers",
            "openai",
            "--security-level",
            "4",
            "--gateway-url",
            "http://gateway.invalid",
        ),
        env={"OPENAI_API_KEY": "sk-test-secret-value"},
    )

    assert unapproved["providers"][0]["status"] == "unapproved"
    assert policy_denied["providers"][0]["status"] == "policy_denied"
    rendered = json.dumps([unapproved, policy_denied])
    assert "sk-test-secret-value" not in rendered


def test_gateway_probe_records_latency_cost_and_redacts_secret_values(monkeypatch: pytest.MonkeyPatch):
    calls = []

    def fake_gateway_call(gateway_url, path, payload, timeout_seconds):
        calls.append({"gateway_url": gateway_url, "path": path, "payload": payload, "timeout": timeout_seconds})
        if path == "/internal/models/estimate-cost":
            return {
                "model_profile_id": "qwen3_embedding_local_4b",
                "provider": "runpod",
                "model": "Qwen/Qwen3-Embedding-4B",
                "dimensions": 2560,
                "estimated_tokens": 6,
                "estimated_cost_usd": None,
                "reason": "cost_unavailable",
            }
        if path == "/internal/models/embeddings":
            return {
                "object": "list",
                "provider": "runpod",
                "model": "Qwen/Qwen3-Embedding-4B",
                "dimensions": 2560,
                "data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}],
                "usage": {"total_tokens": 6},
            }
        if path == "/internal/models/rerank":
            return {
                "provider": "runpod",
                "model": "Qwen/Qwen3-Reranker-4B",
                "results": [{"index": 0, "relevance_score": 0.9}],
            }
        raise AssertionError(path)

    monkeypatch.setattr(live_provider_validation, "post_gateway_json", fake_gateway_call)
    report = _run(
        _args(
            "--providers",
            "runpod",
            "--approved-providers",
            "runpod",
            "--rerank-providers",
            "runpod",
            "--gateway-url",
            "http://gateway.internal",
            "--skip-health-probe",
        ),
        env={
            "RUNPOD_EMBEDDING_ENDPOINT_URL": "https://api.runpod.ai/v2/endpoint/runsync",
            "RUNPOD_API_KEY": "rp_secret_should_not_appear",
        },
    )

    assert report["live_proof_claimed"] is True
    assert report["gateway_live_proof_claimed"] is True
    provider = report["providers"][0]
    assert provider["status"] == "success"
    assert provider["operations"]["embedding"]["execution_path"] == "gateway_http"
    assert provider["operations"]["embedding"]["first_vector_dimensions"] == 3
    assert provider["operations"]["rerank"]["status"] == "success"
    assert provider["cost_metadata"]["reason"] == "cost_unavailable"
    assert [call["path"] for call in calls] == [
        "/internal/models/estimate-cost",
        "/internal/models/embeddings",
        "/internal/models/rerank",
    ]
    rendered = json.dumps(report)
    assert "rp_secret_should_not_appear" not in rendered
    assert "https://api.runpod.ai" not in rendered


def test_malformed_gateway_success_body_does_not_claim_live_proof(monkeypatch: pytest.MonkeyPatch):
    def malformed_gateway_call(gateway_url, path, payload, timeout_seconds):
        return {}

    monkeypatch.setattr(live_provider_validation, "post_gateway_json", malformed_gateway_call)
    args = _args(
        "--providers",
        "runpod",
        "--approved-providers",
        "runpod",
        "--rerank-providers",
        "runpod",
        "--gateway-url",
        "http://gateway.internal",
        "--skip-health-probe",
    )
    report = _run(
        args,
        env={
            "RUNPOD_EMBEDDING_ENDPOINT_URL": "https://api.runpod.ai/v2/endpoint/runsync",
            "RUNPOD_API_KEY": "rp_secret_should_not_appear",
        },
    )

    assert report["live_proof_claimed"] is False
    assert report["gateway_live_proof_claimed"] is False
    assert report["proof_status"] == "skipped_no_live_provider_calls"
    assert report["providers"][0]["status"] == "unavailable"
    assert report["providers"][0]["operations"]["embedding"]["error"] == {
        "type": "MalformedGatewayResponse",
        "code": "missing_embedding_vector",
    }
    assert live_provider_validation.exit_code(report, require_live=True) == 2


def test_requested_malformed_rerank_makes_live_provider_report_partial(monkeypatch: pytest.MonkeyPatch):
    def mixed_gateway_call(gateway_url, path, payload, timeout_seconds):
        if path == "/internal/models/estimate-cost":
            return {"provider": "runpod", "estimated_tokens": 6, "reason": "cost_unavailable"}
        if path == "/internal/models/embeddings":
            return {
                "object": "list",
                "provider": "runpod",
                "model": "Qwen/Qwen3-Embedding-4B",
                "dimensions": 2560,
                "data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}],
            }
        if path == "/internal/models/rerank":
            return {}
        raise AssertionError(path)

    monkeypatch.setattr(live_provider_validation, "post_gateway_json", mixed_gateway_call)
    report = _run(
        _args(
            "--providers",
            "runpod",
            "--approved-providers",
            "runpod",
            "--rerank-providers",
            "runpod",
            "--gateway-url",
            "http://gateway.internal",
            "--skip-health-probe",
        ),
        env={
            "RUNPOD_EMBEDDING_ENDPOINT_URL": "https://api.runpod.ai/v2/endpoint/runsync",
            "RUNPOD_API_KEY": "rp_secret_should_not_appear",
        },
    )

    assert report["live_proof_claimed"] is True
    assert report["gateway_live_proof_claimed"] is True
    assert report["proof_status"] == "partial"
    assert report["partial_providers"] == ["runpod"]
    assert report["providers"][0]["status"] == "partial"
    assert report["providers"][0]["operations"]["rerank"]["error"] == {
        "type": "MalformedGatewayResponse",
        "code": "missing_rerank_results",
    }
    assert live_provider_validation.exit_code(report, require_live=True) == 1
