from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal

import typer

from .capture_import import import_capture_manifest
from .crawler import MunicipalCodeCrawler
from .exporter import export_corpus
from .url_manifest import (
    load_url_manifest,
    manifest_graph,
    merge_graphs,
    parse_level_filter,
    read_url_manifest,
    slice_url_manifest_entries,
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
    fetcher: Literal["http", "playwright", "decodo"] = typer.Option(
        "http",
        help="Fetch mode: plain HTTP, stock Playwright Chromium, or Decodo Web Scraping API.",
    ),
    render_wait_ms: int = typer.Option(1500, min=0, help="Extra milliseconds to wait after DOMContentLoaded in Playwright mode."),
    isolate_playwright_context: bool = typer.Option(
        False,
        "--isolate-playwright-context",
        help="Create a fresh browser context per Playwright page fetch.",
    ),
    decodo_proxy_pool: str = typer.Option(
        "",
        "--decodo-proxy-pool",
        envvar="DECODO_PROXY_POOL",
        help="Optional Decodo proxy pool for --fetcher decodo. Empty preserves provider default.",
    ),
    decodo_headless: str = typer.Option(
        "",
        "--decodo-headless",
        envvar="DECODO_HEADLESS",
        help="Optional Decodo JS rendering response type for --fetcher decodo. Empty disables the parameter.",
    ),
    decodo_geo: str = typer.Option("", "--decodo-geo", envvar="DECODO_GEO", help="Optional Decodo geographic target."),
    decodo_locale: str = typer.Option("", "--decodo-locale", envvar="DECODO_LOCALE", help="Optional Decodo locale."),
    decodo_device_type: str = typer.Option(
        "",
        "--decodo-device-type",
        envvar="DECODO_DEVICE_TYPE",
        help="Optional Decodo device type.",
    ),
    decodo_target: str = typer.Option("universal", "--decodo-target", envvar="DECODO_TARGET", help="Decodo target template."),
    archive_raw: bool = typer.Option(False, help="Also save fetched HTML under output/raw/."),
    archive_network: bool = typer.Option(False, help="Also save per-page network event logs under output/network/."),
    allow_zero_sections: bool = typer.Option(False, help="Allow a crawl that fetched pages but extracted no code sections."),
    url_list: Path | None = typer.Option(None, "--url-list", help="CSV URL manifest with level,citation,name,url columns."),
    url_list_levels: str = typer.Option(
        "Section,Subsection",
        "--url-list-levels",
        help="Comma-separated manifest levels to fetch when --url-list is supplied.",
    ),
    url_list_offset: int = typer.Option(
        0,
        "--url-list-offset",
        min=0,
        help="Skip this many filtered --url-list fetch entries while preserving the full manifest graph.",
    ),
    url_list_limit: int | None = typer.Option(
        None,
        "--url-list-limit",
        min=1,
        help="Fetch at most this many filtered --url-list entries while preserving the full manifest graph.",
    ),
    manifest_only: bool = typer.Option(
        False,
        "--manifest-only",
        help="When --url-list is supplied, fetch only listed URLs instead of following discovered links.",
    ),
    capture_manifest: Path | None = typer.Option(
        None,
        "--capture-manifest",
        help="JSONL manifest of operator-owned HTML captures to parse instead of fetching.",
    ),
    capture_root: Path | None = typer.Option(
        None,
        "--capture-root",
        help="Base directory for relative html_path values in --capture-manifest.",
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
        fetch_entries = slice_url_manifest_entries(fetch_entries, offset=url_list_offset, limit=url_list_limit)
        page_hints = {entry.url: entry for entry in fetch_entries}
        if capture_manifest:
            pages, nodes, edges, report = import_capture_manifest(
                capture_manifest,
                root_url=root_url,
                capture_root=capture_root,
                page_hints=page_hints,
                raw_dir=output / "raw" if archive_raw else None,
                network_dir=output / "network" if archive_network else None,
            )
        else:
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
                decodo_proxy_pool=decodo_proxy_pool,
                decodo_headless=decodo_headless,
                decodo_geo=decodo_geo,
                decodo_locale=decodo_locale,
                decodo_device_type=decodo_device_type,
                decodo_target=decodo_target,
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
