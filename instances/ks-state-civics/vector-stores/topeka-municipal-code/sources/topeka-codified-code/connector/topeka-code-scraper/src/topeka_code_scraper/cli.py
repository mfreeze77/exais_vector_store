from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal

import typer

from .crawler import MunicipalCodeCrawler
from .exporter import export_corpus

app = typer.Typer(add_completion=False, help="Scrape the Topeka Municipal Code into clean JSONL + GraphRAG graph files.")


@app.command()
def scrape(
    output: Path = typer.Option(Path("output/topeka"), "--output", "-o", help="Output directory."),
    root_url: str = typer.Option("https://topeka.municipal.codes/TMC", help="Crawl root."),
    delay: float = typer.Option(0.75, min=0.0, help="Minimum seconds between request starts."),
    retries: int = typer.Option(4, min=0, max=10, help="Retries for transient errors."),
    timeout: float = typer.Option(30.0, min=1.0, help="HTTP timeout in seconds."),
    max_pages: int | None = typer.Option(None, min=1, help="Optional crawl cap for testing."),
    fetcher: Literal["http", "playwright"] = typer.Option("http", help="Fetch mode: plain HTTP or stock Playwright Chromium."),
    render_wait_ms: int = typer.Option(1500, min=0, help="Extra milliseconds to wait after DOMContentLoaded in Playwright mode."),
    archive_raw: bool = typer.Option(False, help="Also save fetched HTML under output/raw/."),
    archive_network: bool = typer.Option(False, help="Also save per-page network event logs under output/network/."),
    allow_zero_sections: bool = typer.Option(False, help="Allow a crawl that fetched pages but extracted no code sections."),
    user_agent: str = typer.Option(
        "TopekaCodeScraper/0.1 (public municipal-code indexing)",
        help="HTTP User-Agent header.",
    ),
) -> None:
    """Crawl Topeka Municipal Code and export clean, graph-ready data."""

    async def run() -> None:
        crawler = MunicipalCodeCrawler(
            root_url=root_url,
            delay_seconds=delay,
            retries=retries,
            timeout_seconds=timeout,
            max_pages=max_pages,
            archive_raw=archive_raw,
            archive_network=archive_network,
            raw_dir=output / "raw",
            network_dir=output / "network",
            user_agent=user_agent,
            fetcher=fetcher,
            render_wait_ms=render_wait_ms,
        )
        pages, nodes, edges, report = await crawler.crawl()
        export_corpus(output, pages, nodes, edges, report)
        typer.echo(f"Fetched pages: {report.pages_fetched} ({report.pages_failed} failed)")
        typer.echo(f"Fetcher: {report.fetcher}")
        typer.echo(f"Sections: {report.section_count}")
        typer.echo(f"Definitions: {report.definition_count}")
        typer.echo(f"Graph: {report.node_count} nodes / {report.edge_count} edges")
        typer.echo(f"Output: {output.resolve()}")
        if report.pages_fetched == 0:
            typer.echo("Crawl failed: no pages were fetched. See crawl_report.json for details.", err=True)
            raise typer.Exit(code=2)
        if report.section_count == 0 and not allow_zero_sections:
            typer.echo("Crawl failed: no code sections were extracted. See crawl_report.json for details.", err=True)
            raise typer.Exit(code=3)

    asyncio.run(run())


if __name__ == "__main__":
    app()
