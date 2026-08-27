from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


PageType = Literal[
    "code",
    "title",
    "division",
    "chapter",
    "article",
    "appendix",
    "table",
    "section",
    "container",
    "unknown",
]


class CodeVersion(BaseModel):
    ordinance: str | None = None
    passed_date: str | None = None
    raw: str | None = None


class LinkReference(BaseModel):
    citation: str | None = None
    url: str
    target_id: str
    text: str | None = None


class OrdinanceHistory(BaseModel):
    ordinance: str
    section: str | None = None
    date: str | None = None
    raw: str


class ContentBlock(BaseModel):
    order: int
    kind: Literal["paragraph", "list_item", "table", "heading"] = "paragraph"
    marker: str | None = None
    text: str


class AssetRecord(BaseModel):
    type: Literal["image", "attachment"]
    url: str
    label: str | None = None


class TableRecord(BaseModel):
    order: int
    rows: list[list[str]] = Field(default_factory=list)


class DefinitionRecord(BaseModel):
    id: str
    jurisdiction_id: str = "ks-topeka"
    code: str = "TMC"
    section_id: str
    section_citation: str
    term: str
    aliases: list[str] = Field(default_factory=list)
    text: str
    source_url: str
    content_hash: str


class CodeSection(BaseModel):
    id: str
    jurisdiction_id: str = "ks-topeka"
    jurisdiction_name: str = "City of Topeka, Kansas"
    code: str = "TMC"
    citation: str
    title: str
    source_url: str
    page_type: Literal["section"] = "section"
    text: str
    blocks: list[ContentBlock] = Field(default_factory=list)
    tables: list[TableRecord] = Field(default_factory=list)
    assets: list[AssetRecord] = Field(default_factory=list)
    references: list[LinkReference] = Field(default_factory=list)
    ordinance_history: list[OrdinanceHistory] = Field(default_factory=list)
    definitions: list[str] = Field(default_factory=list, description="Definition node IDs")
    version: CodeVersion | None = None
    retrieved_at: datetime
    content_hash: str
    source_html_hash: str


class TocGraphNode(BaseModel):
    id: str
    type: str
    label: str
    citation: str | None = None
    url: str | None = None


class TocGraphEdge(BaseModel):
    source: str
    target: str
    order: int = 0


class ParsedPage(BaseModel):
    id: str
    url: str
    path: str
    page_type: PageType
    citation: str | None = None
    title: str
    heading: str
    version: CodeVersion | None = None
    internal_links: list[str] = Field(default_factory=list)
    structural_edges: list[tuple[str, str]] = Field(default_factory=list)
    toc_nodes: list[TocGraphNode] = Field(default_factory=list)
    toc_edges: list[TocGraphEdge] = Field(default_factory=list)
    section: CodeSection | None = None
    definitions: list[DefinitionRecord] = Field(default_factory=list)
    source_html_hash: str


class GraphNode(BaseModel):
    id: str
    type: str
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    type: Literal["CONTAINS", "REFERENCES", "DEFINES", "HAS_ORDINANCE_HISTORY"]
    properties: dict[str, Any] = Field(default_factory=dict)


class CrawlReport(BaseModel):
    started_at: datetime
    finished_at: datetime
    root_url: str
    pages_seen: int
    pages_fetched: int
    pages_failed: int
    section_count: int
    definition_count: int
    node_count: int
    edge_count: int
    failures: list[dict[str, str]] = Field(default_factory=list)
    fetcher: str = "http"
