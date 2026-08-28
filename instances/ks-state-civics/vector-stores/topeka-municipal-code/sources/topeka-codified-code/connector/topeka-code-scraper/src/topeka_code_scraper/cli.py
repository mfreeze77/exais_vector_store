from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal

import typer

from .crawler import MunicipalCodeCrawler
from .exporter import export_corpus
from .url_manifest import (
    load_url_manifest,
    manifest_graph,
    merge_graphs,
    parse_level_filter,
    read_url_manifest,
    write_url_manifest_artifacts,
)

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
    isolate_playwright_context: bool = typer.Option(
        False,
        "--isolate-playwright-context",
        help="Create a fresh browser context per Playwright page fetch.",
    ),
    archive_raw: bool = typer.Option(False, help="Also save fetched HTML under output/raw/."),
    archive_network: bool = typer.Option(False, help="Also save per-page network event logs under output/network/."),
    allow_zero_sections: bool = typer.Option(False, help="Allow a crawl that fetched pages but extracted no code sections."),
    url_list: Path | None = typer.Option(None, "--url-list", help="CSV URL manifest with level,citation,name,url columns."),
    url_list_levels: str = typer.Option(
        "Section,Subsection",
        "--url-list-levels",
        help="Comma-separated manifest levels to fetch when --url-list is supplied.",
    ),
    manifest_only: bool = typer.Option(
        False,
        "--manifest-only",
        help="When --url-list is supplied, fetch only listed URLs instead of following discovered links.",
    ),
    user_agent: str = typer.Option(
        "TopekaCodeScraper/0.1 (public municipal-code indexing)",
        help="HTTP User-Agent header.",
    ),
) -> None:
    """Crawl Topeka Municipal Code and export clean, graph-ready data."""

    async def run() -> None:
        manifest_entries = read_url_manifest(url_list) if url_list else []
        fetch_levels = parse_level_filter(url_list_levels)
        fetch_entries = load_url_manifest(url_list, fetch_levels=fetch_levels) if url_list else []
        page_hints = {entry.url: entry for entry in fetch_entries}
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
            isolate_playwright_context=isolate_playwright_context,
            seed_urls=[entry.url for entry in fetch_entries] if fetch_entries else None,
            page_hints=page_hints,
            follow_links=not manifest_only,
        )
        pages, nodes, edges, report = await crawler.crawl()
        if manifest_entries:
            manifest_nodes, manifest_edges = manifest_graph(manifest_entries)
            nodes, edges = merge_graphs(manifest_nodes, manifest_edges, nodes, edges)
            report.node_count = len(nodes)
            report.edge_count = len(edges)
        export_corpus(output, pages, nodes, edges, report)
        if manifest_entries:
            write_url_manifest_artifacts(output, manifest_entries, fetch_entries)
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
