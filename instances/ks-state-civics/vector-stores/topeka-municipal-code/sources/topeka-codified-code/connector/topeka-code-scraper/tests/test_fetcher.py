import pytest
import httpx

from topeka_code_scraper.fetcher import DecodoFetcher, has_municipal_code_content, is_challenge_only_page


def test_challenge_only_page_is_blocked():
    html = "<html><script src='/cdn-cgi/challenge-platform/scripts/jsd/main.js'></script></html>"

    assert is_challenge_only_page(403, {"cf-mitigated": "challenge"}, html)
    assert is_challenge_only_page(200, {}, html)


def test_rendered_code_page_with_challenge_script_is_allowed():
    html = """
    <html>
      <body>
        <h1>TOPEKA MUNICIPAL CODE</h1>
        <a href="/TMC/18.55.010">18.55.010</a>
        <p>Chapter 18.55 Definitions</p>
        <script src="/cdn-cgi/challenge-platform/scripts/jsd/main.js"></script>
      </body>
    </html>
    """

    assert has_municipal_code_content(html)
    assert not is_challenge_only_page(200, {}, html)


def test_access_denied_shell_without_code_content_is_blocked():
    html = "<html><title>Attention Required</title><body>Access denied</body></html>"

    assert is_challenge_only_page(403, {}, html)
    assert is_challenge_only_page(200, {}, html)


@pytest.mark.asyncio
async def test_decodo_fetcher_posts_minimal_payload_and_returns_html():
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        seen["payload"] = request.read().decode("utf-8")
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "content": """
                            <html><body>
                              <h1>TOPEKA MUNICIPAL CODE</h1>
                              <a href="/TMC/18.55.010">18.55.010</a>
                              <p>Chapter 18.55 Definitions and ordinance text.</p>
                            </body></html>
                        """,
                        "headers": {"content-type": "text/html"},
                        "status_code": 200,
                        "url": "https://topeka.municipal.codes/TMC/18.55.010",
                        "task_id": "task-1",
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with DecodoFetcher(api_token="Basic token-value", delay_seconds=0, retries=0, transport=transport) as fetcher:
        result = await fetcher.fetch("https://topeka.municipal.codes/TMC/18.55.010")

    assert seen["auth"] == "Basic token-value"
    assert '"target":"universal"' in seen["payload"]
    assert "proxy_pool" not in seen["payload"]
    assert "headless" not in seen["payload"]
    assert result.status_code == 200
    assert result.url == "https://topeka.municipal.codes/TMC/18.55.010"
    assert "TOPEKA MUNICIPAL CODE" in result.html
    assert result.network_events[0]["event"] == "decodo_result"
    assert result.network_events[0]["task_id"] == "task-1"


@pytest.mark.asyncio
async def test_decodo_fetcher_posts_explicit_optional_parameters():
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["payload"] = request.read().decode("utf-8")
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "content": """
                            <html><body>
                              <h1>TOPEKA MUNICIPAL CODE</h1>
                              <a href="/TMC/18.55.010">18.55.010</a>
                              <p>Chapter 18.55 Definitions and ordinance text.</p>
                            </body></html>
                        """,
                        "status_code": 200,
                        "url": "https://topeka.municipal.codes/TMC/18.55.010",
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with DecodoFetcher(
        api_token="token-value",
        delay_seconds=0,
        retries=0,
        proxy_pool="standard",
        headless="html",
        geo="United States",
        locale="en-US",
        device_type="desktop_chrome",
        transport=transport,
    ) as fetcher:
        await fetcher.fetch("https://topeka.municipal.codes/TMC/18.55.010")

    assert '"proxy_pool":"standard"' in seen["payload"]
    assert '"headless":"html"' in seen["payload"]
    assert '"geo":"United States"' in seen["payload"]
    assert '"locale":"en-US"' in seen["payload"]
    assert '"device_type":"desktop_chrome"' in seen["payload"]


@pytest.mark.asyncio
async def test_decodo_fetcher_rejects_challenge_content():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "content": "<html><body>Just a moment... Cloudflare Ray ID abc</body></html>",
                        "status_code": 200,
                        "url": "https://topeka.municipal.codes/TMC/1.10.040",
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with DecodoFetcher(api_token="token-value", delay_seconds=0, retries=0, transport=transport) as fetcher:
        with pytest.raises(RuntimeError, match="publisher challenge page returned"):
            await fetcher.fetch("https://topeka.municipal.codes/TMC/1.10.040")
