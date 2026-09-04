from __future__ import annotations

import asyncio
import base64
import json
from types import SimpleNamespace

import httpx
import pytest

from svs_common.marker_client import (
    MarkerRunpodClient,
    MarkerRunpodError,
    extract_markdown,
    is_marker_pdf_upload,
    is_retryable_marker_error,
    markdown_filename_for_pdf,
    resolve_image,
)


API_KEY = "rp-test-secret"
ENDPOINT_ID = "ep-test"


def run(coro):
    return asyncio.run(coro)


def client_with_handler(handler) -> MarkerRunpodClient:
    client = MarkerRunpodClient(
        api_key=API_KEY,
        endpoint_id=ENDPOINT_ID,
        poll_interval_sec=1,
        timeout_sec=30,
        retry_backoff_sec=0,
        transport=httpx.MockTransport(handler),
    )

    async def no_sleep(seconds: int) -> None:
        return None

    client._sleep = no_sleep  # type: ignore[method-assign]
    return client


def test_marker_client_happy_path_returns_output_and_keeps_secret_out_of_logs():
    raw_pdf = b"%PDF-1.4 marker-test"
    captured: list[httpx.Request] = []
    statuses = iter(
        [
            {"status": "IN_QUEUE"},
            {
                "status": "COMPLETED",
                "output": {
                    "text": "# Converted\n\nBody",
                    "pages": 2,
                    "output_format": "markdown",
                },
            },
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        if request.url.path.endswith("/run"):
            return httpx.Response(200, json={"id": "job-123"})
        if request.url.path.endswith("/status/job-123"):
            return httpx.Response(200, json=next(statuses))
        return httpx.Response(404, json={"error": "unexpected"})

    logs: list[str] = []
    jobs: list[str] = []
    result = run(
        client_with_handler(handler).process_pdf_bytes(
            filename="source.pdf",
            pdf_bytes=raw_pdf,
            log_callback=logs.append,
            job_id_callback=jobs.append,
        )
    )

    assert result == {"text": "# Converted\n\nBody", "pages": 2, "output_format": "markdown"}
    assert jobs == ["job-123"]
    assert API_KEY not in "\n".join(logs)
    assert any("polling status=IN_QUEUE" in line for line in logs)
    assert any("completed status=COMPLETED" in line for line in logs)

    submit = next(request for request in captured if request.url.path.endswith("/run"))
    assert submit.headers["authorization"] == f"Bearer {API_KEY}"
    body = json.loads(submit.read().decode("utf-8"))
    assert body["input"]["filename"] == "source.pdf"
    assert base64.b64decode(body["input"]["pdf_base64"]) == raw_pdf


def test_marker_client_rejects_non_remote_mode():
    with pytest.raises(MarkerRunpodError, match="MARKER_MODE='local' is not supported"):
        MarkerRunpodClient(api_key=API_KEY, endpoint_id=ENDPOINT_ID, mode="local")
    with pytest.raises(MarkerRunpodError, match="MARKER_MODE='auto' is not supported"):
        MarkerRunpodClient(api_key=API_KEY, endpoint_id=ENDPOINT_ID, mode="auto")


def test_marker_client_missing_config_fails_before_network_call():
    client = MarkerRunpodClient(api_key="", endpoint_id="")
    with pytest.raises(MarkerRunpodError, match="not configured"):
        run(client.process_pdf_bytes(filename="x.pdf", pdf_bytes=b"%PDF"))


def test_marker_client_uses_runpod_alias_when_marker_config_absent(monkeypatch: pytest.MonkeyPatch):
    from svs_common import config as svs_config

    monkeypatch.delenv("MARKER_RUNPOD_API_KEY", raising=False)
    monkeypatch.delenv("MARKER_RUNPOD_ENDPOINT_ID", raising=False)
    monkeypatch.setenv("RUNPOD_API_KEY", "alias-key")
    monkeypatch.setenv("RUNPOD_ENDPOINT_ID", "alias-endpoint")
    monkeypatch.setattr(
        svs_config,
        "get_settings",
        lambda: SimpleNamespace(
            marker_runpod_api_key=None,
            marker_runpod_endpoint_id=None,
            runpod_api_key=None,
            runpod_endpoint_id=None,
            marker_mode="remote",
            marker_timeout_sec=30,
            marker_poll_interval_sec=1,
            marker_max_attempts=1,
            marker_retry_backoff_sec=0,
        ),
    )

    client = MarkerRunpodClient()

    assert client.api_key == "alias-key"
    assert client.endpoint_id == "alias-endpoint"


def test_marker_client_accepts_statecivics_marker_endpoint_alias(
    monkeypatch: pytest.MonkeyPatch,
):
    from svs_common import config as svs_config

    monkeypatch.delenv("MARKER_RUNPOD_API_KEY", raising=False)
    monkeypatch.delenv("MARKER_RUNPOD_ENDPOINT_ID", raising=False)
    monkeypatch.delenv("RUNPOD_ENDPOINT_ID", raising=False)
    monkeypatch.setenv("RUNPOD_API_KEY", "statecivics-key")
    monkeypatch.setenv("RUNPOD_MARKER_ENDPOINT_ID", "statecivics-marker-endpoint")
    monkeypatch.setattr(
        svs_config,
        "get_settings",
        lambda: SimpleNamespace(
            marker_runpod_api_key=None,
            marker_runpod_endpoint_id=None,
            runpod_api_key=None,
            runpod_endpoint_id=None,
            marker_mode="remote",
            marker_timeout_sec=30,
            marker_poll_interval_sec=1,
            marker_max_attempts=1,
            marker_retry_backoff_sec=0,
        ),
    )

    client = MarkerRunpodClient()

    assert client.api_key == "statecivics-key"
    assert client.endpoint_id == "statecivics-marker-endpoint"


def test_marker_specific_endpoint_precedes_legacy_and_generic_aliases(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("MARKER_RUNPOD_ENDPOINT_ID", "preferred-marker-endpoint")
    monkeypatch.setenv("RUNPOD_MARKER_ENDPOINT_ID", "legacy-marker-endpoint")
    monkeypatch.setenv("RUNPOD_ENDPOINT_ID", "generic-endpoint")

    client = MarkerRunpodClient(api_key="key")

    assert client.endpoint_id == "preferred-marker-endpoint"


def test_marker_client_uses_runpod_alias_when_settings_unavailable(monkeypatch: pytest.MonkeyPatch):
    from svs_common import config as svs_config

    monkeypatch.delenv("MARKER_RUNPOD_API_KEY", raising=False)
    monkeypatch.delenv("MARKER_RUNPOD_ENDPOINT_ID", raising=False)
    monkeypatch.setenv("RUNPOD_API_KEY", "alias-key")
    monkeypatch.setenv("RUNPOD_ENDPOINT_ID", "alias-endpoint")

    def unavailable_settings():
        raise RuntimeError("settings unavailable")

    monkeypatch.setattr(svs_config, "get_settings", unavailable_settings)

    client = MarkerRunpodClient()

    assert client.api_key == "alias-key"
    assert client.endpoint_id == "alias-endpoint"


def test_marker_client_terminal_failures_return_none():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/run"):
            return httpx.Response(200, json={"id": "job-fail"})
        return httpx.Response(200, json={"status": "FAILED", "error": "upstream failed"})

    logs: list[str] = []
    result = run(
        client_with_handler(handler).process_pdf_bytes(
            filename="source.pdf",
            pdf_bytes=b"%PDF",
            log_callback=logs.append,
        )
    )

    assert result is None
    assert any("failed status=FAILED" in line for line in logs)
    assert API_KEY not in "\n".join(logs)


def test_marker_client_retries_cuda_warmup_failure_then_returns_markdown():
    raw_pdf = b"%PDF-1.4 warmup"
    run_count = {"value": 0}
    captured_job_ids: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/run"):
            run_count["value"] += 1
            return httpx.Response(200, json={"id": f"job-{run_count['value']}"})
        if request.url.path.endswith("/status/job-1"):
            return httpx.Response(
                200,
                json={
                    "status": "FAILED",
                    "error": "CUDA error: no kernel image is available for execution on the device",
                },
            )
        if request.url.path.endswith("/status/job-2"):
            return httpx.Response(
                200,
                json={"status": "COMPLETED", "output": {"text": "# Warmed\n\nReady"}},
            )
        return httpx.Response(404)

    logs: list[str] = []
    result = run(
        client_with_handler(handler).process_pdf_bytes(
            filename="warmup.pdf",
            pdf_bytes=raw_pdf,
            max_attempts=2,
            log_callback=logs.append,
            job_id_callback=captured_job_ids.append,
        )
    )

    assert result == {"text": "# Warmed\n\nReady"}
    assert captured_job_ids == ["job-1", "job-2"]
    assert run_count["value"] == 2
    assert any("attempt start attempt=1" in line for line in logs)
    assert any("retrying attempt=2" in line for line in logs)
    assert any("attempt start attempt=2" in line for line in logs)
    assert API_KEY not in "\n".join(logs)


def test_marker_helpers_route_and_extract_markdown():
    assert is_marker_pdf_upload("spec.pdf", "application/pdf", "auto_detect_v1")
    assert is_marker_pdf_upload("spec.pdf", "application/pdf", "raw_pdf_research_v1")
    assert is_marker_pdf_upload("spec.pdf", "application/pdf", "pdf_markdown_external_v1")
    assert not is_marker_pdf_upload("spec.md", "text/markdown", "auto_detect_v1")
    assert markdown_filename_for_pdf("My Spec.pdf") == "My-Spec.md"
    assert extract_markdown({"markdown": {"content": "# Nested"}}) == "# Nested"
    with pytest.raises(MarkerRunpodError, match="no markdown"):
        extract_markdown({"images": []})
    assert is_retryable_marker_error("CUDA error: no kernel image is available")
    assert not is_retryable_marker_error("bad input: password protected pdf")


def test_resolve_image_from_base64():
    raw = b"image-bytes"
    result = run(resolve_image({"base64": base64.b64encode(raw).decode("ascii")}))
    assert result == raw
