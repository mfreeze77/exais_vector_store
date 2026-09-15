#!/usr/bin/env python3
"""Inventory every document in Topeka's declared master listings.

The city publishes both listings through a Revize document centre, which prints
its own per-category and per-year document counts. Those printed counts are an
independently authored number: this script reconciles the links it parsed
against them, so "we found N documents" is corroborated by the publisher rather
than only by our own parser.

    python scripts/release/topeka-collection-discover.py --listing all --output-dir <dir>

A parse that yields no documents for a declared group is a failure, never an
empty successful listing. Discovery is read-only: it fetches listing HTML and
writes manifests. It downloads no PDF; acquisition is a separate resumable step.
"""
from __future__ import annotations

import argparse
import html
import html.parser
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import urljoin, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jurisdiction_release_contract import (  # noqa: E402
    COLLECTIONS_BY_SLUG,
    ROOT,
    CollectionSpec,
    RoutingError,
    canonical_source_url,
    publisher_key,
    route_document,
    sha256_bytes,
    source_document_id,
)

USER_AGENT = "ExAIS-Vector-Store-Topeka-Collector/1.0"

DEFAULT_OUTPUT = (
    ROOT / "instances" / "ks-state-civics" / "vector-stores" / "topeka-municipal-code" / "discovery"
)
ORDINANCE_SEED = (
    ROOT / "instances" / "ks-state-civics" / "vector-stores" / "topeka-municipal-code"
    / "sources" / "topeka-ordinances" / "seed"
)

# Publisher category label -> registered collection. Labels are the publisher's
# own category headings; a label that is not here is reported, never guessed at.
CATEGORY_LABELS: dict[str, str] = {
    "ordinances": "ordinances",
    "charter ordinances": "charter-ordinances",
    "resolutions": "resolutions",
}

LISTINGS: dict[str, dict[str, Any]] = {
    "ordinances": {
        "url": "https://topeka.gov/community/ordinances/index.php",
        # This page carries two categories; each maps by its own heading.
        "default_collection": None,
    },
    "resolutions": {
        "url": "https://topeka.gov/community/resolutions/index.php",
        # This page's top-level headings are years, not categories: the whole
        # listing is one collection and year navigation does not split it.
        "default_collection": "resolutions",
    },
}

_YEAR = re.compile(r"^(19|20)\d{2}$")

# Every file type the city actually publishes instruments as. The listing is not
# PDF-only: recent 2026 ordinances appear as .docx, and dropping them would
# under-report a declared group while still looking like a clean parse.
DOCUMENT_MEDIA_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc": "application/msword",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".rtf": "application/rtf",
    ".txt": "text/plain",
    ".csv": "text/csv",
}
# Extraction today is the bounded remote PDF path. Other types are acquired and
# inventoried, but their extraction support is stated, never assumed.
EXTRACTABLE_MEDIA_TYPES = frozenset({"application/pdf"})


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class DiscoveredLink:
    url: str
    label: str
    category_label: str | None
    group_label: str | None
    in_document_centre: bool
    media_type: str
    extension: str


@dataclass
class DeclaredGroup:
    node_id: str
    label: str
    level: str  # "category" or "group"
    declared_count: int
    parent: str | None = None
    listed_entries: int = 0
    duplicate_entries: int = 0
    members: list[str] = field(default_factory=list)


class DocumentCentreParser(html.parser.HTMLParser):
    """Walks the Revize document centre, keeping each link's category and year.

    Structure, from the live pages:
        <a name="outer-539"></a><h3 class="docs-toggle ...">Ordinances
            <small class="doc-center-counter">350 documents</small></h3>
          <a name="sub-547"></a><h4 class="docs-toggle ...">2025
              <small class="doc-center-counter">83 documents</small></h4>
            <ul class="file-group"><li><a href="...pdf">20601</a></li>...

    Links that appear before any category heading are kept with
    ``in_document_centre=False`` rather than dropped: the Standard Traffic
    Ordinance is listed in the page intro, outside the centre.
    """

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: list[DiscoveredLink] = []
        self.groups: list[DeclaredGroup] = []

        self._pending_node: tuple[str, str] | None = None  # (kind, node id)
        self._heading: tuple[str, str, str] | None = None  # (level, node id, tag)
        self._heading_text: list[str] = []
        self._counter_text: list[str] | None = None
        self._category: str | None = None
        self._group: str | None = None
        self._anchor: str | None = None
        self._anchor_text: list[str] = []

    def handle_starttag(self, tag: str, attrs_list: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attrs = {key.lower(): (value or "") for key, value in attrs_list}

        if tag == "a" and attrs.get("name", "").startswith(("outer-", "sub-")):
            kind, _, node_id = attrs["name"].partition("-")
            self._pending_node = ("category" if kind == "outer" else "group", node_id)
            return

        if tag in {"h3", "h4"} and "docs-toggle" in attrs.get("class", ""):
            level, node_id = self._pending_node or (("category" if tag == "h3" else "group"), f"anon-{len(self.groups)}")
            self._pending_node = None
            self._heading = (level, node_id, tag)
            self._heading_text = []
            self._counter_text = None
            return

        if tag == "small" and self._heading and "doc-center-counter" in attrs.get("class", ""):
            self._counter_text = []
            return

        if tag == "a" and attrs.get("href"):
            self._anchor = urljoin(self.base_url, attrs["href"])
            self._anchor_text = []

    def handle_data(self, data: str) -> None:
        if self._counter_text is not None:
            self._counter_text.append(data)
        elif self._heading is not None:
            self._heading_text.append(data)
        if self._anchor is not None:
            self._anchor_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "small" and self._counter_text is not None:
            return  # keep the captured text until the heading closes

        if tag in {"h3", "h4"} and self._heading and self._heading[2] == tag:
            level, node_id, _ = self._heading
            label = " ".join("".join(self._heading_text).split())
            declared = 0
            if self._counter_text:
                match = re.search(r"([\d,]+)\s+documents?", "".join(self._counter_text))
                if match:
                    declared = int(match.group(1).replace(",", ""))
            # Hierarchy comes from the markup level, which is what the publisher
            # actually varies: the ordinances page prints years as h4 under a
            # category h3, the resolutions page prints years as h3 directly.
            level = "category" if tag == "h3" else "group"
            if level == "category":
                self._category = label
                self._group = label if _YEAR.match(label) else None
                parent = None
            else:
                self._group = label
                parent = self._category
            self.groups.append(DeclaredGroup(node_id, label, level, declared, parent))
            self._heading = None
            self._heading_text = []
            self._counter_text = None
            return

        if tag == "a" and self._anchor is not None:
            url, label = self._anchor, " ".join("".join(self._anchor_text).split())
            self._anchor, self._anchor_text = None, []
            extension = Path(urlsplit(url).path).suffix.lower()
            media_type = DOCUMENT_MEDIA_TYPES.get(extension)
            if media_type is None:
                return
            self.links.append(DiscoveredLink(
                url=url,
                label=label,
                category_label=self._category,
                group_label=self._group,
                in_document_centre=self._category is not None,
                media_type=media_type,
                extension=extension,
            ))


def fetch(url: str, *, timeout: int) -> bytes:
    req = request.Request(url, headers={"User-Agent": USER_AGENT})
    with request.urlopen(req, timeout=timeout) as response:
        return response.read()


def collection_for(link: DiscoveredLink, listing: str) -> tuple[CollectionSpec | None, str]:
    """Registered collection for one discovered link, plus how it was decided.

    Category first, because listing membership is the publisher's category. A
    link outside the document centre has no category, so it falls back to the
    registry's URL rules.
    """
    label = (link.category_label or "").strip().lower()
    slug = CATEGORY_LABELS.get(label)
    if slug is None and _YEAR.match(label or ""):
        slug = LISTINGS[listing]["default_collection"]
    if slug:
        spec = COLLECTIONS_BY_SLUG[slug]
        # The publisher's category says what a document is; it does not make an
        # arbitrary host official. A link placed under a category but served from
        # somewhere we have not registered is reported, not adopted.
        if not on_registered_host(link.url, spec):
            return None, f"off_host_for_{spec.slug}"
        return spec, f"listing_category:{link.category_label}"
    try:
        return route_document(official_url=link.url), "url_rule"
    except RoutingError:
        return None, "unrouted"


def on_registered_host(url: str, spec: CollectionSpec) -> bool:
    parts = urlsplit(canonical_source_url(url))
    if parts.netloc in spec.hosts:
        return True
    return any(
        parts.netloc == host and parts.path.startswith(prefix)
        for host, prefix in spec.legacy_locations
    )


def derive_publisher_key(link: DiscoveredLink, spec: CollectionSpec) -> str:
    """The publisher's own key for this document.

    The link label is the ordinance/resolution number on these listings; the
    file stem is the fallback, which is what keeps the unnumbered Standard
    Traffic Ordinance identifiable.
    """
    label = link.label.strip()
    if re.fullmatch(r"[A-Za-z]?\d{1,6}[A-Za-z]?", label):
        return label
    stem = Path(urlsplit(canonical_source_url(link.url)).path).stem
    match = re.search(r"(\d{2,6})\s*$", stem)
    if match and spec.slug != "municipal-code":
        return match.group(1)
    return stem


def _group_for(index: dict, link: DiscoveredLink) -> DeclaredGroup | None:
    """The declared group a link sits in, or None when it is outside the centre."""
    if not link.in_document_centre:
        return None
    return index.get((link.category_label, link.group_label)) or index.get((None, link.category_label))


def discover_listing(listing: str, *, html_bytes: bytes, source_url: str) -> dict[str, Any]:
    parser = DocumentCentreParser(source_url)
    parser.feed(html_bytes.decode("utf-8", errors="replace"))

    groups = {group.node_id: group for group in parser.groups}
    documents: dict[str, dict[str, Any]] = {}
    aliases: list[dict[str, Any]] = []
    unrouted: list[dict[str, Any]] = []
    outside_centre: list[dict[str, Any]] = []

    group_by_label: dict[tuple[str | None, str | None], DeclaredGroup] = {}
    for group in parser.groups:
        group_by_label[(group.parent, group.label)] = group

    for link in parser.links:
        spec, basis = collection_for(link, listing)
        canonical = canonical_source_url(link.url)
        if spec is None or not canonical:
            unrouted.append({"url": link.url, "label": link.label, "reason": basis})
            continue

        key = derive_publisher_key(link, spec)
        try:
            doc_id = source_document_id(spec, key)
        except ValueError:
            unrouted.append({"url": link.url, "label": link.label, "reason": "no stable publisher key"})
            continue

        parts = urlsplit(canonical)
        is_legacy = any(
            parts.netloc == host and parts.path.startswith(prefix)
            for host, prefix in spec.legacy_locations
        )

        if not link.in_document_centre:
            outside_centre.append({"source_document_id": doc_id, "url": canonical, "label": link.label})

        existing = documents.get(doc_id)
        if existing is None:
            documents[doc_id] = {
                "source_document_id": doc_id,
                "collection_id": spec.collection_id,
                "publisher_key": key,
                "official_url": canonical,
                "label": link.label,
                "listing_url": source_url,
                "listing_category": link.category_label,
                "listing_group": link.group_label,
                "routing_basis": basis,
                "in_document_centre": link.in_document_centre,
                "membership": "document_centre" if link.in_document_centre else "outside_document_centre_review_needed",
                "is_legacy_url": is_legacy,
                "media_type": link.media_type,
                "extraction_supported": link.media_type in EXTRACTABLE_MEDIA_TYPES,
                "alias_urls": [],
                "legacy_urls": [canonical] if is_legacy else [],
            }
            group = _group_for(group_by_label, link)
            if group:
                group.listed_entries += 1
                group.members.append(doc_id)
            continue

        group = _group_for(group_by_label, link)
        if group:
            # A second listed entry for the same document still occupies a slot in
            # the publisher's count, so it is counted and then named as a duplicate.
            group.listed_entries += 1
            group.duplicate_entries += 1

        # Same document reached through another URL, or listed twice. One
        # identity either way; the extra entry is reported, not silently merged.
        if canonical == existing["official_url"]:
            aliases.append({
                "source_document_id": doc_id,
                "canonical_url": canonical,
                "alias_url": canonical,
                "kind": "repeated_listing_entry",
            })
        else:
            if is_legacy:
                existing["legacy_urls"].append(canonical)
            else:
                existing["alias_urls"].append(canonical)
            aliases.append({
                "source_document_id": doc_id,
                "alias_url": canonical,
                "kind": "legacy_location" if is_legacy else "duplicate_listing_entry",
            })
        # Canonical URL preference, strongest first: a live document-centre entry,
        # then any live entry, then a legacy location. A retired bucket must never
        # end up as the official URL just because it appeared earlier in the page.
        def rank(in_centre: bool, legacy: bool) -> int:
            return (2 if in_centre else 1) - (2 if legacy else 0)

        if rank(link.in_document_centre, is_legacy) > rank(existing["in_document_centre"], existing["is_legacy_url"]):
            existing["alias_urls"].append(existing["official_url"])
            if existing["is_legacy_url"] and existing["official_url"] not in existing["legacy_urls"]:
                existing["legacy_urls"].append(existing["official_url"])
            existing["official_url"] = canonical
            existing["is_legacy_url"] = is_legacy
            existing["in_document_centre"] = link.in_document_centre
            if link.in_document_centre:
                existing["membership"] = "document_centre"
                existing["listing_category"] = link.category_label
                existing["listing_group"] = link.group_label

    for row in documents.values():
        official = row["official_url"]
        row["alias_urls"] = sorted(set(row["alias_urls"]) - {official})
        row["legacy_urls"] = sorted(set(row["legacy_urls"]) - {official})
    for alias in aliases:
        alias["canonical_url"] = documents[alias["source_document_id"]]["official_url"]
    # An entry that ended up being the canonical URL is not an alias of itself.
    aliases = [a for a in aliases if a["alias_url"] != a["canonical_url"] or a["kind"] == "repeated_listing_entry"]

    by_collection = Counter(row["collection_id"] for row in documents.values())
    return {
        "listing": listing,
        "source_url": source_url,
        "listing_sha256": sha256_bytes(html_bytes),
        "retrieved_at": utc_now(),
        "documents": sorted(documents.values(), key=lambda row: row["source_document_id"]),
        "groups": [
            {
                "node_id": group.node_id,
                "label": group.label,
                "level": group.level,
                "parent": group.parent,
                "declared_count": group.declared_count,
                "listed_entries": group.listed_entries,
                "duplicate_entries": group.duplicate_entries,
                "distinct_documents": group.listed_entries - group.duplicate_entries,
            }
            for group in parser.groups
        ],
        "aliases": aliases,
        "unrouted": unrouted,
        "outside_document_centre": outside_centre,
        "link_count": len(parser.links),
        "by_collection": dict(sorted(by_collection.items())),
    }


def reconcile(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Compare the parse against the publisher's own printed counts.

    Two different numbers are checked, because they answer different questions:
    ``listed_entries`` must equal the publisher's count (did we parse every slot
    the publisher printed?), while ``distinct_documents`` may legitimately be
    lower when the publisher lists one document twice.
    """
    findings: list[dict[str, Any]] = []
    groups = result["groups"]
    children_of: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for group in groups:
        if group["parent"]:
            children_of[group["parent"]].append(group)

    for group in groups:
        children = children_of.get(group["label"], [])
        if group["level"] == "category" and children:
            child_declared = sum(other["declared_count"] for other in children)
            child_listed = sum(other["listed_entries"] for other in children)
            if child_listed != child_declared:
                findings.append({
                    "severity": "error",
                    "code": "GROUP_COUNT_MISMATCH",
                    "group": group["label"],
                    "declared": child_declared,
                    "listed": child_listed,
                    "detail": "the year groups' printed counts do not match the entries parsed from them",
                })
            outside = group["declared_count"] - child_declared
            if outside:
                findings.append({
                    "severity": "warning",
                    "code": "CATEGORY_SUBTOTAL_GAP",
                    "group": group["label"],
                    "declared": group["declared_count"],
                    "listed": child_declared,
                    "detail": (
                        f"the category counter is {outside} higher than its year counters; documents "
                        "listed outside the year groups account for the difference"
                    ),
                })
            continue

        if group["declared_count"] and group["listed_entries"] == 0:
            findings.append({
                "severity": "error",
                "code": "EMPTY_DECLARED_GROUP",
                "group": group["label"],
                "declared": group["declared_count"],
                "listed": 0,
                "detail": "the publisher declares documents here but the parse found none",
            })
        elif group["listed_entries"] != group["declared_count"]:
            findings.append({
                "severity": "error",
                "code": "GROUP_COUNT_MISMATCH",
                "group": group["label"],
                "declared": group["declared_count"],
                "listed": group["listed_entries"],
                "detail": "parsed entry count does not match the publisher's printed count",
            })
        if group["duplicate_entries"]:
            findings.append({
                "severity": "warning",
                "code": "DUPLICATE_LISTING_ENTRY",
                "group": group["label"],
                "declared": group["declared_count"],
                "listed": group["listed_entries"],
                "detail": (
                    f"{group['duplicate_entries']} entr(y/ies) point at a document already listed in this "
                    "group; they resolve to one identity and do not create extra documents"
                ),
            })

    for row in result["unrouted"]:
        findings.append({
            "severity": "error",
            "code": "UNROUTED_DOCUMENT",
            "group": row.get("label") or row["url"],
            "detail": f"{row['url']} -> {row['reason']}",
        })

    review = [d for d in result["documents"] if d["membership"] != "document_centre"]
    if review:
        findings.append({
            "severity": "warning",
            "code": "MEMBERSHIP_REVIEW_NEEDED",
            "group": result["listing"],
            "detail": (
                f"{len(review)} document(s) are linked from the page but not from the document centre "
                f"({[d['source_document_id'].rsplit(':', 1)[-1] for d in review]}); membership is not "
                "established by a page link alone and needs review before release"
            ),
        })

    unsupported = [d for d in result["documents"] if not d["extraction_supported"]]
    if unsupported:
        by_type = Counter(d["media_type"] for d in unsupported)
        findings.append({
            "severity": "warning",
            "code": "EXTRACTION_UNSUPPORTED_MEDIA",
            "group": result["listing"],
            "detail": (
                f"{len(unsupported)} listed document(s) are not PDFs ({dict(by_type)}); they are "
                "inventoried and acquirable, but the configured extraction path is PDF-only"
            ),
        })
    return findings


def build_worklist(results: list[dict[str, Any]], seed: Path) -> dict[str, Any]:
    """Reconcile discovery against the retained corpus.

    Outcomes are assigned per discovered document and per retained record, and
    every record on both sides lands in exactly one bucket.
    """
    retained: dict[str, dict[str, Any]] = {}
    manifest = seed / "manifests" / "ordinances.jsonl"
    if manifest.exists():
        with manifest.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                row = json.loads(line)
                try:
                    spec = route_document(official_url=row["pdf_url"], listing_category=row.get("category"))
                except RoutingError:
                    continue
                key = str(row.get("ordinance_number") or "").strip() or \
                    Path(urlsplit(canonical_source_url(row["pdf_url"])).path).stem
                retained[source_document_id(spec, key)] = row

    discovered = {row["source_document_id"]: row for result in results for row in result["documents"]}

    reuse, acquire, absent = [], [], []
    for doc_id, row in sorted(discovered.items()):
        record = retained.get(doc_id)
        if record is None:
            acquire.append({
                "source_document_id": doc_id,
                "collection_id": row["collection_id"],
                "official_url": row["official_url"],
                "outcome": "acquire_new",
                "reason": "listed by the publisher with no retained original",
            })
            continue
        reuse.append({
            "source_document_id": doc_id,
            "collection_id": row["collection_id"],
            "official_url": row["official_url"],
            "retained_sha256": record["sha256"],
            "retained_path": record["saved_path"],
            "outcome": "verify_then_reuse",
            "reason": (
                "a retained original exists for this identity; acquisition re-reads the publisher "
                "byte length and hash before deciding reuse or re-download"
            ),
        })
    for doc_id, record in sorted(retained.items()):
        if doc_id in discovered:
            continue
        absent.append({
            "source_document_id": doc_id,
            "official_url": canonical_source_url(record["pdf_url"]),
            "retained_sha256": record["sha256"],
            "outcome": "retained_but_unlisted",
            "reason": (
                "retained here but absent from the current publisher listing. The city states only "
                "ordinances from the last four years are published online, so absence is a listing "
                "window, not a repeal, and the retained version is kept"
            ),
        })

    return {
        "discovered_count": len(discovered),
        "retained_count": len(retained),
        "verify_then_reuse": reuse,
        "acquire_new": acquire,
        "retained_but_unlisted": absent,
        "counts": {
            "verify_then_reuse": len(reuse),
            "acquire_new": len(acquire),
            "retained_but_unlisted": len(absent),
        },
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--listing", choices=[*LISTINGS, "all"], default="all")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--ordinance-seed", type=Path, default=ORDINANCE_SEED)
    parser.add_argument("--cached-html", type=Path, default=None,
                        help="directory holding <listing>.html, used instead of fetching")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--save-listing-html", action="store_true",
                        help="retain the fetched listing HTML next to the manifests")
    args = parser.parse_args()

    names = list(LISTINGS) if args.listing == "all" else [args.listing]
    results: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []

    for name in names:
        source_url = LISTINGS[name]["url"]
        if args.cached_html:
            path = args.cached_html / f"{name}.html"
            if not path.exists():
                print(f"FAIL cached listing {path} is absent")
                return 1
            payload = path.read_bytes()
        else:
            try:
                payload = fetch(source_url, timeout=args.timeout)
            except (error.URLError, TimeoutError) as exc:
                findings.append({
                    "severity": "error", "code": "LISTING_UNREACHABLE",
                    "group": name, "detail": f"{source_url}: {exc}",
                })
                print(f"FAIL {name}: {source_url} unreachable: {exc}")
                continue

        result = discover_listing(name, html_bytes=payload, source_url=source_url)
        results.append(result)
        findings.extend(reconcile(result))

        target = args.output_dir / name
        write_jsonl(target / "documents.jsonl", result["documents"])
        write_jsonl(target / "groups.jsonl", result["groups"])
        write_jsonl(target / "aliases.jsonl", result["aliases"])
        if args.save_listing_html:
            (target / "listing.html").write_bytes(payload)

    worklist = build_worklist(results, args.ordinance_seed)
    write_jsonl(args.output_dir / "worklist.jsonl",
                worklist["verify_then_reuse"] + worklist["acquire_new"] + worklist["retained_but_unlisted"])

    errors = [f for f in findings if f["severity"] == "error"]
    report = {
        "artifact": "topeka_collection_discovery",
        "schema_version": "1.0",
        "discovered_at": utc_now(),
        "listings": [
            {
                "listing": r["listing"],
                "source_url": r["source_url"],
                "listing_sha256": r["listing_sha256"],
                "link_count": r["link_count"],
                "document_count": len(r["documents"]),
                "by_collection": r["by_collection"],
                "alias_count": len(r["aliases"]),
                "outside_document_centre": r["outside_document_centre"],
                "groups": r["groups"],
            }
            for r in results
        ],
        "worklist_counts": worklist["counts"],
        "findings": findings,
        "passed": not errors and len(results) == len(names),
    }
    (args.output_dir / "discovery-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    for r in results:
        print(f"{r['listing']:12s} links={r['link_count']:4d}  documents={len(r['documents']):4d}  "
              f"aliases={len(r['aliases']):2d}  {r['by_collection']}")
        parents = {g["parent"] for g in r["groups"] if g["parent"]}
        for group in r["groups"]:
            # A category with year groups is counted through them, not directly.
            rolls_up = group["label"] in parents
            flag = "" if rolls_up or group["listed_entries"] == group["declared_count"] else "  <-- differs"
            dupes = f"  (-{group['duplicate_entries']} duplicate)" if group["duplicate_entries"] else ""
            indent = "  " if group["level"] == "category" else "    "
            shown = (
                sum(g["listed_entries"] for g in r["groups"] if g["parent"] == group["label"]) + group["listed_entries"]
                if rolls_up else group["listed_entries"]
            )
            print(f"{indent}{group['label']:22s} declared={group['declared_count']:4d} "
                  f"listed={shown:4d} distinct={group['distinct_documents']:4d}{flag}{dupes}")
    print(f"worklist       {worklist['counts']}")
    for finding in findings:
        print(f"  {finding['severity'].upper()} {finding['code']} {finding.get('group','')}: {finding['detail']}")
    print(f"result         {'PASS' if report['passed'] else 'FAIL'}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
