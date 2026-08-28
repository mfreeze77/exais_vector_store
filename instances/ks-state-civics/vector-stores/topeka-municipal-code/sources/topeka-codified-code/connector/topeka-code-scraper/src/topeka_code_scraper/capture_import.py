from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .fetcher import is_challenge_only_page
from .graph import GraphBuilder
from .models import CrawlReport, ParsedPage
from .normalize import BASE_URL, canonicalize_url, sha256_text
from .parser import MunicipalCodeParser
from .url_manifest import UrlManifestEntry


def import_capture_manifest(
    capture_manifest: Path,
    *,
    root_url: str = f"{BASE_URL}/TMC",
    capture_root: Path | None = None,
    page_hints: dict[str, UrlManifestEntry] | None = None,
    raw_dir: Path | None = None,
    network_dir: Path | None = None,
) -> tuple[list[ParsedPage], list, list, CrawlReport]:
    started = datetime.now(UTC)
    parser = MunicipalCodeParser()
    pages: list[ParsedPage] = []
    failures: list[dict[str, str]] = []
    rows_seen = 0
    hints = page_hints or {}

    base_dir = capture_root or capture_manifest.parent
    for row_number, row in enumerate(_read_jsonl(capture_manifest), start=1):
        rows_seen += 1
        raw_url = str(row.get("url") or row.get("source_url") or "")
        canonical = canonicalize_url(raw_url)
        if not canonical:
            failures.append({"url": raw_url or f"row:{row_number}", "error": "ValueError: capture URL is not under https://topeka.municipal.codes/TMC"})
            continue

        try:
            html = _capture_html(row, base_dir)
            status_code = int(row.get("status_code") or 200)
            headers = _headers(row.get("headers"))
            if is_challenge_only_page(status_code, headers, html):
                raise RuntimeError(f"publisher challenge page returned for {canonical}")
            retrieved_at = _retrieved_at(row.get("retrieved_at"))
            hint = hints.get(canonical)
            page = parser.parse(
                canonical,
                html,
                retrieved_at,
                forced_page_type=hint.parser_page_type if hint else None,
                forced_citation=hint.citation if hint else None,
                forced_title=hint.name if hint else None,
            )
            pages.append(page)
            _archive_html(raw_dir, page, html)
            _archive_network(network_dir, page, row, status_code, headers, retrieved_at)
        except Exception as exc:
            failures.append({"url": canonical, "error": f"{type(exc).__name__}: {exc}"})

    nodes, edges = GraphBuilder().build(pages)
    finished = datetime.now(UTC)
    report = CrawlReport(
        started_at=started,
        finished_at=finished,
        root_url=canonicalize_url(root_url) or f"{BASE_URL}/TMC",
        pages_seen=rows_seen,
        pages_fetched=len(pages),
        pages_failed=len(failures),
        section_count=sum(1 for page in pages if page.section),
        definition_count=sum(len(page.definitions) for page in pages),
        node_count=len(nodes),
        edge_count=len(edges),
        failures=failures,
        fetcher="capture_manifest",
    )
    return pages, nodes, edges, report


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on {path}:{line_number}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"Capture row on {path}:{line_number} must be an object")
            rows.append(value)
    return rows


def _capture_html(row: dict[str, Any], base_dir: Path) -> str:
    inline = row.get("html")
    if isinstance(inline, str) and inline.strip():
        return inline

    html_path = row.get("html_path") or row.get("path")
    if not isinstance(html_path, str) or not html_path.strip():
        raise ValueError("capture row must include html or html_path")
    path = Path(html_path)
    if not path.is_absolute():
        path = base_dir / path
    return path.read_text(encoding="utf-8")


def _headers(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def _retrieved_at(value: Any) -> datetime:
    if isinstance(value, str) and value.strip():
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return datetime.now(UTC)


def _archive_html(raw_dir: Path | None, page: ParsedPage, html: str) -> None:
    if raw_dir is None:
        return
    raw_dir.mkdir(parents=True, exist_ok=True)
    name = page.path.removeprefix("/TMC").strip("/") or "TMC"
    safe = name.replace("/", "__")
    path = raw_dir / f"{safe}.{sha256_text(html)[:12]}.html"
    path.write_text(html, encoding="utf-8")


def _archive_network(
    network_dir: Path | None,
    page: ParsedPage,
    row: dict[str, Any],
    status_code: int,
    headers: dict[str, str],
    retrieved_at: datetime,
) -> None:
    if network_dir is None:
        return
    network_dir.mkdir(parents=True, exist_ok=True)
    name = page.path.removeprefix("/TMC").strip("/") or "TMC"
    safe = name.replace("/", "__")
    path = network_dir / f"{safe}.{sha256_text(page.url)[:12]}.network.json"
    payload = {
        "url": page.url,
        "status_code": status_code,
        "retrieved_at": retrieved_at.isoformat(),
        "headers": headers,
        "events": row.get("network_events") if isinstance(row.get("network_events"), list) else [],
        "source": row.get("source") or "operator_capture",
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
