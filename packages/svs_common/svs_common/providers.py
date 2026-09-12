from __future__ import annotations
import asyncio, hashlib, json, logging, math, random, time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from typing import Protocol
import httpx
from .config import get_settings
from .provider_probe import health_allows_routing, normalize_health_status
from .schemas import EmbeddingData, EmbeddingResponse, ExpertChatMessage, RerankResponse, RerankResult

logger = logging.getLogger(__name__)

class EmbeddingProvider(Protocol):
    async def embed(self, texts: list[str], model: str, dimensions: int, input_type: str | None = None) -> EmbeddingResponse: ...

class RerankProvider(Protocol):
    async def rerank(self, query: str, documents: list[str], model: str, top_n: int | None = None) -> RerankResponse: ...


@dataclass(frozen=True)
class ChatProviderResult:
    content: str
    model: str
    usage: dict[str, int]
    finish_reason: str | None = None


class ChatProvider(Protocol):
    provider: str

    async def complete(
        self,
        messages: list[ExpertChatMessage],
        model: str,
        *,
        max_output_tokens: int,
        temperature: float,
    ) -> ChatProviderResult: ...

class ProviderConfigurationError(RuntimeError):
    """Raised when a selected provider is not configured for runtime use."""

@dataclass(frozen=True)
class ProviderConfigStatus:
    provider: str
    configured: bool
    required_env: tuple[str, ...] = ()
    reason: str | None = None
    health_status: str = "unknown"
    p95_latency_ms: int | None = None
    max_security_level: int | None = None
    region: str | None = None
    model_revision: str | None = None
    auth_secret_ref: str | None = None
    routing_state: str = "unknown"


def _setting(settings: Any, name: str) -> str | None:
    value = getattr(settings, name, None)
    if value is None:
        return None
    return str(value).strip()


def _status(
    provider: str,
    env_names: tuple[str, ...],
    configured: bool,
    reason: str | None = None,
    **metadata: Any,
) -> ProviderConfigStatus:
    if configured:
        return ProviderConfigStatus(provider=provider, configured=True, required_env=env_names, **metadata)
    missing = ", ".join(env_names) if env_names else "provider configuration"
    return ProviderConfigStatus(
        provider=provider,
        configured=False,
        required_env=env_names,
        reason=reason or f"{provider} embedding provider requires {missing}",
        **metadata,
    )


def provider_config_status(provider_name: str, settings: Any | None = None) -> ProviderConfigStatus:
    provider = (provider_name or "").strip().lower()
    s = settings or get_settings()
    if provider == "hash_mock":
        return ProviderConfigStatus(provider=provider, configured=True)
    if provider == "openai":
        return _status(provider, ("OPENAI_API_KEY",), bool(_setting(s, "openai_api_key")))
    if provider == "voyage":
        return _status(provider, ("VOYAGE_API_KEY",), bool(_setting(s, "voyage_api_key")))
    if provider == "cohere":
        return _status(provider, ("COHERE_API_KEY",), bool(_setting(s, "cohere_api_key")))
    if provider in {"jina", "tei", "huggingface_tei"}:
        return _status(provider, ("TEI_ENDPOINT_URL",), bool(_setting(s, "tei_endpoint_url")))
    if provider in RUNPOD_PROVIDERS:
        return _status(
            provider,
            ("RUNPOD_EMBEDDING_ENDPOINT_URL",),
            bool(_setting(s, "runpod_embedding_endpoint_url")),
            auth_secret_ref="envref://RUNPOD_API_KEY" if _setting(s, "runpod_api_key") else None,
        )
    if provider == "infinity":
        return _status(provider, ("INFINITY_ENDPOINT_URL",), bool(_setting(s, "infinity_endpoint_url")))
    if provider in {"self_hosted", "openai_compatible_private"}:
        return _status(
            provider,
            ("SELF_HOSTED_MODEL_ENDPOINT_URL",),
            bool(_setting(s, "self_hosted_model_endpoint_url")),
            auth_secret_ref="envref://SELF_HOSTED_MODEL_API_KEY" if _setting(s, "self_hosted_model_api_key") else None,
        )
    return ProviderConfigStatus(
        provider=provider or "unknown",
        configured=False,
        reason=f"unknown embedding provider: {provider_name}",
    )


class HashEmbeddingProvider:
    provider = 'hash_mock'
    async def embed(self, texts: list[str], model: str = 'deterministic-dev-hash', dimensions: int = 1536, input_type: str | None = None) -> EmbeddingResponse:
        data = [EmbeddingData(embedding=self._vector(t, dimensions), index=i) for i, t in enumerate(texts)]
        return EmbeddingResponse(data=data, model=model, provider=self.provider, dimensions=dimensions, usage={'prompt_tokens': sum(len(t.split()) for t in texts), 'total_tokens': sum(len(t.split()) for t in texts)})

    def _vector(self, text: str, dimensions: int) -> list[float]:
        digest = hashlib.sha256(text.encode()).digest()
        vals, i = [], 0
        while len(vals) < dimensions:
            block = hashlib.sha256(digest + i.to_bytes(4, 'big')).digest()
            vals.extend([(b / 127.5) - 1.0 for b in block])
            i += 1
        vals = vals[:dimensions]
        norm = math.sqrt(sum(v * v for v in vals)) or 1.0
        return [v / norm for v in vals]

# --- Embedding request batching ------------------------------------------------
#
# Remote embedding endpoints cap the size of a single request. OpenAI rejects an
# embeddings request whose inputs exceed 300,000 tokens with HTTP 400 and code
# "max_tokens_per_request" -- verified live against text-embedding-3-small on
# 2026-09-10, where 296,755 tokens returned 200 and 302,822 tokens returned
# "Requested 302822 tokens, max 300000 tokens per request". Posting every chunk
# of a document in a single request therefore makes large documents
# un-indexable, so providers split their inputs into ordered batches.
#
# Callers match vectors to chunk text positionally, so the batching contract is
# strict: embed() returns exactly one vector per input, in input order, or it
# raises. A short or reordered result would misalign vectors with text and
# corrupt retrieval silently, which is worse than a failed ingest, so every
# batch is checked rather than truncated.

OPENAI_MAX_TOKENS_PER_REQUEST = 300_000
OPENAI_MAX_INPUTS_PER_REQUEST = 2048

# Voyage and Cohere publish smaller per-request caps than OpenAI. These are
# applied conservatively -- a batch smaller than the vendor cap is always
# accepted where a larger one would be -- and have NOT been confirmed against
# the live vendor APIs, unlike the OpenAI cap above.
VOYAGE_MAX_TOKENS_PER_REQUEST = 100_000
VOYAGE_MAX_INPUTS_PER_REQUEST = 1000
COHERE_MAX_INPUTS_PER_REQUEST = 96

# Tokens are estimated from character length because the runtime images carry no
# tokenizer. Measured with cl100k_base over the 12,577 chunks of the Kansas
# fiscal corpus, the true ratio is 3.08 chars/token at the median and 1.58 at
# the minimum, so a divisor of 2.0 over-counts for realistic text; the batch
# budget then leaves further headroom under the hard cap. Content that still
# defeats the estimate is handled rather than failed: a request rejected for
# exceeding the token cap is bisected and re-sent.
EMBEDDING_CHARS_PER_TOKEN = 2.0
DEFAULT_EMBEDDING_BATCH_TOKEN_BUDGET = 200_000


class EmbeddingBatchError(RuntimeError):
    """Raised when a provider cannot return one vector per input, in input order."""


class _EmbeddingRequestTooLarge(RuntimeError):
    """An endpoint rejected a batch for exceeding its per-request token cap."""


def estimate_embedding_tokens(text: str) -> int:
    """Return a deliberately high token estimate for one input."""
    return max(1, math.ceil(len(text) / EMBEDDING_CHARS_PER_TOKEN))


def plan_embedding_batches(
    texts: list[str],
    *,
    token_budget: int,
    max_inputs: int | None = None,
) -> list[tuple[int, int]]:
    """Split inputs into contiguous [start, end) spans that preserve input order.

    Every input falls in exactly one span and the spans are returned in input
    order, so concatenating per-span results rebuilds the caller's ordering. An
    input whose own estimate already exceeds the budget still gets its own span:
    it is sent and allowed to fail loudly rather than being dropped or split.
    """
    if not texts:
        return []
    budget = max(1, int(token_budget))
    limit = max(1, int(max_inputs)) if max_inputs else None
    spans: list[tuple[int, int]] = []
    start = 0
    used = 0
    for index, text in enumerate(texts):
        cost = estimate_embedding_tokens(text)
        batched = index - start
        if batched and (used + cost > budget or (limit is not None and batched >= limit)):
            spans.append((start, index))
            start, used = index, 0
        used += cost
    spans.append((start, len(texts)))
    return spans


def ordered_batch_vectors(items: Any, *, expected: int, provider: str) -> list[list[float]]:
    """Order one batch's vectors by the index the endpoint reported, not arrival order."""
    if not isinstance(items, list) or len(items) != expected:
        found = len(items) if isinstance(items, list) else "no"
        raise EmbeddingBatchError(
            f"{provider} returned {found} embeddings for a batch of {expected} inputs"
        )
    slots: list[list[float] | None] = [None] * expected
    for position, item in enumerate(items):
        if isinstance(item, dict):
            index = int(item.get("index", position))
            vector = item.get("embedding")
        else:
            index = position
            vector = item
        if vector is None:
            raise EmbeddingBatchError(f"{provider} returned a batch item without an embedding")
        if not 0 <= index < expected:
            raise EmbeddingBatchError(
                f"{provider} returned embedding index {index} outside a batch of {expected} inputs"
            )
        if slots[index] is not None:
            raise EmbeddingBatchError(f"{provider} returned duplicate embedding index {index}")
        slots[index] = list(vector)
    ordered = [slot for slot in slots if slot is not None]
    if len(ordered) != expected:
        raise EmbeddingBatchError(
            f"{provider} did not return an embedding for every input in a batch of {expected}"
        )
    return ordered


def accumulate_embedding_usage(totals: dict[str, int], usage: Any) -> None:
    """Sum numeric usage counters across the batches of one embed() call."""
    if not isinstance(usage, dict):
        return
    for key, value in usage.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        totals[key] = int(totals.get(key, 0) + value)


def _is_token_cap_rejection(response: httpx.Response) -> bool:
    """True when a 400 says the batch exceeded the endpoint's per-request token cap."""
    try:
        body = response.json()
    except (TypeError, ValueError):
        return False
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return False
    marker = " ".join(
        str(error.get(field) or "") for field in ("code", "type", "message")
    ).lower()
    return "max_tokens_per_request" in marker or "tokens per request" in marker


async def _send_embedding_batch(
    send: Callable[[list[str]], Awaitable[list[list[float]]]],
    batch: list[str],
    *,
    provider: str,
) -> list[list[float]]:
    """Send one batch, bisecting it if the endpoint says it exceeded the token cap.

    Bisection is a correctness backstop for content the character-based estimate
    under-counts, not a retry policy: it reacts only to the endpoint's explicit
    token-cap rejection, adds no delay, and terminates because each step halves
    the batch. A single input that is still too large is a chunking fault and is
    raised rather than dropped.
    """
    try:
        return await send(batch)
    except _EmbeddingRequestTooLarge:
        if len(batch) <= 1:
            size = len(batch[0]) if batch else 0
            raise EmbeddingBatchError(
                f"{provider} rejected a single {size}-character input for exceeding its "
                "per-request token cap; the chunking profile must emit smaller chunks"
            ) from None
        middle = len(batch) // 2
        head = await _send_embedding_batch(send, batch[:middle], provider=provider)
        tail = await _send_embedding_batch(send, batch[middle:], provider=provider)
        return head + tail


async def embed_in_order(
    texts: list[str],
    *,
    provider: str,
    token_budget: int,
    max_inputs: int | None,
    send: Callable[[list[str]], Awaitable[list[list[float]]]],
) -> list[list[float]]:
    """Embed every input across as many requests as needed, preserving input order."""
    vectors: list[list[float]] = []
    for start, end in plan_embedding_batches(texts, token_budget=token_budget, max_inputs=max_inputs):
        batch = texts[start:end]
        batch_vectors = await _send_embedding_batch(send, batch, provider=provider)
        if len(batch_vectors) != len(batch):
            raise EmbeddingBatchError(
                f"{provider} returned {len(batch_vectors)} embeddings for inputs "
                f"{start}..{end - 1} of {len(texts)}"
            )
        vectors.extend(batch_vectors)
    if len(vectors) != len(texts):
        raise EmbeddingBatchError(
            f"{provider} returned {len(vectors)} embeddings for {len(texts)} inputs"
        )
    return vectors


class OpenAIEmbeddingProvider:
    provider = 'openai'
    def __init__(self, api_key: str | None = None, *, batch_token_budget: int | None = None):
        self.api_key = api_key
        self.batch_token_budget = int(batch_token_budget or DEFAULT_EMBEDDING_BATCH_TOKEN_BUDGET)

    async def embed(self, texts: list[str], model: str, dimensions: int, input_type: str | None = None) -> EmbeddingResponse:
        api_key = self.api_key or get_settings().openai_api_key
        if not api_key:
            raise ProviderConfigurationError("openai embedding provider requires OPENAI_API_KEY")
        if not texts:
            return EmbeddingResponse(data=[], model=model, provider=self.provider, dimensions=dimensions, usage={})
        usage: dict[str, int] = {}
        response_model = model
        async with httpx.AsyncClient(timeout=120) as client:
            async def send(batch: list[str]) -> list[list[float]]:
                nonlocal response_model
                resp = await client.post(
                    'https://api.openai.com/v1/embeddings',
                    headers={'Authorization': f'Bearer {api_key}'},
                    json={'model': model, 'input': batch, 'dimensions': dimensions},
                )
                if resp.status_code == 400 and _is_token_cap_rejection(resp):
                    raise _EmbeddingRequestTooLarge()
                resp.raise_for_status()
                body = resp.json()
                response_model = body.get('model', response_model)
                accumulate_embedding_usage(usage, body.get('usage'))
                return ordered_batch_vectors(body.get('data', []), expected=len(batch), provider=self.provider)

            vectors = await embed_in_order(
                texts,
                provider=self.provider,
                token_budget=self.batch_token_budget,
                max_inputs=OPENAI_MAX_INPUTS_PER_REQUEST,
                send=send,
            )
        data = [EmbeddingData(embedding=vector, index=index) for index, vector in enumerate(vectors)]
        return EmbeddingResponse(data=data, model=response_model, provider=self.provider, dimensions=dimensions, usage=usage)

# --- WAVE-142: bounded retry for the embedding HTTP request -------------------
# A single dropped TCP connect ended a 31,000-document run (WAVE-140: nine
# attempts, eight replays, five fatal errors in 13,272 calls across two classes -
# httpx.ConnectError and httpx.ReadTimeout). This retries the request, nothing else.
#
# Deliberately narrow. It wraps ONLY `client.post`, not the surrounding `send`
# closure, because `send` also calls `accumulate_embedding_usage` and parses the
# body: retrying across those would double-count usage. Applied at one call site,
# the Voyage provider, because that is the only provider with observed failures.
#
# A 400 token-cap rejection reaches the caller untouched so `embed_in_order` can
# bisect; it is not a transport failure and is never retried.
#
# OWNER DECISION 2026-09-12 on a ReadTimeout (F6): a read timeout means the request
# may already have been processed and billed upstream, so retrying it can double-bill
# at the vendor. We retry it anyway, at most `embedding_max_timeout_retries` times
# per batch, and log each at WARNING as `possible_double_bill` with the batch id and
# token count so spend stays auditable. Rationale, verbatim: "a dead 31k run costs
# more than one re-billed batch."

RETRYABLE_TRANSPORT_ERRORS = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteTimeout,
    httpx.PoolTimeout,
    httpx.ReadError,
    httpx.WriteError,
    httpx.RemoteProtocolError,
)

# a ReadTimeout is the subset that may already have been billed upstream
POSSIBLE_DOUBLE_BILL_ERRORS = (httpx.ReadTimeout,)


class EmbeddingRetryExhausted(Exception):
    """One failure shape for an exhausted retry, transport or status alike (F4).

    Carries the last status and body snippet when the final attempt was an HTTP
    failure; chains the transport error as __cause__ when it was a transport one.
    """

    def __init__(self, provider: str, attempts: int, cause: str,
                 status_code: int | None = None, body_snippet: str | None = None):
        self.provider = provider
        self.attempts = attempts
        self.status_code = status_code
        self.body_snippet = body_snippet
        super().__init__(
            f'{provider} embedding request failed after {attempts} attempt(s): {cause}'
            + (f' (HTTP {status_code}: {body_snippet})' if status_code is not None else '')
        )


def _is_retryable_status(status_code: int) -> bool:
    """429 and 5xx only. Every other 4xx is the caller's to handle."""
    return status_code == 429 or 500 <= status_code <= 599


def _parse_retry_after(value: str | None, now: float) -> float | None:
    """Seconds, or an HTTP-date. Returns None when absent or unparseable (F5)."""
    if not value:
        return None
    raw = value.strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        return None
    if when is None:
        return None
    try:
        return max(0.0, when.timestamp() - now)
    except (OverflowError, OSError, ValueError):
        return None


def _body_snippet(response: Any, limit: int = 200) -> str:
    try:
        return (response.text or '')[:limit]
    except Exception:  # noqa: BLE001 - a snippet is best-effort diagnostics
        return ''


async def post_embedding_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str],
    json_payload: dict[str, Any],
    provider: str,
    batch_id: str = 'unknown',
    batch_tokens: int | None = None,
    max_attempts: int | None = None,
    backoff_sec: float | None = None,
    deadline_sec: float | None = None,
    max_timeout_retries: int | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
    jitter: Callable[[float], float] | None = None,
    clock: Callable[[], float] | None = None,
) -> httpx.Response:
    """POST an embedding request, retrying transport failures, 429 and 5xx.

    Bounded three ways: attempt count, a wall-clock deadline measured from the
    first attempt and covering request time as well as sleep (F2), and a separate
    cap on read-timeout retries because those may already have been billed (F6).

    Exhausting any bound raises EmbeddingRetryExhausted, the same shape for a
    transport failure and for a persistent 429/5xx alike (F4).
    """
    settings = get_settings()
    attempts = max(1, int(max_attempts if max_attempts is not None else settings.embedding_max_attempts))
    base = backoff_sec if backoff_sec is not None else settings.embedding_retry_backoff_sec
    deadline = deadline_sec if deadline_sec is not None else settings.embedding_retry_deadline_sec
    timeout_cap = (max_timeout_retries if max_timeout_retries is not None
                   else settings.embedding_max_timeout_retries)
    do_sleep = sleep or asyncio.sleep
    # full jitter: uniform in [0, delay]; keeps concurrent callers from re-colliding
    pick = jitter or (lambda ceiling: random.uniform(0, ceiling))
    now = clock or time.monotonic

    started = now()
    timeout_retries = 0
    last_cause = 'no attempt made'
    last_error: BaseException | None = None
    last_status: int | None = None
    last_body: str | None = None

    for attempt in range(1, attempts + 1):
        retry_after: float | None = None
        try:
            response = await client.post(url, headers=headers, json=json_payload)
            if not _is_retryable_status(response.status_code):
                return response
            last_status = response.status_code
            last_body = _body_snippet(response)
            last_cause = f'HTTP {response.status_code}'
            last_error = None
            if response.status_code == 429:
                retry_after = _parse_retry_after(
                    getattr(response, 'headers', {}).get('Retry-After'), now())
        except RETRYABLE_TRANSPORT_ERRORS as exc:
            last_cause = f'{type(exc).__name__}: {exc}'
            last_error = exc
            last_status = None
            last_body = None
            if isinstance(exc, POSSIBLE_DOUBLE_BILL_ERRORS):
                timeout_retries += 1
                if timeout_retries > timeout_cap:
                    logger.warning(
                        'embedding request to %s exhausted its read-timeout allowance '
                        '(%d) on batch %s; giving up', provider, timeout_cap, batch_id)
                    raise EmbeddingRetryExhausted(
                        provider, attempt, last_cause, last_status, last_body) from exc
                logger.warning(
                    'possible_double_bill: retrying a read timeout for %s batch=%s '
                    'tokens=%s timeout_retry=%d/%d - the upstream request may already '
                    'have been processed and billed',
                    provider, batch_id, batch_tokens, timeout_retries, timeout_cap)

        if attempt >= attempts:
            logger.warning('embedding request to %s failed after %d/%d attempts (%s); giving up',
                           provider, attempt, attempts, last_cause)
            raise EmbeddingRetryExhausted(
                provider, attempt, last_cause, last_status, last_body) from last_error

        remaining = deadline - (now() - started)
        if remaining <= 0:
            logger.warning(
                'embedding request to %s failed on attempt %d/%d (%s); retry deadline '
                '%.1fs reached, giving up', provider, attempt, attempts, last_cause, deadline)
            raise EmbeddingRetryExhausted(
                provider, attempt, last_cause, last_status, last_body) from last_error

        # Retry-After wins over the computed backoff when the server supplied one (F5).
        delay = retry_after if retry_after is not None else pick(base * (2 ** (attempt - 1)))
        # clamp to what is left rather than abandoning the attempt (F3)
        delay = min(delay, remaining)
        logger.warning('embedding request to %s failed on attempt %d/%d (%s); retrying in %.2fs',
                       provider, attempt, attempts, last_cause, delay)
        await do_sleep(delay)

    raise AssertionError('unreachable')  # pragma: no cover


class VoyageEmbeddingProvider:
    provider = 'voyage'
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    async def embed(self, texts: list[str], model: str, dimensions: int, input_type: str | None = None) -> EmbeddingResponse:
        api_key = self.api_key or get_settings().voyage_api_key
        if not api_key:
            raise ProviderConfigurationError("voyage embedding provider requires VOYAGE_API_KEY")
        if not texts:
            return EmbeddingResponse(data=[], model=model, provider=self.provider, dimensions=dimensions, usage={})
        usage: dict[str, int] = {}
        async with httpx.AsyncClient(timeout=120) as client:
            async def send(batch: list[str]) -> list[list[float]]:
                payload: dict[str, Any] = {'model': model, 'input': batch, 'output_dimension': dimensions}
                if input_type:
                    payload['input_type'] = input_type
                # a stable, non-secret id for this exact batch, so a
                # possible_double_bill log line can be reconciled against spend
                batch_id = hashlib.sha256(
                    '\x00'.join(batch).encode('utf-8')).hexdigest()[:16]
                resp = await post_embedding_with_retry(
                    client,
                    'https://api.voyageai.com/v1/embeddings',
                    headers={'Authorization': f'Bearer {api_key}'},
                    json_payload=payload,
                    provider=self.provider,
                    batch_id=batch_id,
                    batch_tokens=sum(estimate_embedding_tokens(text) for text in batch),
                )
                if resp.status_code == 400 and _is_token_cap_rejection(resp):
                    raise _EmbeddingRequestTooLarge()
                resp.raise_for_status()
                body = resp.json()
                accumulate_embedding_usage(usage, body.get('usage'))
                return ordered_batch_vectors(body.get('data', []), expected=len(batch), provider=self.provider)

            vectors = await embed_in_order(
                texts,
                provider=self.provider,
                token_budget=VOYAGE_MAX_TOKENS_PER_REQUEST,
                max_inputs=VOYAGE_MAX_INPUTS_PER_REQUEST,
                send=send,
            )
        data = [EmbeddingData(embedding=vector, index=index) for index, vector in enumerate(vectors)]
        return EmbeddingResponse(data=data, model=model, provider=self.provider, dimensions=dimensions, usage=usage)

class CohereEmbeddingProvider:
    provider = 'cohere'
    def __init__(self, api_key: str | None = None):
        self.api_key = api_key

    async def embed(self, texts: list[str], model: str, dimensions: int, input_type: str | None = None) -> EmbeddingResponse:
        api_key = self.api_key or get_settings().cohere_api_key
        if not api_key:
            raise ProviderConfigurationError("cohere embedding provider requires COHERE_API_KEY")
        if not texts:
            return EmbeddingResponse(data=[], model=model, provider=self.provider, dimensions=dimensions, usage={})
        cohere_input_type = 'search_query' if input_type == 'query' else 'search_document'
        usage: dict[str, int] = {}
        async with httpx.AsyncClient(timeout=120) as client:
            async def send(batch: list[str]) -> list[list[float]]:
                resp = await client.post(
                    'https://api.cohere.com/v2/embed',
                    headers={'Authorization': f'Bearer {api_key}'},
                    json={'model': model, 'texts': batch, 'input_type': cohere_input_type, 'embedding_types': ['float']},
                )
                if resp.status_code == 400 and _is_token_cap_rejection(resp):
                    raise _EmbeddingRequestTooLarge()
                resp.raise_for_status()
                body = resp.json()
                accumulate_embedding_usage(usage, body.get('meta', {}).get('billed_units'))
                raw = body.get('embeddings', {}).get('float') or body.get('embeddings') or []
                return ordered_batch_vectors(raw, expected=len(batch), provider=self.provider)

            vectors = await embed_in_order(
                texts,
                provider=self.provider,
                token_budget=DEFAULT_EMBEDDING_BATCH_TOKEN_BUDGET,
                max_inputs=COHERE_MAX_INPUTS_PER_REQUEST,
                send=send,
            )
        data = [EmbeddingData(embedding=vector[:dimensions], index=index) for index, vector in enumerate(vectors)]
        return EmbeddingResponse(data=data, model=model, provider=self.provider, dimensions=dimensions, usage=usage)

RUNPOD_PROVIDERS = {"runpod", "runpod_serverless", "runpod_serverless_or_local"}
OPENAI_COMPATIBLE_PROVIDERS = {"tei", "huggingface_tei", "infinity", "jina", "self_hosted", "openai_compatible_private"}


def _headers(api_key: str | None) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _endpoint_url(base_url: str, path: str | None) -> str:
    base = base_url.rstrip("/")
    if not path:
        return base
    normalized_path = path.strip("/")
    if base.endswith(f"/{normalized_path}"):
        return base
    return f"{base}/{normalized_path}"


def _unwrap_endpoint_body(body: Any) -> Any:
    if isinstance(body, dict) and isinstance(body.get("output"), (dict, list)):
        return body["output"]
    return body


def _embedding_payload(provider: str, texts: list[str], model: str, dimensions: int, input_type: str | None) -> dict[str, Any]:
    options: dict[str, Any] = {"dimensions": dimensions}
    if input_type:
        options["inputType"] = input_type
    if provider in RUNPOD_PROVIDERS:
        return {
            "input": {
                "operation": "embeddings",
                "model": model,
                "input": texts,
                "options": options,
            }
        }
    payload: dict[str, Any] = {"model": model, "input": texts, "dimensions": dimensions}
    if input_type:
        payload["input_type"] = input_type
    return payload


def _normalize_embedding_data(body: Any, *, dimensions: int) -> list[EmbeddingData]:
    body = _unwrap_endpoint_body(body)
    if isinstance(body, list):
        return [EmbeddingData(embedding=list(vector)[:dimensions], index=i) for i, vector in enumerate(body)]
    if not isinstance(body, dict):
        raise ProviderConfigurationError("private embedding endpoint returned an unsupported response")
    if "data" in body:
        data: list[EmbeddingData] = []
        for i, item in enumerate(body.get("data") or []):
            if isinstance(item, dict):
                data.append(EmbeddingData(embedding=list(item["embedding"])[:dimensions], index=int(item.get("index", i))))
            else:
                data.append(EmbeddingData(embedding=list(item)[:dimensions], index=i))
        return data
    vectors = body.get("embeddings") or body.get("vectors") or []
    return [EmbeddingData(embedding=list(vector)[:dimensions], index=i) for i, vector in enumerate(vectors)]


def _rerank_payload(provider: str, query: str, documents: list[str], model: str, top_n: int | None) -> dict[str, Any]:
    if provider in RUNPOD_PROVIDERS:
        return {
            "input": {
                "operation": "rerank",
                "model": model,
                "query": query,
                "documents": documents,
                "options": {"topN": top_n},
            }
        }
    payload: dict[str, Any] = {"model": model, "query": query, "documents": documents}
    if top_n is not None:
        payload["top_n"] = top_n
    return payload


def _normalize_rerank_results(body: Any, *, documents_count: int, top_n: int | None) -> list[RerankResult]:
    body = _unwrap_endpoint_body(body)
    raw_results: Any
    if isinstance(body, list):
        raw_results = body
    elif isinstance(body, dict):
        raw_results = body.get("results") or body.get("data") or body.get("rerank") or body.get("scores") or []
    else:
        raise ProviderConfigurationError("private rerank endpoint returned an unsupported response")

    results: list[RerankResult] = []
    for i, item in enumerate(raw_results):
        if isinstance(item, dict):
            index = int(item.get("index", item.get("document_index", i)))
            score = float(item.get("relevance_score", item.get("score", item.get("similarity", 0.0))))
        else:
            index = i
            score = float(item)
        if 0 <= index < documents_count:
            results.append(RerankResult(index=index, relevance_score=score))
    results.sort(key=lambda result: result.relevance_score, reverse=True)
    if top_n:
        results = results[:top_n]
    return results


class GenericEndpointEmbeddingProvider:
    def __init__(
        self,
        provider: str,
        endpoint_url: str,
        api_key: str | None = None,
        *,
        health_status: str = "unknown",
        embedding_path: str | None = None,
    ):
        if not endpoint_url:
            raise ProviderConfigurationError(f"{provider} embedding provider requires an endpoint URL")
        self.provider = provider.strip().lower()
        self.endpoint_url = endpoint_url.rstrip("/")
        self.api_key = api_key
        self.health_status = normalize_health_status(health_status)
        self.embedding_path = embedding_path

    async def embed(self, texts: list[str], model: str, dimensions: int, input_type: str | None = None) -> EmbeddingResponse:
        if not health_allows_routing(self.health_status):
            raise ProviderConfigurationError(f"{self.provider} embedding endpoint health is {self.health_status}; routing disabled")
        # NOT batched. This adapter fronts TEI / Infinity / RunPod / self-hosted
        # endpoints whose per-request caps are deployment-specific and unknown
        # here, so imposing a batch size could only be a guess. The request shape
        # is left exactly as deployed; the ordering and count guards this module
        # applies to the vendor providers should be extended here once a real
        # endpoint's limits are measured. See WAVE-131.
        path = None if self.provider in RUNPOD_PROVIDERS else (self.embedding_path or "embeddings")
        payload = _embedding_payload(self.provider, texts, model, dimensions, input_type)
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(_endpoint_url(self.endpoint_url, path), headers=_headers(self.api_key), json=payload)
            resp.raise_for_status()
            body = _unwrap_endpoint_body(resp.json())
        data = _normalize_embedding_data(body, dimensions=dimensions)
        response_model = body.get("model", model) if isinstance(body, dict) else model
        usage = body.get("usage", {}) if isinstance(body, dict) else {}
        return EmbeddingResponse(data=data, model=response_model, provider=self.provider, dimensions=dimensions, usage=usage)


class GenericEndpointRerankProvider:
    def __init__(
        self,
        provider: str,
        endpoint_url: str,
        api_key: str | None = None,
        *,
        health_status: str = "unknown",
        rerank_path: str | None = None,
    ):
        if not endpoint_url:
            raise ProviderConfigurationError(f"{provider} rerank provider requires an endpoint URL")
        self.provider = provider.strip().lower()
        self.endpoint_url = endpoint_url.rstrip("/")
        self.api_key = api_key
        self.health_status = normalize_health_status(health_status)
        self.rerank_path = rerank_path

    async def rerank(self, query: str, documents: list[str], model: str, top_n: int | None = None) -> RerankResponse:
        if not health_allows_routing(self.health_status):
            raise ProviderConfigurationError(f"{self.provider} rerank endpoint health is {self.health_status}; routing disabled")
        path = None if self.provider in RUNPOD_PROVIDERS else (self.rerank_path or "rerank")
        payload = _rerank_payload(self.provider, query, documents, model, top_n)
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(_endpoint_url(self.endpoint_url, path), headers=_headers(self.api_key), json=payload)
            resp.raise_for_status()
            body = _unwrap_endpoint_body(resp.json())
        results = _normalize_rerank_results(body, documents_count=len(documents), top_n=top_n)
        response_model = body.get("model", model) if isinstance(body, dict) else model
        return RerankResponse(results=results, model=response_model, provider=self.provider)

def provider_for(provider_name: str, settings: Any | None = None) -> EmbeddingProvider:
    s = settings or get_settings()
    provider = (provider_name or "").strip().lower()
    status = provider_config_status(provider, s)
    if provider == 'hash_mock':
        return HashEmbeddingProvider()
    if not status.configured:
        raise ProviderConfigurationError(status.reason or f"{provider} embedding provider is not configured")
    if provider == 'openai':
        return OpenAIEmbeddingProvider(_setting(s, 'openai_api_key'))
    if provider == 'voyage':
        return VoyageEmbeddingProvider(_setting(s, 'voyage_api_key'))
    if provider == 'cohere':
        return CohereEmbeddingProvider(_setting(s, 'cohere_api_key'))
    if provider in {'jina', 'tei', 'huggingface_tei'}:
        return GenericEndpointEmbeddingProvider(provider, _setting(s, 'tei_endpoint_url') or '')
    if provider in RUNPOD_PROVIDERS:
        return GenericEndpointEmbeddingProvider('runpod', _setting(s, 'runpod_embedding_endpoint_url') or '', _setting(s, 'runpod_api_key'))
    if provider == 'infinity':
        return GenericEndpointEmbeddingProvider('infinity', _setting(s, 'infinity_endpoint_url') or '')
    if provider in {"self_hosted", "openai_compatible_private"}:
        return GenericEndpointEmbeddingProvider(provider, _setting(s, "self_hosted_model_endpoint_url") or '', _setting(s, "self_hosted_model_api_key"))
    raise ProviderConfigurationError(f"unknown embedding provider: {provider_name}")


def provider_for_rerank(provider_name: str, settings: Any | None = None) -> RerankProvider:
    s = settings or get_settings()
    provider = (provider_name or "").strip().lower()
    status = provider_config_status(provider, s)
    if not status.configured:
        raise ProviderConfigurationError(status.reason or f"{provider} rerank provider is not configured")
    if provider in {'jina', 'tei', 'huggingface_tei'}:
        return GenericEndpointRerankProvider(provider, _setting(s, 'tei_endpoint_url') or '')
    if provider in RUNPOD_PROVIDERS:
        return GenericEndpointRerankProvider('runpod', _setting(s, 'runpod_embedding_endpoint_url') or '', _setting(s, 'runpod_api_key'))
    if provider == 'infinity':
        return GenericEndpointRerankProvider('infinity', _setting(s, 'infinity_endpoint_url') or '')
    if provider in {"self_hosted", "openai_compatible_private"}:
        return GenericEndpointRerankProvider(provider, _setting(s, "self_hosted_model_endpoint_url") or '', _setting(s, "self_hosted_model_api_key"))
    raise ProviderConfigurationError(f"unknown rerank provider: {provider_name}")


def chat_provider_config_status(provider_name: str, settings: Any | None = None) -> ProviderConfigStatus:
    """Report chat configuration without changing embedding/rerank status rules."""

    provider = (provider_name or "").strip().lower()
    s = settings or get_settings()
    if provider == "fixture":
        if bool(getattr(s, "is_local_env", False)):
            return ProviderConfigStatus(provider=provider, configured=True)
        return ProviderConfigStatus(
            provider=provider,
            configured=False,
            reason="fixture chat provider is restricted to local/dev/test/ci",
        )
    if provider == "openai":
        return _status(
            provider,
            ("OPENAI_API_KEY",),
            bool(_setting(s, "openai_api_key")),
            reason="openai chat provider requires OPENAI_API_KEY",
        )
    if provider == "anthropic":
        return _status(
            provider,
            ("ANTHROPIC_API_KEY",),
            bool(_setting(s, "anthropic_api_key")),
            reason="anthropic chat provider requires ANTHROPIC_API_KEY",
        )
    if provider in {"self_hosted", "openai_compatible_private"}:
        return _status(
            provider,
            ("SELF_HOSTED_MODEL_ENDPOINT_URL",),
            bool(_setting(s, "self_hosted_model_endpoint_url")),
            reason=f"{provider} chat provider requires SELF_HOSTED_MODEL_ENDPOINT_URL",
            auth_secret_ref=(
                "envref://SELF_HOSTED_MODEL_API_KEY"
                if _setting(s, "self_hosted_model_api_key")
                else None
            ),
        )
    return ProviderConfigStatus(
        provider=provider or "unknown",
        configured=False,
        reason=f"unknown chat provider: {provider_name}",
    )


def _chat_usage(body: Any) -> dict[str, int]:
    usage = body if isinstance(body, dict) else {}
    input_tokens = int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
    output_tokens = int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)
    total_tokens = int(usage.get("total_tokens", input_tokens + output_tokens) or 0)
    return {
        "input_tokens": max(0, input_tokens),
        "output_tokens": max(0, output_tokens),
        "total_tokens": max(0, total_tokens),
    }


class FixtureChatProvider:
    provider = "fixture"

    async def complete(
        self,
        messages: list[ExpertChatMessage],
        model: str,
        *,
        max_output_tokens: int,
        temperature: float,
    ) -> ChatProviderResult:
        canonical = json.dumps(
            [message.model_dump(mode="json") for message in messages],
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
        last_user = next((message.content for message in reversed(messages) if message.role == "user"), "")
        content = f"[fixture:{digest}] {last_user}".strip()
        input_tokens = sum(len(message.content.split()) for message in messages)
        output_tokens = len(content.split())
        return ChatProviderResult(
            content=content,
            model=model,
            usage={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            },
            finish_reason="stop",
        )


class OpenAICompatibleChatProvider:
    def __init__(
        self,
        provider: str,
        endpoint_url: str,
        api_key: str | None = None,
        *,
        timeout_seconds: float = 120.0,
    ):
        if not endpoint_url:
            raise ProviderConfigurationError(f"{provider} chat provider requires an endpoint URL")
        self.provider = provider.strip().lower()
        self.endpoint_url = endpoint_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    async def complete(
        self,
        messages: list[ExpertChatMessage],
        model: str,
        *,
        max_output_tokens: int,
        temperature: float,
    ) -> ChatProviderResult:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [message.model_dump(mode="json") for message in messages],
        }
        if self.provider == "openai" and model.strip().lower().startswith("gpt-5"):
            payload["max_completion_tokens"] = max_output_tokens
        else:
            payload["max_tokens"] = max_output_tokens
            payload["temperature"] = temperature
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                _endpoint_url(self.endpoint_url, "chat/completions"),
                headers=_headers(self.api_key),
                json=payload,
            )
            response.raise_for_status()
        try:
            body = response.json()
        except (TypeError, ValueError) as exc:
            raise ProviderConfigurationError(
                f"{self.provider} chat provider returned an unsupported response"
            ) from exc
        try:
            if not isinstance(body, dict):
                raise TypeError("chat response must be an object")
            choice = body["choices"][0]
            content = choice["message"]["content"]
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise ProviderConfigurationError(
                f"{self.provider} chat provider returned an unsupported response"
            ) from exc
        if not isinstance(content, str) or not content.strip():
            raise ProviderConfigurationError(f"{self.provider} chat provider returned empty content")
        try:
            usage = _chat_usage(body.get("usage"))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ProviderConfigurationError(
                f"{self.provider} chat provider returned unsupported usage metadata"
            ) from exc
        return ChatProviderResult(
            content=content,
            model=str(body.get("model") or model),
            usage=usage,
            finish_reason=(str(choice.get("finish_reason")) if choice.get("finish_reason") is not None else None),
        )


class AnthropicChatProvider:
    provider = "anthropic"

    def __init__(self, api_key: str, *, timeout_seconds: float = 120.0):
        if not api_key.strip():
            raise ProviderConfigurationError("anthropic chat provider requires ANTHROPIC_API_KEY")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    async def complete(
        self,
        messages: list[ExpertChatMessage],
        model: str,
        *,
        max_output_tokens: int,
        temperature: float,
    ) -> ChatProviderResult:
        del temperature  # Claude Sonnet 5 rejects this deprecated parameter.
        system = "\n\n".join(message.content for message in messages if message.role == "system")
        provider_messages = [
            message.model_dump(mode="json")
            for message in messages
            if message.role in {"user", "assistant"}
        ]
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_output_tokens,
            "messages": provider_messages,
        }
        if system:
            payload["system"] = system
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
        try:
            body = response.json()
        except (TypeError, ValueError) as exc:
            raise ProviderConfigurationError("anthropic chat provider returned an unsupported response") from exc
        try:
            if not isinstance(body, dict):
                raise TypeError("chat response must be an object")
            blocks = body["content"]
            content = "".join(
                str(block.get("text") or "")
                for block in blocks
                if isinstance(block, dict) and block.get("type") == "text"
            )
            usage_body = body.get("usage") or {}
            usage = _chat_usage({
                "input_tokens": usage_body.get("input_tokens", 0),
                "output_tokens": usage_body.get("output_tokens", 0),
            })
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ProviderConfigurationError("anthropic chat provider returned an unsupported response") from exc
        if not content.strip():
            raise ProviderConfigurationError("anthropic chat provider returned empty content")
        return ChatProviderResult(
            content=content,
            model=str(body.get("model") or model),
            usage=usage,
            finish_reason=(str(body.get("stop_reason")) if body.get("stop_reason") is not None else None),
        )


def chat_provider_for(provider_name: str, settings: Any | None = None) -> ChatProvider:
    s = settings or get_settings()
    provider = (provider_name or "").strip().lower()
    status = chat_provider_config_status(provider, s)
    if provider == "fixture":
        if not status.configured:
            raise ProviderConfigurationError(status.reason or "fixture chat provider is not configured")
        return FixtureChatProvider()
    if not status.configured:
        raise ProviderConfigurationError(status.reason or f"{provider} chat provider is not configured")
    timeout_seconds = float(getattr(s, "expert_chat_timeout_sec", 120.0) or 120.0)
    if provider == "openai":
        return OpenAICompatibleChatProvider(
            provider,
            "https://api.openai.com/v1",
            _setting(s, "openai_api_key"),
            timeout_seconds=timeout_seconds,
        )
    if provider == "anthropic":
        return AnthropicChatProvider(
            _setting(s, "anthropic_api_key") or "",
            timeout_seconds=timeout_seconds,
        )
    if provider in {"self_hosted", "openai_compatible_private"}:
        return OpenAICompatibleChatProvider(
            provider,
            _setting(s, "self_hosted_model_endpoint_url") or "",
            _setting(s, "self_hosted_model_api_key"),
            timeout_seconds=timeout_seconds,
        )
    raise ProviderConfigurationError(f"unknown chat provider: {provider_name}")
