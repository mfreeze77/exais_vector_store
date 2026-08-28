from __future__ import annotations

import re
from collections import OrderedDict
from datetime import UTC, datetime
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, Tag

from .models import (
    AssetRecord,
    CodeSection,
    CodeVersion,
    ContentBlock,
    DefinitionRecord,
    LinkReference,
    OrdinanceHistory,
    ParsedPage,
    TableRecord,
    TocGraphEdge,
    TocGraphNode,
    PageType,
)
from .normalize import (
    BASE_URL,
    canonicalize_url,
    normalize_space,
    normalize_text,
    sha256_text,
    source_path,
    stable_child_id,
    stable_page_id,
)

_VERSION_RE = re.compile(
    r"The Topeka Municipal Code is current through Ordinance\s+(?P<ord>[^,]+),\s*passed\s+(?P<date>[^.]+)\.",
    re.I,
)
_SECTION_HEAD_RE = re.compile(r"^(?:§\s*)?(?P<citation>\d+(?:\.\d+){2,})\s*(?P<title>.*)$")
_TITLE_RE = re.compile(r"^Title\s+(?P<num>\S+)\s*(?P<title>.*)$", re.I)
_DIV_RE = re.compile(r"^Division\s+(?P<num>\S+)\.?\s*(?P<title>.*)$", re.I)
_CHAPTER_RE = re.compile(r"^(?:Ch\.?|Chapter)\s+(?P<num>\S+)\s*(?P<title>.*)$", re.I)
_ARTICLE_RE = re.compile(r"^Article\s+(?P<num>\S+)\s*(?P<title>.*)$", re.I)
_APPENDIX_RE = re.compile(r"^Appendix\s+(?P<num>\S+)[:.]?\s*(?P<title>.*)$", re.I)
_HISTORY_RE = re.compile(
    r"\bOrd(?:inance)?\.?(?:\s+No\.)?\s*(?P<ord>[A-Z]?\d{3,6}[A-Z]?)\b"
    r"(?:\s*§\s*(?P<section>[^,;)]+))?"
    r"(?:,\s*(?P<date>\d{1,2}-\d{1,2}-\d{2,4}))?",
    re.I,
)
_DEF_RE = re.compile(
    r"^[\u201c\"](?P<term>[^\u201d\"]+)[\u201d\"]"
    r"(?:\s+or\s+(?P<alias>[A-Za-z][A-Za-z0-9 .'-]{0,50}))?\s+means\b",
    re.I,
)
_SEE_DEF_RE = re.compile(r"^(?P<term>[A-Z][A-Za-z0-9 /&,'’-]{0,80})\.\s+See\s+[\u201c\"]", re.I)
_MARKER_RE = re.compile(r"^(?P<marker>(?:\([A-Za-z0-9ivxlcdm]+\)|[A-Z]\.|\d+\.|\([ivxlcdm]+\)))\s+")

_STOP_PREFIXES = (
    "The Topeka Municipal Code is current through",
    "Disclaimer: The City Clerk",
    "Hosted by ICC Code Solutions",
    "Privacy Policy",
    "Terms of Use",
    "City Website:",
    "View Full Table",
    "View Full Image",
    "View Full File",
)

_REMOVE_SELECTORS = (
    "script",
    "style",
    "noscript",
    "svg",
    "form",
    "button",
    "input",
    "select",
    "textarea",
)


class MunicipalCodeParser:
    def parse(
        self,
        url: str,
        html: str,
        retrieved_at: datetime | None = None,
        *,
        forced_page_type: PageType | None = None,
        forced_citation: str | None = None,
        forced_title: str | None = None,
    ) -> ParsedPage:
        retrieved_at = retrieved_at or datetime.now(UTC)
        canonical = canonicalize_url(url)
        if not canonical:
            raise ValueError(f"Not a Topeka Municipal Code URL: {url}")

        html_hash = sha256_text(html)
        soup = BeautifulSoup(html, "lxml")
        for selector in _REMOVE_SELECTORS:
            for tag in soup.select(selector):
                tag.decompose()

        root = soup.find("main") or soup.find(attrs={"role": "main"}) or soup.find("article") or soup.body or soup
        heading_tag = self._find_primary_heading(root, canonical)
        heading = normalize_space(heading_tag.get_text(" ", strip=True)) if heading_tag else self._fallback_heading(canonical)
        page_type, citation, title = self._classify(heading, canonical)
        page_type = forced_page_type or page_type
        citation = forced_citation or citation
        title = forced_title or title
        version = self._extract_version(root.get_text("\n", strip=True))
        internal_links = self._extract_internal_links(root)
        structural_edges = self._extract_nested_list_edges(root)
        toc_nodes, toc_edges = self._extract_toc_graph(root, canonical)

        section = None
        definitions: list[DefinitionRecord] = []
        if page_type == "section":
            section = self._parse_section(
                root=root,
                heading_tag=heading_tag,
                url=canonical,
                citation=citation or self._citation_from_path(canonical),
                title=title,
                version=version,
                retrieved_at=retrieved_at,
                html_hash=html_hash,
            )
            definitions = self._extract_definitions(section)
            section.definitions = [item.id for item in definitions]

        return ParsedPage(
            id=stable_page_id(canonical),
            url=canonical,
            path=source_path(canonical),
            page_type=page_type,
            citation=citation,
            title=title or heading,
            heading=heading,
            version=version,
            internal_links=internal_links,
            structural_edges=structural_edges,
            toc_nodes=toc_nodes,
            toc_edges=toc_edges,
            section=section,
            definitions=definitions,
            source_html_hash=html_hash,
        )

    def _find_primary_heading(self, root: Tag, url: str) -> Tag | None:
        headings = root.find_all(re.compile(r"^h[1-6]$"))
        if not headings:
            return None
        path_citation = self._citation_from_path(url)
        if path_citation:
            for tag in headings:
                text = normalize_space(tag.get_text(" ", strip=True))
                if path_citation in text:
                    return tag
        for tag in headings:
            text = normalize_space(tag.get_text(" ", strip=True))
            if text and text not in {"View Full Table", "View Full Image", "View Full File"}:
                return tag
        return headings[0]

    def _fallback_heading(self, url: str) -> str:
        suffix = source_path(url).removeprefix("/TMC").strip("/")
        return "TOPEKA MUNICIPAL CODE" if not suffix else suffix

    def _citation_from_path(self, url: str) -> str | None:
        suffix = source_path(url).removeprefix("/TMC/")
        return suffix if re.fullmatch(r"\d+(?:\.\d+){2,}", suffix) else None

    def _classify(self, heading: str, url: str) -> tuple[str, str | None, str]:
        if source_path(url) == "/TMC":
            return "code", None, "Topeka Municipal Code"
        for regex, page_type in [
            (_TITLE_RE, "title"),
            (_DIV_RE, "division"),
            (_CHAPTER_RE, "chapter"),
            (_ARTICLE_RE, "article"),
            (_APPENDIX_RE, "appendix"),
        ]:
            match = regex.match(heading)
            if match:
                num = normalize_space(match.group("num"))
                title = normalize_space(match.group("title")) or heading
                return page_type, num, title
        match = _SECTION_HEAD_RE.match(heading)
        if match:
            citation = match.group("citation")
            title = normalize_space(match.group("title").strip(" .\u2014-")) or citation
            return "section", citation, title
        path = source_path(url).removeprefix("/TMC/")
        if path.startswith("Ax"):
            return "appendix", path, heading
        if path.lower().startswith("tables"):
            return "table", path, heading
        return "container", path or None, heading

    def _extract_version(self, text: str) -> CodeVersion | None:
        match = _VERSION_RE.search(normalize_space(text))
        if not match:
            return None
        raw = match.group(0)
        return CodeVersion(
            ordinance=normalize_space(match.group("ord")),
            passed_date=normalize_space(match.group("date")),
            raw=raw,
        )

    def _extract_internal_links(self, root: Tag) -> list[str]:
        links: OrderedDict[str, None] = OrderedDict()
        for anchor in root.find_all("a", href=True):
            target = canonicalize_url(anchor.get("href"), BASE_URL)
            if target:
                links[target] = None
        return list(links)

    def _direct_anchor_url(self, li: Tag) -> str | None:
        nested_lists = set(li.find_all(["ul", "ol"], recursive=False))
        for anchor in li.find_all("a", href=True):
            if any(parent in nested_lists for parent in anchor.parents if isinstance(parent, Tag)):
                continue
            target = canonicalize_url(anchor.get("href"), BASE_URL)
            if target:
                return target
        return None

    def _extract_nested_list_edges(self, root: Tag) -> list[tuple[str, str]]:
        edges: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for li in root.find_all("li"):
            child = self._direct_anchor_url(li)
            if not child:
                continue
            parent_li = None
            parent_list = li.parent if isinstance(li.parent, Tag) else None
            if parent_list:
                parent_li = parent_list.find_parent("li")
            if not parent_li:
                continue
            parent = self._direct_anchor_url(parent_li)
            if parent and parent != child and (parent, child) not in seen:
                seen.add((parent, child))
                edges.append((parent, child))
        return edges


    def _anchor_descriptor(self, text: str, href: str, current_url: str) -> TocGraphNode | None:
        text = normalize_space(text)
        if not text:
            return None
        absolute = __import__("urllib.parse", fromlist=["urljoin"]).urljoin(BASE_URL, href)
        parts = urlsplit(absolute)
        canonical = canonicalize_url(absolute, BASE_URL)
        if not canonical:
            return None

        page_type = "container"
        citation: str | None = None
        label = text
        for regex, kind in [
            (_TITLE_RE, "title"),
            (_DIV_RE, "division"),
            (_CHAPTER_RE, "chapter"),
            (_ARTICLE_RE, "article"),
            (_APPENDIX_RE, "appendix"),
        ]:
            match = regex.match(text)
            if match:
                page_type = kind
                citation = normalize_space(match.group("num"))
                break
        else:
            sec = _SECTION_HEAD_RE.match(text)
            if sec:
                citation = sec.group("citation")
                page_type = "section" if citation.count(".") >= 2 else "chapter"
            else:
                numeric = re.match(r"^(?P<num>\d+(?:\.\d+)+)\s+", text)
                if numeric:
                    citation = numeric.group("num")
                    page_type = "section" if citation.count(".") >= 2 else "chapter"

        # If a distinct canonical page exists, use its stable page ID. If the link is
        # only a fragment on the current page (common for Divisions), create a virtual
        # deterministic hierarchy node so the graph does not flatten the structure.
        if canonical != current_url:
            node_id = stable_page_id(canonical)
            node_url = canonical
        elif parts.fragment and page_type != "container":
            node_id = stable_child_id(stable_page_id(current_url), page_type, citation or text)
            node_url = absolute
        else:
            return None

        return TocGraphNode(id=node_id, type=page_type, label=label, citation=citation, url=node_url)

    def _direct_toc_node(self, li: Tag, current_url: str) -> TocGraphNode | None:
        direct_nested = set(li.find_all(["ul", "ol"], recursive=False))
        for anchor in li.find_all("a", href=True):
            if any(parent in direct_nested for parent in anchor.parents if isinstance(parent, Tag)):
                continue
            node = self._anchor_descriptor(anchor.get_text(" ", strip=True), anchor.get("href"), current_url)
            if node:
                return node
        return None

    def _extract_toc_graph(self, root: Tag, current_url: str) -> tuple[list[TocGraphNode], list[TocGraphEdge]]:
        nodes: OrderedDict[str, TocGraphNode] = OrderedDict()
        edges: OrderedDict[tuple[str, str], TocGraphEdge] = OrderedDict()
        page_id = stable_page_id(current_url)
        order = 0
        for outer in root.find_all(["ul", "ol"]):
            if outer.find_parent(["ul", "ol"]):
                continue
            for li in outer.find_all("li"):
                node = self._direct_toc_node(li, current_url)
                if not node:
                    continue
                nodes[node.id] = node
                parent_li = li.parent.find_parent("li") if isinstance(li.parent, Tag) else None
                parent_node = self._direct_toc_node(parent_li, current_url) if parent_li else None
                source_id = parent_node.id if parent_node else page_id
                if parent_node:
                    nodes[parent_node.id] = parent_node
                key = (source_id, node.id)
                if source_id != node.id and key not in edges:
                    edges[key] = TocGraphEdge(source=source_id, target=node.id, order=order)
                    order += 1
        return list(nodes.values()), list(edges.values())

    def _parse_section(
        self,
        root: Tag,
        heading_tag: Tag | None,
        url: str,
        citation: str,
        title: str,
        version: CodeVersion | None,
        retrieved_at: datetime,
        html_hash: str,
    ) -> CodeSection:
        blocks = self._extract_blocks(root, heading_tag)
        text = normalize_text("\n\n".join(block.text for block in blocks if block.text))
        section_id = stable_page_id(url)
        references = self._extract_references(root, url, heading_tag)
        history = self._extract_history(text)
        tables = self._extract_tables(root, heading_tag)
        return CodeSection(
            id=section_id,
            citation=citation,
            title=title or citation,
            source_url=url,
            text=text,
            blocks=blocks,
            tables=tables,
            assets=self._extract_assets(root, heading_tag),
            references=references,
            ordinance_history=history,
            version=version,
            retrieved_at=retrieved_at,
            content_hash=sha256_text(text),
            source_html_hash=html_hash,
        )

    def _is_after_heading(self, tag: Tag, heading_tag: Tag | None) -> bool:
        if heading_tag is None:
            return True
        for candidate in heading_tag.find_all_next():
            if candidate is tag:
                return True
        return False

    def _extract_blocks(self, root: Tag, heading_tag: Tag | None) -> list[ContentBlock]:
        blocks: list[ContentBlock] = []
        order = 0
        candidates = root.find_all(["p", "li", "table"])
        for tag in candidates:
            if not self._is_after_heading(tag, heading_tag):
                continue
            if tag.name == "table":
                rows = []
                for tr in tag.find_all("tr"):
                    cells = [normalize_space(cell.get_text(" ", strip=True)) for cell in tr.find_all(["th", "td"])]
                    if cells:
                        rows.append(cells)
                text = "\n".join(" | ".join(cells) for cells in rows)
                text = normalize_text(text)
                if text:
                    blocks.append(ContentBlock(order=order, kind="table", text=text))
                    order += 1
                continue

            # Avoid nested list duplication: only keep the li's own text before a child list.
            if tag.name == "li" and tag.find(["ul", "ol"]):
                own_parts = []
                for child in tag.contents:
                    if isinstance(child, Tag) and child.name in {"ul", "ol"}:
                        break
                    own_parts.append(child.get_text(" ", strip=True) if isinstance(child, Tag) else str(child))
                raw = " ".join(own_parts)
            else:
                raw = tag.get_text(" ", strip=True)
            text = normalize_space(raw)
            if not text:
                continue
            if any(text.startswith(prefix) for prefix in _STOP_PREFIXES):
                break
            if text in {"Search Within This", "Loading…", "Loading..."}:
                continue
            marker = None
            match = _MARKER_RE.match(text)
            if match:
                marker = match.group("marker")
            kind = "list_item" if tag.name == "li" else "paragraph"
            blocks.append(ContentBlock(order=order, kind=kind, marker=marker, text=text))
            order += 1

        if blocks:
            return blocks

        # Fallback for unusual markup: plain text slicing between heading and footer marker.
        raw = root.get_text("\n", strip=True)
        lines = [normalize_space(line) for line in raw.splitlines() if normalize_space(line)]
        heading_text = normalize_space(heading_tag.get_text(" ", strip=True)) if heading_tag else None
        start = 0
        if heading_text and heading_text in lines:
            start = lines.index(heading_text) + 1
        for line in lines[start:]:
            if any(line.startswith(prefix) for prefix in _STOP_PREFIXES):
                break
            blocks.append(ContentBlock(order=len(blocks), text=line))
        return blocks

    def _extract_tables(self, root: Tag, heading_tag: Tag | None) -> list[TableRecord]:
        tables: list[TableRecord] = []
        for table in root.find_all("table"):
            if not self._is_after_heading(table, heading_tag):
                continue
            text = normalize_space(table.get_text(" ", strip=True))
            if any(text.startswith(prefix) for prefix in _STOP_PREFIXES):
                continue
            rows: list[list[str]] = []
            for tr in table.find_all("tr"):
                cells = [normalize_space(cell.get_text(" ", strip=True)) for cell in tr.find_all(["th", "td"])]
                if cells:
                    rows.append(cells)
            if rows:
                tables.append(TableRecord(order=len(tables), rows=rows))
        return tables

    def _extract_references(self, root: Tag, self_url: str, heading_tag: Tag | None) -> list[LinkReference]:
        refs: OrderedDict[str, LinkReference] = OrderedDict()
        for container in root.find_all(["p", "li", "table"]):
            if not self._is_after_heading(container, heading_tag):
                continue
            container_text = normalize_space(container.get_text(" ", strip=True))
            if any(container_text.startswith(prefix) for prefix in _STOP_PREFIXES):
                break
            for anchor in container.find_all("a", href=True):
                target = canonicalize_url(anchor.get("href"), BASE_URL)
                if not target or target == self_url:
                    continue
                text = normalize_space(anchor.get_text(" ", strip=True)) or None
                refs[target] = LinkReference(
                    citation=self._citation_from_path(target),
                    url=target,
                    target_id=stable_page_id(target),
                    text=text,
                )
        return list(refs.values())

    def _extract_assets(self, root: Tag, heading_tag: Tag | None) -> list[AssetRecord]:
        from urllib.parse import urljoin

        assets: OrderedDict[tuple[str, str], AssetRecord] = OrderedDict()
        for tag in root.find_all(["img", "a"]):
            if not self._is_after_heading(tag, heading_tag):
                continue
            if tag.name == "img" and tag.get("src"):
                url = urljoin(BASE_URL, tag.get("src"))
                label = normalize_space(tag.get("alt", "")) or None
                assets[("image", url)] = AssetRecord(type="image", url=url, label=label)
            elif tag.name == "a" and tag.get("href"):
                href = tag.get("href")
                lower = href.lower().split("?", 1)[0]
                if "/attachment/" in lower or lower.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".tif", ".tiff", ".png", ".jpg", ".jpeg")):
                    url = urljoin(BASE_URL, href)
                    label = normalize_space(tag.get_text(" ", strip=True)) or None
                    assets[("attachment", url)] = AssetRecord(type="attachment", url=url, label=label)
        return list(assets.values())

    def _extract_history(self, text: str) -> list[OrdinanceHistory]:
        history: list[OrdinanceHistory] = []
        seen: set[tuple[str, str | None, str | None]] = set()
        for match in _HISTORY_RE.finditer(text):
            key = (match.group("ord"), match.group("section"), match.group("date"))
            if key in seen:
                continue
            seen.add(key)
            history.append(
                OrdinanceHistory(
                    ordinance=normalize_space(match.group("ord")),
                    section=normalize_space(match.group("section")) if match.group("section") else None,
                    date=match.group("date"),
                    raw=normalize_space(match.group(0)),
                )
            )
        return history

    def _extract_definitions(self, section: CodeSection) -> list[DefinitionRecord]:
        paragraphs = [block.text for block in section.blocks if block.kind in {"paragraph", "list_item"}]
        definitions: list[DefinitionRecord] = []
        current_term: str | None = None
        current_aliases: list[str] = []
        current_parts: list[str] = []

        def flush() -> None:
            nonlocal current_term, current_aliases, current_parts
            if not current_term or not current_parts:
                current_term = None
                current_aliases = []
                current_parts = []
                return
            text = normalize_text("\n\n".join(current_parts))
            def_id = stable_child_id(section.id, "def", current_term)
            definitions.append(
                DefinitionRecord(
                    id=def_id,
                    section_id=section.id,
                    section_citation=section.citation,
                    term=current_term,
                    aliases=current_aliases,
                    text=text,
                    source_url=section.source_url,
                    content_hash=sha256_text(text),
                )
            )
            current_term = None
            current_aliases = []
            current_parts = []

        for paragraph in paragraphs:
            match = _DEF_RE.match(paragraph)
            see_match = _SEE_DEF_RE.match(paragraph)
            if match or see_match:
                flush()
                if match:
                    current_term = normalize_space(match.group("term"))
                    alias = match.group("alias")
                    current_aliases = [normalize_space(alias)] if alias else []
                else:
                    current_term = normalize_space(see_match.group("term"))
                    current_aliases = []
                current_parts = [paragraph]
            elif current_term:
                if re.match(r"^(?:Cross References?:|State law references?:|Editor[’\']s Note:|\(?Ord\.|Formerly\b)", paragraph, re.I):
                    flush()
                else:
                    current_parts.append(paragraph)
        flush()
        return definitions
