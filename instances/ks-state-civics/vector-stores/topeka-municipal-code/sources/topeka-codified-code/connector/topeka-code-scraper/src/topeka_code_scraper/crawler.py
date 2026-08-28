from __future__ import annotations

import asyncio
from collections import deque
from datetime import UTC, datetime
import json
from pathlib import Path

from .fetcher import FetchResult, HttpFetcher, PlaywrightFetcher
from .graph import GraphBuilder
from .models import CrawlReport, ParsedPage
from .normalize import BASE_URL, canonicalize_url, sha256_text
from .parser import MunicipalCodeParser
from .url_manifest import UrlManifestEntry


class MunicipalCodeCrawler:
    def __init__(
        self,
        *,
        root_url: str = f"{BASE_URL}/TMC",
        delay_seconds: float = 0.75,
        retries: int = 4,
        timeout_seconds: float = 30.0,
        max_pages: int | None = None,
        archive_raw: bool = False,
        archive_network: bool = False,
        raw_dir: Path | None = None,
        network_dir: Path | None = None,
        user_agent: str = "TopekaCodeScraper/0.1 (public municipal-code indexing)",
        fetcher: str = "http",
        render_wait_ms: int = 1500,
        isolate_playwright_context: bool = False,
        seed_urls: list[str] | None = None,
        page_hints: dict[str, UrlManifestEntry] | None = None,
        follow_links: bool = True,
    ) -> None:
        canonical = canonicalize_url(root_url)
        if not canonical:
            raise ValueError("root_url must be under https://topeka.municipal.codes/TMC")
        self.root_url = canonical
        self.delay_seconds = delay_seconds
        self.retries = retries
        self.timeout_seconds = timeout_seconds
        self.max_pages = max_pages
        self.archive_raw = archive_raw
        self.archive_network = archive_network
        self.raw_dir = raw_dir
        self.network_dir = network_dir
        self.user_agent = user_agent
        self.fetcher = fetcher
        self.render_wait_ms = render_wait_ms
        self.isolate_playwright_context = isolate_playwright_context
        self.seed_urls = [url for url in (canonicalize_url(item) for item in (seed_urls or [])) if url]
        self.page_hints = page_hints or {}
        self.follow_links = follow_links
        self.parser = MunicipalCodeParser()

    async def crawl(self) -> tuple[list[ParsedPage], list, list, CrawlReport]:
        started = datetime.now(UTC)
        start_urls = self.seed_urls or [self.root_url]
        queue: deque[str] = deque(start_urls)
        queued = set(start_urls)
        seen: set[str] = set()
        pages: list[ParsedPage] = []
        failures: list[dict[str, str]] = []

        async with self._build_fetcher() as fetcher:
            while queue:
                if self.max_pages is not None and len(seen) >= self.max_pages:
                    break
                url = queue.popleft()
                if url in seen:
                    continue
                seen.add(url)
                try:
                    fetched = await fetcher.fetch(url)
                    fetched_url = canonicalize_url(fetched.url) or url
                    hint = self.page_hints.get(fetched_url)
                    page = self.parser.parse(
                        fetched.url,
                        fetched.html,
                        fetched.retrieved_at,
                        forced_page_type=hint.parser_page_type if hint else None,
                        forced_citation=hint.citation if hint else None,
                        forced_title=hint.name if hint else None,
                    )
                    pages.append(page)
                    if self.archive_raw:
                        self._archive_html(page, fetched)
                    if self.archive_network:
                        self._archive_network(page, fetched)
                    if self.follow_links:
                        for link in page.internal_links:
                            if link not in seen and link not in queued:
                                queued.add(link)
                                queue.append(link)
                except Exception as exc:  # keep crawl resumable and report individual failures
                    failures.append({"url": url, "error": f"{type(exc).__name__}: {exc}"})

        nodes, edges = GraphBuilder().build(pages)
        finished = datetime.now(UTC)
        report = CrawlReport(
            started_at=started,
            finished_at=finished,
            root_url=self.root_url,
            pages_seen=len(seen),
            pages_fetched=len(pages),
            pages_failed=len(failures),
            section_count=sum(1 for p in pages if p.section),
            definition_count=sum(len(p.definitions) for p in pages),
            node_count=len(nodes),
            edge_count=len(edges),
            failures=failures,
            fetcher=self.fetcher,
        )
        return pages, nodes, edges, report

    def _build_fetcher(self) -> HttpFetcher | PlaywrightFetcher:
        if self.fetcher == "http":
            return HttpFetcher(
                delay_seconds=self.delay_seconds,
                timeout_seconds=self.timeout_seconds,
                retries=self.retries,
                user_agent=self.user_agent,
            )
        if self.fetcher == "playwright":
            return PlaywrightFetcher(
                delay_seconds=self.delay_seconds,
                timeout_seconds=self.timeout_seconds,
                retries=self.retries,
                user_agent=self.user_agent,
                render_wait_ms=self.render_wait_ms,
                isolate_context=self.isolate_playwright_context,
            )
        raise ValueError(f"Unsupported fetcher: {self.fetcher}")

    def _archive_html(self, page: ParsedPage, fetched: FetchResult) -> None:
        raw_dir = self.raw_dir or Path("raw")
        raw_dir.mkdir(parents=True, exist_ok=True)
        name = page.path.removeprefix("/TMC").strip("/") or "TMC"
        safe = name.replace("/", "__")
        path = raw_dir / f"{safe}.{sha256_text(fetched.html)[:12]}.html"
        path.write_text(fetched.html, encoding="utf-8")

    def _archive_network(self, page: ParsedPage, fetched: FetchResult) -> None:
        network_dir = self.network_dir or Path("network")
        network_dir.mkdir(parents=True, exist_ok=True)
        name = page.path.removeprefix("/TMC").strip("/") or "TMC"
        safe = name.replace("/", "__")
        path = network_dir / f"{safe}.{sha256_text(fetched.url)[:12]}.network.json"
        payload = {
            "url": fetched.url,
            "status_code": fetched.status_code,
            "retrieved_at": fetched.retrieved_at.isoformat(),
            "headers": fetched.headers or {},
            "events": fetched.network_events or [],
        }
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
