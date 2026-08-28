from __future__ import annotations

import asyncio
import os
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx


@dataclass(slots=True)
class FetchResult:
    url: str
    html: str
    status_code: int
    retrieved_at: datetime
    headers: dict[str, str] | None = None
    network_events: list[dict[str, Any]] | None = None


class PoliteRateLimiter:
    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = max(0.0, delay_seconds)
        self._lock = asyncio.Lock()
        self._next_allowed = 0.0

    async def wait(self) -> None:
        loop = asyncio.get_running_loop()
        async with self._lock:
            now = loop.time()
            if now < self._next_allowed:
                await asyncio.sleep(self._next_allowed - now)
            self._next_allowed = loop.time() + self.delay_seconds


class HttpFetcher:
    RETRYABLE = {408, 425, 429, 500, 502, 503, 504}

    def __init__(
        self,
        *,
        delay_seconds: float = 0.75,
        timeout_seconds: float = 30.0,
        retries: int = 4,
        user_agent: str = "TopekaCodeScraper/0.1 (public municipal-code indexing)",
    ) -> None:
        self.retries = max(0, retries)
        self.rate_limiter = PoliteRateLimiter(delay_seconds)
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=True,
            headers={
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.8",
            },
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
        )

    async def __aenter__(self) -> "HttpFetcher":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.client.aclose()

    async def fetch(self, url: str) -> FetchResult:
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            await self.rate_limiter.wait()
            try:
                response = await self.client.get(url)
                if response.status_code == 200:
                    return FetchResult(
                        url=str(response.url),
                        html=response.text,
                        status_code=response.status_code,
                        retrieved_at=datetime.now(UTC),
                        headers=dict(response.headers),
                    )
                if response.status_code not in self.RETRYABLE:
                    response.raise_for_status()
                delay = self._retry_delay(response, attempt)
                await asyncio.sleep(delay)
            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    raise
                await asyncio.sleep(min(30.0, (2**attempt) + random.random()))
        raise RuntimeError(f"Failed to fetch {url}") from last_error

    def _retry_delay(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("retry-after")
        if retry_after:
            try:
                return min(60.0, float(retry_after))
            except ValueError:
                try:
                    dt = parsedate_to_datetime(retry_after)
                    seconds = (dt - datetime.now(dt.tzinfo or UTC)).total_seconds()
                    return max(0.0, min(60.0, seconds))
                except Exception:
                    pass
        return min(30.0, (2**attempt) + random.random())


class PlaywrightFetcher:
    RETRYABLE = {408, 425, 429, 500, 502, 503, 504}

    def __init__(
        self,
        *,
        delay_seconds: float = 0.75,
        timeout_seconds: float = 30.0,
        retries: int = 4,
        user_agent: str = "TopekaCodeScraper/0.1 (public municipal-code indexing)",
        render_wait_ms: int = 1500,
        headless: bool = True,
        isolate_context: bool = False,
    ) -> None:
        self.retries = max(0, retries)
        self.rate_limiter = PoliteRateLimiter(delay_seconds)
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent
        self.render_wait_ms = max(0, render_wait_ms)
        self.headless = headless
        self.isolate_context = isolate_context
        self._playwright = None
        self._browser = None
        self._context = None

    async def __aenter__(self) -> "PlaywrightFetcher":
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError("Playwright fetcher requires installing the browser extra: pip install -e '.[browser]'") from exc

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self.headless)
        if not self.isolate_context:
            self._context = await self._new_context()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._context is not None:
            await self._context.close()
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()

    async def fetch(self, url: str) -> FetchResult:
        if self._browser is None:
            raise RuntimeError("PlaywrightFetcher must be used as an async context manager")

        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            await self.rate_limiter.wait()
            context = await self._new_context() if self.isolate_context else self._context
            if context is None:
                raise RuntimeError("PlaywrightFetcher context was not initialized")
            page = await context.new_page()
            network_events: list[dict[str, Any]] = []
            page.on("request", lambda request: network_events.append({
                "event": "request",
                "method": request.method,
                "resource_type": request.resource_type,
                "url": request.url,
            }))
            page.on("response", lambda response: network_events.append({
                "event": "response",
                "status": response.status,
                "resource_type": response.request.resource_type,
                "url": response.url,
                "content_type": response.headers.get("content-type"),
                "cf_mitigated": response.headers.get("cf-mitigated"),
            }))
            try:
                response = await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=int(self.timeout_seconds * 1000),
                )
                if self.render_wait_ms:
                    await page.wait_for_timeout(self.render_wait_ms)
                html = await page.content()
                status_code = response.status if response is not None else 0
                headers = dict(response.headers) if response is not None else {}
                final_url = page.url
                if is_challenge_only_page(status_code, headers, html):
                    raise RuntimeError(f"publisher challenge page returned for {url}")
                if status_code == 200:
                    return FetchResult(
                        url=final_url,
                        html=html,
                        status_code=status_code,
                        retrieved_at=datetime.now(UTC),
                        headers=headers,
                        network_events=network_events,
                    )
                if status_code not in self.RETRYABLE:
                    raise RuntimeError(f"unexpected HTTP {status_code} for {url}")
                await asyncio.sleep(min(30.0, (2**attempt) + random.random()))
            except Exception as exc:
                last_error = exc
                if attempt >= self.retries:
                    raise
                await asyncio.sleep(min(30.0, (2**attempt) + random.random()))
            finally:
                await page.close()
                if self.isolate_context:
                    await context.close()
        raise RuntimeError(f"Failed to fetch {url}") from last_error

    async def _new_context(self):
        if self._browser is None:
            raise RuntimeError("PlaywrightFetcher browser was not initialized")
        return await self._browser.new_context(
            user_agent=self.user_agent,
            locale="en-US",
            service_workers="block",
        )


class DecodoFetcher:
    RETRYABLE = {204, 408, 425, 429, 500, 502, 503, 504}

    def __init__(
        self,
        *,
        delay_seconds: float = 0.75,
        timeout_seconds: float = 30.0,
        retries: int = 4,
        api_token: str | None = None,
        endpoint_url: str | None = None,
        proxy_pool: str | None = None,
        headless: str | None = None,
        geo: str | None = None,
        locale: str | None = None,
        device_type: str | None = None,
        target: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.retries = max(0, retries)
        self.rate_limiter = PoliteRateLimiter(delay_seconds)
        self.api_token = _normalize_decodo_token(api_token or os.getenv("DECODO_API_TOKEN"))
        if not self.api_token:
            raise RuntimeError("Decodo fetcher requires DECODO_API_TOKEN")
        self.endpoint_url = endpoint_url or os.getenv("DECODO_API_ENDPOINT") or "https://scraper-api.decodo.com/v2/scrape"
        self.proxy_pool = _optional_decodo_value(proxy_pool if proxy_pool is not None else os.getenv("DECODO_PROXY_POOL"))
        self.headless = _optional_decodo_value(headless if headless is not None else os.getenv("DECODO_HEADLESS"))
        self.geo = _optional_decodo_value(geo if geo is not None else os.getenv("DECODO_GEO"))
        self.locale = _optional_decodo_value(locale if locale is not None else os.getenv("DECODO_LOCALE"))
        self.device_type = _optional_decodo_value(device_type if device_type is not None else os.getenv("DECODO_DEVICE_TYPE"))
        self.target = (target or os.getenv("DECODO_TARGET") or "universal").strip()
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=True,
            headers={
                "Accept": "application/json",
                "Authorization": f"Basic {self.api_token}",
                "Content-Type": "application/json",
            },
            transport=transport,
        )

    async def __aenter__(self) -> "DecodoFetcher":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.client.aclose()

    async def fetch(self, url: str) -> FetchResult:
        payload = self._payload(url)
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            await self.rate_limiter.wait()
            try:
                response = await self.client.post(self.endpoint_url, json=payload)
                if response.status_code in self.RETRYABLE and attempt < self.retries:
                    await asyncio.sleep(min(30.0, (2**attempt) + random.random()))
                    continue
                if response.status_code != 200:
                    raise RuntimeError(f"Decodo API HTTP {response.status_code} for {url}")
                return self._result_from_response(url, response)
            except (httpx.TimeoutException, httpx.TransportError, ValueError, RuntimeError) as exc:
                last_error = exc
                if attempt >= self.retries:
                    raise
                await asyncio.sleep(min(30.0, (2**attempt) + random.random()))
        raise RuntimeError(f"Failed to fetch {url} through Decodo") from last_error

    def _payload(self, url: str) -> dict[str, str]:
        payload = {
            "url": url,
            "target": self.target,
            "proxy_pool": self.proxy_pool,
            "headless": self.headless,
            "geo": self.geo,
            "locale": self.locale,
            "device_type": self.device_type,
        }
        return {key: value for key, value in payload.items() if value}

    def _result_from_response(self, requested_url: str, response: httpx.Response) -> FetchResult:
        body = response.json()
        results = body.get("results")
        if not isinstance(results, list) or not results:
            if body.get("status") == "failed":
                status_code = body.get("status_code")
                message = body.get("message") or "no message"
                raise RuntimeError(f"Decodo scrape failed status_code={status_code}: {message}")
            raise RuntimeError(f"Decodo API response did not include results for {requested_url}")
        result = results[0]
        if not isinstance(result, dict):
            raise RuntimeError(f"Decodo API result was not an object for {requested_url}")
        content = result.get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError(f"Decodo API returned empty content for {requested_url}")
        target_status = _int_or_default(result.get("status_code"), response.status_code)
        final_url = str(result.get("url") or requested_url)
        headers = {str(key): str(value) for key, value in (result.get("headers") or {}).items()} if isinstance(result.get("headers"), dict) else {}
        if is_challenge_only_page(target_status, headers, content):
            raise RuntimeError(f"publisher challenge page returned for {requested_url}")
        if target_status != 200:
            raise RuntimeError(f"Decodo target HTTP {target_status} for {requested_url}")
        return FetchResult(
            url=final_url,
            html=content,
            status_code=target_status,
            retrieved_at=datetime.now(UTC),
            headers=headers,
            network_events=[
                {
                    "event": "decodo_result",
                    "task_id": result.get("task_id"),
                    "created_at": result.get("created_at"),
                    "updated_at": result.get("updated_at"),
                    "status_code": target_status,
                    "url": final_url,
                    "proxy_pool": self.proxy_pool,
                    "headless": self.headless,
                }
            ],
        )


def has_municipal_code_content(html: str) -> bool:
    lowered = html.lower()
    return (
        "topeka municipal code" in lowered
        and ("href=\"/tmc/" in lowered or "href='/tmc/" in lowered or "/tmc/" in lowered)
        and ("title 18" in lowered or "chapter" in lowered or "sections:" in lowered or "ordinance" in lowered)
    )


def is_challenge_only_page(status_code: int, headers: dict[str, str], html: str) -> bool:
    header_lookup = {key.lower(): value for key, value in headers.items()}
    if header_lookup.get("cf-mitigated", "").lower() == "challenge":
        return True
    lowered = html.lower()
    challenge_markers = any(
        marker in lowered
        for marker in (
            "challenge-platform",
            "challenges.cloudflare.com",
            "cf-browser-verification",
            "cloudflare ray id",
            "just a moment",
            "checking your browser",
            "verify you are human",
            "attention required",
            "access denied",
            "__cf_chl_",
            "cf-chl-",
            "cf-turnstile",
            "captcha",
        )
    )
    if status_code in {403, 503} and challenge_markers:
        return True
    return challenge_markers and not has_municipal_code_content(html)


def _normalize_decodo_token(value: str | None) -> str:
    token = (value or "").strip()
    if token.lower().startswith("basic "):
        return token[6:].strip()
    return token


def _optional_decodo_value(value: str | None) -> str:
    normalized = (value or "").strip()
    if normalized.lower() in {"", "auto", "default", "off", "none", "null"}:
        return ""
    return normalized


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
