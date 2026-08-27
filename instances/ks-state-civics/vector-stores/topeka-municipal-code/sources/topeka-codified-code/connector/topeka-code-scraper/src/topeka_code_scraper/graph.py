from __future__ import annotations

from collections import OrderedDict

from .models import GraphEdge, GraphNode, ParsedPage
from .normalize import sha256_text, stable_child_id, stable_page_id


class GraphBuilder:
    def build(self, pages: list[ParsedPage]) -> tuple[list[GraphNode], list[GraphEdge]]:
        page_by_url = {page.url: page for page in pages}
        nodes: OrderedDict[str, GraphNode] = OrderedDict()
        edges: OrderedDict[tuple[str, str, str, str], GraphEdge] = OrderedDict()

        code_id = "ks-topeka:jurisdiction"
        nodes[code_id] = GraphNode(
            id=code_id,
            type="jurisdiction",
            label="City of Topeka, Kansas",
            properties={"state": "KS"},
        )

        for page in pages:
            nodes[page.id] = GraphNode(
                id=page.id,
                type=page.page_type,
                label=self._page_label(page),
                properties={
                    "url": page.url,
                    "source_url": page.url,
                    "citation_url": page.url,
                    "citation": page.citation,
                    "title": page.title,
                    "source_html_hash": page.source_html_hash,
                    "version": page.version.model_dump(mode="json") if page.version else None,
                },
            )
            if page.section:
                nodes[page.id].properties.update({
                    "content_hash": page.section.content_hash,
                    "text_chars": len(page.section.text),
                })

        # Add virtual/in-page TOC nodes (for example Divisions represented by fragments).
        for page in pages:
            for toc_node in page.toc_nodes:
                if toc_node.id not in nodes:
                    nodes[toc_node.id] = GraphNode(
                        id=toc_node.id,
                        type=toc_node.type,
                        label=toc_node.label,
                        properties={
                            "url": toc_node.url,
                            "source_url": toc_node.url,
                            "citation_url": toc_node.url,
                            "citation": toc_node.citation,
                            "virtual": True,
                        },
                    )
            for toc_edge in page.toc_edges:
                self._add_edge(
                    edges,
                    toc_edge.source,
                    toc_edge.target,
                    "CONTAINS",
                    {"order": toc_edge.order, "source": "toc"},
                )

        root = next((p for p in pages if p.page_type == "code"), None)
        if root:
            self._add_edge(edges, code_id, root.id, "CONTAINS")

        # Nested TOC relations are the highest-quality hierarchy signal.
        structural_pairs: set[tuple[str, str]] = set()
        for page in pages:
            for parent_url, child_url in page.structural_edges:
                parent = page_by_url.get(parent_url)
                child = page_by_url.get(child_url)
                if parent and child:
                    structural_pairs.add((parent.id, child.id))
                    self._add_edge(edges, parent.id, child.id, "CONTAINS")

        # Fallback containment from listing pages to immediate linked descendants.
        for page in pages:
            if page.page_type == "section":
                continue
            for target_url in page.internal_links:
                target = page_by_url.get(target_url)
                if not target or target.id == page.id:
                    continue
                if self._looks_structural(page, target) and (page.id, target.id) not in structural_pairs:
                    if not self._has_better_parent(target.id, page.id, structural_pairs, page_by_url):
                        self._add_edge(edges, page.id, target.id, "CONTAINS")

        for page in pages:
            if not page.section:
                continue
            for ref in page.section.references:
                if ref.target_id not in nodes:
                    nodes[ref.target_id] = GraphNode(
                        id=ref.target_id,
                        type="reference_target",
                        label=ref.citation or ref.text or ref.url,
                        properties={
                            "url": ref.url,
                            "source_url": ref.url,
                            "citation_url": ref.url,
                            "citation": ref.citation,
                        },
                    )
                self._add_edge(
                    edges,
                    page.section.id,
                    ref.target_id,
                    "REFERENCES",
                    {
                        "text": ref.text,
                        "citation": ref.citation,
                        "source_url": page.section.source_url,
                        "citation_url": page.section.source_url,
                        "target_url": ref.url,
                    },
                )

            for definition in page.definitions:
                nodes[definition.id] = GraphNode(
                    id=definition.id,
                    type="definition",
                    label=definition.term,
                    properties={
                        "term": definition.term,
                        "aliases": definition.aliases,
                        "text": definition.text,
                        "citation": definition.section_citation,
                        "source_url": definition.source_url,
                        "citation_url": definition.source_url,
                        "content_hash": definition.content_hash,
                    },
                )
                self._add_edge(
                    edges,
                    page.section.id,
                    definition.id,
                    "DEFINES",
                    {
                        "source_url": page.section.source_url,
                        "citation_url": page.section.source_url,
                    },
                )

            for hist in page.section.ordinance_history:
                ord_id = stable_child_id("ks-topeka", "ordinance", hist.ordinance)
                if ord_id not in nodes:
                    nodes[ord_id] = GraphNode(
                        id=ord_id,
                        type="ordinance",
                        label=f"Ordinance {hist.ordinance}",
                        properties={
                            "ordinance": hist.ordinance,
                            "date": hist.date,
                            "observed_in_section_url": page.section.source_url,
                        },
                    )
                self._add_edge(
                    edges,
                    page.section.id,
                    ord_id,
                    "HAS_ORDINANCE_HISTORY",
                    {
                        "section": hist.section,
                        "date": hist.date,
                        "raw": hist.raw,
                        "source_url": page.section.source_url,
                        "citation_url": page.section.source_url,
                    },
                    dedupe_key=f"{hist.ordinance}|{hist.section or ''}|{hist.date or ''}|{hist.raw}",
                )

        return list(nodes.values()), list(edges.values())

    def _page_label(self, page: ParsedPage) -> str:
        return f"{page.citation} {page.title}".strip() if page.citation else page.title

    def _rank(self, page_type: str) -> int:
        return {
            "code": 0,
            "title": 1,
            "division": 2,
            "chapter": 3,
            "article": 4,
            "appendix": 2,
            "table": 2,
            "container": 4,
            "section": 5,
            "unknown": 5,
        }.get(page_type, 5)

    def _looks_structural(self, parent: ParsedPage, child: ParsedPage) -> bool:
        if self._rank(child.page_type) <= self._rank(parent.page_type):
            return False
        if parent.path == "/TMC":
            return child.page_type in {"title", "appendix", "table"}
        parent_token = parent.path.removeprefix("/TMC/")
        child_token = child.path.removeprefix("/TMC/")
        return child_token.startswith(parent_token)

    def _has_better_parent(
        self,
        child_id: str,
        candidate_parent_id: str,
        structural_pairs: set[tuple[str, str]],
        page_by_url: dict[str, ParsedPage],
    ) -> bool:
        candidate = next((p for p in page_by_url.values() if p.id == candidate_parent_id), None)
        if not candidate:
            return False
        for parent_id, existing_child in structural_pairs:
            if existing_child != child_id:
                continue
            existing = next((p for p in page_by_url.values() if p.id == parent_id), None)
            if existing and self._rank(existing.page_type) > self._rank(candidate.page_type):
                return True
        return False

    def _add_edge(
        self,
        edges: OrderedDict[tuple[str, str, str, str], GraphEdge],
        source: str,
        target: str,
        edge_type: str,
        properties: dict | None = None,
        dedupe_key: str | None = None,
    ) -> None:
        key = (source, target, edge_type, dedupe_key or "")
        if key in edges:
            return
        edge_id = f"edge:{sha256_text('|'.join(key))[:20]}"
        edges[key] = GraphEdge(
            id=edge_id,
            source=source,
            target=target,
            type=edge_type,  # type: ignore[arg-type]
            properties=properties or {},
        )
