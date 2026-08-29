from __future__ import annotations

from urllib.parse import urlparse

import httpx
from pydantic import ValidationError

from .config import get_settings
from .schemas import ExpertChatCompletionRequest, ExpertChatCompletionResponse


class ExpertChatGatewayError(RuntimeError):
    """A safe, provider-neutral failure from the internal model gateway."""

    def __init__(self, code: str, *, status_code: int | None = None):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def _model_gateway_base_url(value: str) -> str:
    normalized = str(value or "").strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ExpertChatGatewayError("invalid_model_gateway_url")
    if parsed.username or parsed.password:
        raise ExpertChatGatewayError("invalid_model_gateway_url")
    return normalized


async def complete_expert_chat(req: ExpertChatCompletionRequest) -> ExpertChatCompletionResponse:
    """Complete an expert chat exclusively through the internal ExAIS gateway."""

    settings = get_settings()
    base_url = _model_gateway_base_url(settings.model_gateway_url)
    timeout = float(settings.expert_chat_timeout_sec)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{base_url}/internal/models/expert-chat",
                json=req.model_dump(mode="json"),
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        raise ExpertChatGatewayError(
            "model_gateway_rejected_expert_chat",
            status_code=exc.response.status_code,
        ) from exc
    except (httpx.HTTPError, TimeoutError, OSError) as exc:
        raise ExpertChatGatewayError("model_gateway_unavailable") from exc

    try:
        payload = response.json()
    except (TypeError, ValueError) as exc:
        raise ExpertChatGatewayError("invalid_model_gateway_response") from exc

    try:
        return ExpertChatCompletionResponse.model_validate(payload)
    except (ValidationError, TypeError, ValueError) as exc:
        raise ExpertChatGatewayError("invalid_model_gateway_response") from exc
