from __future__ import annotations

import base64
import hashlib
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

logger = logging.getLogger(__name__)

DEFAULT_MARKER_POLL_INTERVAL_SEC = 3
DEFAULT_MARKER_TIMEOUT_SEC = 1800
DEFAULT_MARKER_MAX_ATTEMPTS = 2
DEFAULT_MARKER_RETRY_BACKOFF_SEC = 5
DEFAULT_HTTP_TIMEOUT_SEC = 30
RUNPOD_BASE_URL = "https://api.runpod.ai/v2"


class MarkerRunpodError(RuntimeError):
    pass


def _read_config() -> dict[str, str | None]:
    env = {
        "api_key": os.getenv("MARKER_RUNPOD_API_KEY") or None,
        "endpoint_id": os.getenv("MARKER_RUNPOD_ENDPOINT_ID") or None,
        "fallback_api_key": os.getenv("RUNPOD_API_KEY") or None,
        "fallback_endpoint_id": os.getenv("RUNPOD_ENDPOINT_ID") or None,
        "mode": (os.getenv("MARKER_MODE") or "").strip().lower() or None,
        "timeout_sec": os.getenv("MARKER_TIMEOUT_SEC") or None,
        "poll_interval_sec": os.getenv("MARKER_POLL_INTERVAL_SEC") or None,
        "max_attempts": os.getenv("MARKER_MAX_ATTEMPTS") or None,
        "retry_backoff_sec": os.getenv("MARKER_RETRY_BACKOFF_SEC") or None,
    }
    try:
        from .config import get_settings

        settings = get_settings()
    except Exception:
        return {
            "api_key": env["api_key"] or env["fallback_api_key"],
            "endpoint_id": env["endpoint_id"] or env["fallback_endpoint_id"],
            "mode": env["mode"] or "remote",
            "timeout_sec": env["timeout_sec"],
            "poll_interval_sec": env["poll_interval_sec"],
            "max_attempts": env["max_attempts"],
            "retry_backoff_sec": env["retry_backoff_sec"],
        }
    return {
        "api_key": env["api_key"] or settings.marker_runpod_api_key or env["fallback_api_key"] or settings.runpod_api_key,
        "endpoint_id": env["endpoint_id"] or settings.marker_runpod_endpoint_id or env["fallback_endpoint_id"] or settings.runpod_endpoint_id,
        "mode": env["mode"] or settings.marker_mode,
        "timeout_sec": env["timeout_sec"] or str(settings.marker_timeout_sec),
        "poll_interval_sec": env["poll_interval_sec"] or str(settings.marker_poll_interval_sec),
        "max_attempts": env["max_attempts"] or str(settings.marker_max_attempts),
        "retry_backoff_sec": env["retry_backoff_sec"] or str(settings.marker_retry_backoff_sec),
    }


def sanitize_stem(filename: str | None, fallback: str = "document") -> str:
    stem = Path(filename or fallback).stem or fallback
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", stem).strip(".-")
    return stem or fallback


def markdown_filename_for_pdf(filename: str | None) -> str:
    return f"{sanitize_stem(filename, 'pdf-document')}.md"


def pdf_source_id(pdf_bytes: bytes) -> str:
    return f"pdf_sha256_{hashlib.sha256(pdf_bytes).hexdigest()[:16]}"


def is_marker_pdf_upload(filename: str | None, mime_type: str | None, requested_mode: str | None) -> bool:
    name = (filename or "").lower()
    mime = (mime_type or "").lower()
    mode = (requested_mode or "auto_detect_v1").strip()
    looks_pdf = name.endswith(".pdf") or mime == "application/pdf"
    if not looks_pdf:
        return False
    return mode in {"auto_detect_v1", "raw_pdf_research_v1", "pdf_markdown_external_v1"}


def extract_markdown(output: dict[str, Any]) -> str:
    if isinstance(output.get("text"), str) and output["text"].strip():
        return output["text"]
    if isinstance(output.get("markdown"), str) and output["markdown"].strip():
        return output["markdown"]
    markdown = output.get("markdown")
    if isinstance(markdown, dict):
        for key in ("content", "text", "body"):
            value = markdown.get(key)
            if isinstance(value, str) and value.strip():
                return value
    raise MarkerRunpodError("Marker completed but returned no markdown text")


def is_retryable_marker_error(error: str | None) -> bool:
    normalized = (error or "").lower()
    retryable_markers = (
        "cuda error",
        "no kernel image",
        "cold start",
        "warm",
        "initializ",
        "container",
        "worker exited",
        "temporarily unavailable",
        "timeout",
        "timed out",
        "rate limit",
        "429",
        "503",
        "504",
    )
    return any(marker in normalized for marker in retryable_markers)


def marker_attribute_summary(
    *,
    original_filename: str | None,
    pdf_bytes: bytes,
    output: dict[str, Any],
    job_id: str | None = None,
    source_object_key: str | None = None,
) -> dict[str, Any]:
    attrs: dict[str, Any] = {
        "source_pdf_id": pdf_source_id(pdf_bytes),
        "source_pdf_filename": original_filename or "uploaded.pdf",
        "pdf_parser": "runpod_marker",
    }
    if job_id:
        attrs["marker_job_id"] = job_id
    if source_object_key:
        attrs["source_pdf_object_key"] = source_object_key
    for source_key, attr_key in (
        ("pages", "marker_pages"),
        ("processing_time_seconds", "marker_processing_time_seconds"),
        ("output_format", "marker_output_format"),
    ):
        value = output.get(source_key)
        if isinstance(value, (str, int, float, bool)):
            attrs[attr_key] = value
    metadata = output.get("metadata")
    if isinstance(metadata, dict):
        safe_metadata = {
            key: value
            for key, value in metadata.items()
            if isinstance(value, (str, int, float, bool)) and "key" not in key.lower() and "secret" not in key.lower()
        }
        if safe_metadata:
            attrs["marker_metadata"] = safe_metadata
    return attrs


class MarkerRunpodClient:
    """Async client for an external RunPod Marker serverless endpoint."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        endpoint_id: str | None = None,
        mode: str | None = None,
        poll_interval_sec: int | None = None,
        timeout_sec: int | None = None,
        max_attempts: int | None = None,
        retry_backoff_sec: int | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        env = _read_config()
        self.api_key = api_key if api_key is not None else env["api_key"]
        self.endpoint_id = endpoint_id if endpoint_id is not None else env["endpoint_id"]
        resolved_mode = (mode if mode is not None else env["mode"]) or "remote"
        self.mode = resolved_mode.strip().lower()
        if self.mode != "remote":
            raise MarkerRunpodError(
                f"MARKER_MODE='{self.mode}' is not supported. ExAIS calls RunPod Marker only; "
                "set MARKER_MODE=remote and provide MARKER_RUNPOD_API_KEY plus MARKER_RUNPOD_ENDPOINT_ID."
            )

        self.poll_interval_sec = int(
            poll_interval_sec
            if poll_interval_sec is not None
            else env["poll_interval_sec"] or DEFAULT_MARKER_POLL_INTERVAL_SEC
        )
        self.timeout_sec = int(
            timeout_sec if timeout_sec is not None else env["timeout_sec"] or DEFAULT_MARKER_TIMEOUT_SEC
        )
        self.max_attempts = max(
            1,
            int(max_attempts if max_attempts is not None else env["max_attempts"] or DEFAULT_MARKER_MAX_ATTEMPTS),
        )
        self.retry_backoff_sec = max(
            0,
            int(
                retry_backoff_sec
                if retry_backoff_sec is not None
                else env["retry_backoff_sec"] or DEFAULT_MARKER_RETRY_BACKOFF_SEC
            ),
        )
        self.transport = transport

    def _assert_configured(self) -> None:
        if not self.api_key or not self.endpoint_id:
            raise MarkerRunpodError(
                "Marker RunPod transport is not configured: set MARKER_RUNPOD_API_KEY and "
                "MARKER_RUNPOD_ENDPOINT_ID, or fallback RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID."
            )

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _endpoint_base(self) -> str:
        return f"{RUNPOD_BASE_URL}/{self.endpoint_id}"

    async def process_pdf_bytes(
        self,
        *,
        filename: str,
        pdf_bytes: bytes,
        poll_interval_sec: int | None = None,
        max_poll_sec: int | None = None,
        max_attempts: int | None = None,
        log_callback: Callable[[str], None] | Callable[[str], Awaitable[None]] | None = None,
        job_id_callback: Callable[[str], None] | Callable[[str], Awaitable[None]] | None = None,
    ) -> dict[str, Any] | None:
        self._assert_configured()
        poll_sec = int(poll_interval_sec if poll_interval_sec is not None else self.poll_interval_sec)
        cap = int(max_poll_sec if max_poll_sec is not None else self.timeout_sec)
        if cap <= 0:
            cap = DEFAULT_MARKER_TIMEOUT_SEC
        attempts = max(1, int(max_attempts if max_attempts is not None else self.max_attempts))

        async def emit(line: str) -> None:
            logger.info("[marker] %s", line)
            if log_callback is None:
                return
            result = log_callback(line)
            if hasattr(result, "__await__"):
                await result  # type: ignore[misc]

        async def emit_job_id(job_id: str) -> None:
            if job_id_callback is None:
                return
            result = job_id_callback(job_id)
            if hasattr(result, "__await__"):
                await result  # type: ignore[misc]

        payload = {
            "input": {
                "pdf_base64": base64.b64encode(pdf_bytes).decode("ascii"),
                "filename": filename,
            }
        }

        for attempt in range(1, attempts + 1):
            await emit(f"attempt start attempt={attempt} max_attempts={attempts}")
            result, retryable = await self._process_pdf_bytes_once(
                payload=payload,
                poll_sec=poll_sec,
                cap=cap,
                emit=emit,
                emit_job_id=emit_job_id,
            )
            if result is not None:
                return result
            if attempt >= attempts or not retryable:
                return None
            await emit(f"retrying attempt={attempt + 1} max_attempts={attempts}")
            if self.retry_backoff_sec > 0:
                await self._sleep(self.retry_backoff_sec)
        return None

    async def _process_pdf_bytes_once(
        self,
        *,
        payload: dict[str, Any],
        poll_sec: int,
        cap: int,
        emit: Callable[[str], Awaitable[None]],
        emit_job_id: Callable[[str], Awaitable[None]],
    ) -> tuple[dict[str, Any] | None, bool]:
        async with httpx.AsyncClient(transport=self.transport, timeout=DEFAULT_HTTP_TIMEOUT_SEC) as client:
            try:
                resp = await client.post(f"{self._endpoint_base()}/run", json=payload, headers=self._auth_headers())
            except httpx.HTTPError as exc:
                await emit(f"submit error={exc.__class__.__name__}")
                return None, True
            if resp.status_code != 200:
                await emit(f"submit failed status={resp.status_code}")
                return None, resp.status_code >= 500 or resp.status_code in {408, 409, 425, 429}
            try:
                data = resp.json()
            except ValueError:
                await emit("submit failed non_json")
                return None, False
            job_id = data.get("id")
            if not isinstance(job_id, str) or not job_id:
                await emit("submit failed missing_id")
                return None, False

            await emit(f"submitted job_id={job_id}")
            await emit_job_id(job_id)
            started = time.monotonic()
            last_status: str | None = None

            while True:
                if time.monotonic() - started > cap:
                    await emit(f"timed out after {int(time.monotonic() - started)}s")
                    return None, True
                try:
                    poll_resp = await client.get(
                        f"{self._endpoint_base()}/status/{job_id}",
                        headers=self._auth_headers(),
                    )
                except httpx.HTTPError as exc:
                    await emit(f"poll error={exc.__class__.__name__}")
                    return None, True
                if poll_resp.status_code != 200:
                    await emit(f"poll failed status={poll_resp.status_code}")
                    return None, poll_resp.status_code >= 500 or poll_resp.status_code in {408, 409, 425, 429}
                try:
                    poll_data = poll_resp.json()
                except ValueError:
                    await emit("poll failed non_json")
                    return None, False
                status = poll_data.get("status") or "UNKNOWN"
                if status != last_status:
                    await emit(f"polling status={status}")
                    last_status = status
                if status == "COMPLETED":
                    output = poll_data.get("output") or {}
                    await emit("completed status=COMPLETED")
                    return (output if isinstance(output, dict) else {}), False
                if status in {"FAILED", "CANCELLED"}:
                    error = poll_data.get("error") or "unknown"
                    await emit(f"failed status={status} error={error}")
                    return None, status == "FAILED" and is_retryable_marker_error(str(error))
                await self._sleep(poll_sec)

    async def _sleep(self, seconds: int) -> None:
        import asyncio

        await asyncio.sleep(max(1, seconds))


async def resolve_image(image_meta: dict[str, Any], *, timeout: int = 30) -> bytes:
    if not isinstance(image_meta, dict):
        raise ValueError("image_meta must be a dict")
    b64 = image_meta.get("base64")
    if isinstance(b64, str) and b64:
        return base64.b64decode(b64)
    url = image_meta.get("url")
    if isinstance(url, str) and url:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
    raise ValueError("image_meta has neither 'base64' nor 'url'")
