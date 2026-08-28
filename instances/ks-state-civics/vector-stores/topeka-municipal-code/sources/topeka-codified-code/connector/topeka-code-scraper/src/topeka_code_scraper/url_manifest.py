from __future__ import annotations

import csv
from collections import OrderedDict
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable

from .models import GraphEdge, GraphNode, PageType
from .normalize import canonicalize_url, normalize_space, sha256_text, stable_page_id


SECTION_FETCH_LEVELS = {"section", "subsection"}

_LEVEL_RANK = {
    "code": 0,
    "index": 1,
    "title": 1,
    "appendix": 1,
    "division": 2,
    "chapter": 3,
    "article": 4,
    "subarticle": 5,
    "section": 6,
    "table": 6,
    "subsection": 7,
}

_PARSER_PAGE_TYPES: dict[str, PageType] = {
    "code": "code",
    "title": "title",
    "division": "division",
    "chapter": "chapter",
    "article": "article",
    "appendix": "appendix",
    "table": "table",
    "section": "section",
    "subsection": "section",
}


@dataclass(frozen=True)
class UrlManifestEntry:
    level: str
    id: str
    citation: str
    name: str
    parent_title: str
    parent_title_name: str
    parent_chapter: str
    url: str
    row_number: int

    @property
    def normalized_level(self) -> str:
        return self.level.strip().lower()

    @property
    def node_id(self) -> str:
        return stable_page_id(self.url)

    @property
    def parser_page_type(self) -> PageType | None:
        return _PARSER_PAGE_TYPES.get(self.normalized_level)


def parse_level_filter(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.strip().lower() for item in value.split(",") if item.strip()}


def load_url_manifest(path: Path, *, fetch_levels: set[str] | None = None) -> list[UrlManifestEntry]:
    all_entries = read_url_manifest(path)
    if not fetch_levels:
        return all_entries
    return [entry for entry in all_entries if entry.normalized_level in fetch_levels]


def read_url_manifest(path: Path) -> list[UrlManifestEntry]:
    entries: list[UrlManifestEntry] = []
    seen_urls: set[str] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or "url" not in {field.lower() for field in reader.fieldnames}:
            raise ValueError(f"{path} must be a CSV with a url column")
        for row_number, row in enumerate(reader, start=2):
            url = canonicalize_url(row_value(row, "url"))
            if not url:
                raise ValueError(f"{path}:{row_number}: URL is not under https://topeka.municipal.codes/TMC")
            if url in seen_urls:
                continue
            seen_urls.add(url)
            entries.append(
                UrlManifestEntry(
                    level=row_value(row, "level"),
                    id=row_value(row, "id"),
                    citation=row_value(row, "citation"),
                    name=row_value(row, "name"),
                    parent_title=row_value(row, "parent_title"),
                    parent_title_name=row_value(row, "parent_title_name"),
                    parent_chapter=row_value(row, "parent_chapter"),
                    url=url,
                    row_number=row_number,
                )
            )
    return entries


def row_value(row: dict[str, str | None], key: str) -> str:
    for candidate, value in row.items():
        if candidate.lower() == key:
            return normalize_space(value or "")
    return ""


def manifest_graph(entries: Iterable[UrlManifestEntry]) -> tuple[list[GraphNode], list[GraphEdge]]:
    nodes: OrderedDict[str, GraphNode] = OrderedDict()
    edges: OrderedDict[tuple[str, str, str], GraphEdge] = OrderedDict()
    stack: list[UrlManifestEntry] = []

    for entry in entries:
        level = entry.normalized_level
        rank = _LEVEL_RANK.get(level, 8)
        label = manifest_label(entry)
        nodes[entry.node_id] = GraphNode(
            id=entry.node_id,
            type=level or "manifest_node",
            label=label,
            properties={
                "url": entry.url,
                "source_url": entry.url,
                "citation_url": entry.url,
                "citation": entry.citation or None,
                "title": entry.name or None,
                "manifest_level": entry.level,
                "manifest_id": entry.id,
                "parent_title": entry.parent_title or None,
                "parent_title_name": entry.parent_title_name or None,
                "parent_chapter": entry.parent_chapter or None,
                "manifest_row_number": entry.row_number,
            },
        )

        while stack and _LEVEL_RANK.get(stack[-1].normalized_level, 8) >= rank:
            stack.pop()
        if stack:
            parent = stack[-1]
            key = (parent.node_id, entry.node_id, "CONTAINS")
            edges.setdefault(
                key,
                GraphEdge(
                    id="edge:" + sha256_text("|".join(key))[:20],
                    source=parent.node_id,
                    target=entry.node_id,
                    type="CONTAINS",
                    properties={
                        "source": "url_manifest",
                        "order": entry.row_number,
                        "source_url": parent.url,
                        "citation_url": parent.url,
                    },
                ),
            )
        stack.append(entry)

    return list(nodes.values()), list(edges.values())


def manifest_label(entry: UrlManifestEntry) -> str:
    return normalize_space(f"{entry.citation} {entry.name}") or entry.url


def merge_graphs(
    manifest_nodes: list[GraphNode],
    manifest_edges: list[GraphEdge],
    parsed_nodes: list[GraphNode],
    parsed_edges: list[GraphEdge],
) -> tuple[list[GraphNode], list[GraphEdge]]:
    nodes: OrderedDict[str, GraphNode] = OrderedDict((node.id, node) for node in manifest_nodes)
    for node in parsed_nodes:
        existing = nodes.get(node.id)
        if existing:
            node.properties = {**existing.properties, **node.properties}
        nodes[node.id] = node

    edges: OrderedDict[tuple[str, str, str, str], GraphEdge] = OrderedDict()
    for edge in manifest_edges + parsed_edges:
        extra = "" if edge.type == "CONTAINS" else json.dumps(edge.properties, sort_keys=True)
        edges.setdefault((edge.source, edge.target, edge.type, extra), edge)
    return list(nodes.values()), list(edges.values())
