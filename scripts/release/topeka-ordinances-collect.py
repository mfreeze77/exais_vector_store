#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html.parser
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib import request
from urllib.parse import urljoin, urlsplit

from topeka_pipeline_common import ORDINANCE_SEED, safe_filename, sha256_bytes, stable_id, utc_now, write_json, write_jsonl


DEFAULT_SOURCE_URL = "https://topeka.gov/community/ordinances/index.php"
OFFICIAL_HOST_SUFFIXES = ("topeka.gov",)


@dataclass(frozen=True)
class Link:
    url: str
    label: str


class AnchorParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[Link] = []
        self._href_stack: list[str] = []
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self._href_stack.append(href)
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._href_stack:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._href_stack:
            return
        href = self._href_stack.pop()
        label = " ".join(" ".join(self._text_parts).split())
        self.links.append(Link(href, label))
        self._text_parts = []


def fetch_bytes(url: str, *, timeout: int) -> bytes:
    req = request.Request(url, headers={"User-Agent": "ExAIS-Vector-Store-Topeka-Ordinance-Collector/1.0"})
    with request.urlopen(req, timeout=timeout) as response:
        return response.read()


def discover_pdf_links(html: str, base_url: str) -> list[Link]:
    parser = AnchorParser()
    parser.feed(html)
    seen: set[str] = set()
    links: list[Link] = []
    for raw in parser.links:
        url = urljoin(base_url, raw.url)
        parsed = urlsplit(url)
        if ".pdf" not in parsed.path.lower() and ".pdf" not in parsed.query.lower():
            continue
        if not is_official_pdf_candidate(url, base_url):
            continue
        haystack = f"{raw.label} {parsed.path}".lower()
        if "ordinance" not in haystack and not re.search(r"\bord(?:inance)?[-_\s]?\d", haystack):
            continue
        normalized = url.split("#", 1)[0]
        if normalized in seen:
            continue
        seen.add(normalized)
        links.append(Link(normalized, raw.label or Path(parsed.path).name))
    return links


def is_official_pdf_candidate(url: str, source_url: str) -> bool:
    source_host = urlsplit(source_url).hostname or ""
    host = urlsplit(url).hostname or ""
    if host == source_host or any(host == suffix or host.endswith("." + suffix) for suffix in OFFICIAL_HOST_SUFFIXES):
        return True
    return False


def parse_ordinance_identity(label: str, url: str) -> dict[str, str]:
    text = " ".join(f"{label} {Path(urlsplit(url).path).stem}".replace("_", " ").replace("-", " ").split())
    category = "charter_ordinance" if re.search(r"\bcharter\b", text, re.I) else "ordinance"
    match = re.search(r"\b(?:charter\s+)?ordinance\s*(?:no\.?|number|#)?\s*([A-Z]?\d{3,6}[A-Z]?)\b", text, re.I)
    if not match:
        match = re.search(r"\bord(?:inance)?\s*([A-Z]?\d{3,6}[A-Z]?)\b", text, re.I)
    ordinance_number = match.group(1).upper() if match else ""
    year_match = re.search(r"\b(19|20)\d{2}\b", text)
    return {
        "category": category,
        "ordinance_number": ordinance_number,
        "year": year_match.group(0) if year_match else "",
        "title": label.strip() or Path(urlsplit(url).path).name,
    }


def build_record(link: Link, pdf_bytes: bytes, saved_path: Path, source_url: str, retrieved_at: str) -> dict[str, Any]:
    identity = parse_ordinance_identity(link.label, link.url)
    digest = sha256_bytes(pdf_bytes)
    record_id = stable_id("topeka-ordinance", identity["ordinance_number"], link.url, digest)
    return {
        "id": record_id,
        "jurisdiction_id": "ks-topeka",
        "jurisdiction_name": "City of Topeka, Kansas",
        "source_collection": "topeka-ordinances",
        "source_page_url": source_url,
        "category": identity["category"],
        "ordinance_number": identity["ordinance_number"],
        "title": identity["title"],
        "year": identity["year"],
        "pdf_url": link.url,
        "saved_path": saved_path.as_posix(),
        "byte_count": len(pdf_bytes),
        "sha256": digest,
        "retrieved_at": retrieved_at,
    }


def collect_ordinances(
    *,
    source_url: str,
    html: str,
    output_dir: Path,
    limit: int,
    timeout: int,
    downloader=fetch_bytes,
) -> dict[str, Any]:
    pdf_dir = output_dir / "raw" / "pdfs"
    manifest_path = output_dir / "manifests" / "ordinances.jsonl"
    citation_path = output_dir / "citation-url-map.jsonl"
    retrieved_at = utc_now()
    links = discover_pdf_links(html, source_url)
    if limit > 0:
        links = links[:limit]
    records: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for link in links:
        try:
            pdf_bytes = downloader(link.url, timeout=timeout)
            name_parts = parse_ordinance_identity(link.label, link.url)
            name_seed = name_parts["ordinance_number"] or Path(urlsplit(link.url).path).stem or stable_id("pdf", link.url)
            saved_path = pdf_dir / safe_filename(name_seed, suffix=".pdf")
            saved_path.parent.mkdir(parents=True, exist_ok=True)
            saved_path.write_bytes(pdf_bytes)
            records.append(build_record(link, pdf_bytes, saved_path.relative_to(output_dir), source_url, retrieved_at))
        except Exception as exc:  # Network/PDF failures must be visible in the manifest, not hidden.
            failures.append({"url": link.url, "label": link.label, "error": str(exc)})
    citation_rows = [
        {
            "record_type": "ordinance_pdf",
            "id": row["id"],
            "ordinance_number": row["ordinance_number"],
            "title": row["title"],
            "source_url": row["pdf_url"],
            "citation_url": row["pdf_url"],
            "content_hash": row["sha256"],
        }
        for row in records
    ]
    write_jsonl(manifest_path, records)
    write_jsonl(citation_path, citation_rows)
    summary = {
        "schema_version": "1.0",
        "status": "success" if records and not failures else "partial_with_failures" if records else "failed_no_ordinances",
        "source_url": source_url,
        "retrieved_at": retrieved_at,
        "links_seen": len(links),
        "ordinance_count": len(records),
        "failure_count": len(failures),
        "failures": failures,
        "files": {
            "ordinances": "manifests/ordinances.jsonl",
            "citation_url_map": "citation-url-map.jsonl",
            "pdfs": "raw/pdfs/",
        },
    }
    write_json(output_dir / "manifests" / "ordinances-manifest.json", summary)
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect official Topeka ordinance PDFs into the source seed layout.")
    parser.add_argument("--source-url", default=DEFAULT_SOURCE_URL)
    parser.add_argument("--output-dir", type=Path, default=ORDINANCE_SEED)
    parser.add_argument("--fixture-html", type=Path)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--allow-empty", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    html = args.fixture_html.read_text(encoding="utf-8") if args.fixture_html else fetch_bytes(args.source_url, timeout=args.timeout).decode("utf-8", errors="replace")
    summary = collect_ordinances(
        source_url=args.source_url,
        html=html,
        output_dir=args.output_dir,
        limit=args.limit,
        timeout=args.timeout,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if not args.allow_empty and summary["ordinance_count"] == 0:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
