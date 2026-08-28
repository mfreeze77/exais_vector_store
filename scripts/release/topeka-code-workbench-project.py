#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from topeka_pipeline_common import read_jsonl, sha256_text, write_json, write_jsonl


CANONICAL_DOCUMENT_SCHEMA = "https://schemas.statecivics.ai/legislation/document/1-0-0"
WORKBENCH_PROJECTION_SCHEMA = "exais.topeka.municipal_code.workbench_projection.v1"
WORKBENCH_COMPONENT_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_URL,
    "https://schemas.exais.ai/exais-vector-store/topeka-municipal-code/workbench-component/v1",
)
DEFAULT_ROOT_KEY = "ks-topeka:tmc:root"
DEFAULT_ROOT_URL = "https://topeka.municipal.codes/TMC"


def stable_uuid(value: str) -> str:
    return str(uuid.uuid5(WORKBENCH_COMPONENT_NAMESPACE, value))


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return sha256_text(canonical_json_bytes(value).decode("utf-8"))


def file_sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_workbench_projection(
    source_output: Path,
    *,
    jurisdiction_id: str = "ks-topeka",
    code: str = "TMC",
    session: str = "municipal-code-current",
    document_title: str = "Topeka Municipal Code",
) -> dict[str, Any]:
    sections = read_jsonl(source_output / "sections.jsonl")
    definitions = read_jsonl(source_output / "definitions.jsonl") if (source_output / "definitions.jsonl").exists() else []
    nodes = read_jsonl(source_output / "nodes.jsonl") if (source_output / "nodes.jsonl").exists() else []
    edges = read_jsonl(source_output / "edges.jsonl") if (source_output / "edges.jsonl").exists() else []
    url_manifest = read_jsonl(source_output / "url-manifest.jsonl") if (source_output / "url-manifest.jsonl").exists() else []
    crawl_report = load_json(source_output / "crawl_report.json")
    quality_report = load_json(source_output / "quality-report.json")

    sections_by_key = {str(row.get("id") or ""): row for row in sections if row.get("id")}
    definitions_by_section: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in definitions:
        section_key = str(row.get("section_id") or "")
        if section_key:
            definitions_by_section[section_key].append(row)

    node_map = manifest_nodes(url_manifest)
    for row in nodes:
        node_id = str(row.get("id") or "")
        if node_id:
            node_map[node_id] = row
    for section_key, section in sections_by_key.items():
        node_map.setdefault(section_key, node_from_section(section))

    contains_edges = [
        row
        for row in edges
        if str(row.get("type") or "") == "CONTAINS" and row.get("source") and row.get("target")
    ]
    parents_by_target: dict[str, list[dict[str, Any]]] = defaultdict(list)
    children_by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in contains_edges:
        parents_by_target[str(edge["target"])].append(edge)
        children_by_source[str(edge["source"])].append(edge)

    included_keys = included_component_keys(set(sections_by_key), parents_by_target)
    if sections and not included_keys:
        included_keys.update(sections_by_key)
    if DEFAULT_ROOT_KEY in node_map and included_keys:
        included_keys.add(DEFAULT_ROOT_KEY)

    parent_key_by_key = parent_key_map(included_keys, parents_by_target)
    ordinal_by_key = ordinal_map(included_keys, children_by_source)

    component_rows: list[dict[str, Any]] = []
    for key in sorted(included_keys, key=lambda item: component_sort_key(item, node_map, ordinal_by_key)):
        section = sections_by_key.get(key)
        component_rows.append(hierarchy_component_row(
            key=key,
            node=node_map.get(key) or {"id": key, "type": "container", "label": key, "properties": {}},
            section=section,
            parent_key=parent_key_by_key.get(key),
            ordinal=ordinal_by_key.get(key, 0),
            jurisdiction_id=jurisdiction_id,
            code=code,
        ))
        if section:
            component_rows.extend(block_component_rows(section))
            component_rows.extend(definition_component_rows(section, definitions_by_section.get(key, [])))

    relation_rows = relation_components(component_rows)
    relation_rows.extend(reference_relations(sections, included_keys))
    relation_rows.extend(definition_relations(definitions, included_keys))
    relation_rows.extend(ordinance_history_relations(sections, included_keys))

    canonical_components, subtree_hashes = canonical_component_tree(component_rows)
    component_projection = projection_rows(component_rows, subtree_hashes)
    references = canonical_references(sections, included_keys)
    slices = slice_rows(component_rows, sections_by_key, parent_key_by_key)
    document_sha = document_source_hash(sections, url_manifest, crawl_report)
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    version_key = f"{WORKBENCH_PROJECTION_SCHEMA}|{jurisdiction_id}|{code}|{document_sha}|{len(sections)}"
    canonical_document = {
        "schema": CANONICAL_DOCUMENT_SCHEMA,
        "documentId": stable_uuid(f"{jurisdiction_id}:{code}:document"),
        "versionId": stable_uuid(f"{version_key}:version"),
        "jurisdiction": jurisdiction_id,
        "session": session,
        "documentType": "other",
        "lifecycleStage": "source-import-projection",
        "metadata": {
            "title": document_title,
            "shortTitle": code,
            "classification": "PUBLIC",
            "createdAt": generated_at,
            "createdBy": "scripts/release/topeka-code-workbench-project.py",
            "source": {
                "method": "import-other",
                "sourceUri": DEFAULT_ROOT_URL,
                "sourceSha256": document_sha,
                "importer": "topeka-code-workbench-project.py",
                "importerVersion": "1",
                "warnings": [],
            },
            "subjects": ["municipal-code", "topeka", "kansas"],
            "extensions": {
                "exais:projection_schema": WORKBENCH_PROJECTION_SCHEMA,
                "exais:source_output": str(source_output),
            },
        },
        "body": canonical_components,
        "references": references,
        "extensions": {
            "exais:source_schema": "topeka_municipal_code_v1",
            "exais:component_key_namespace": "ks-topeka:tmc",
            "exais:source_output": str(source_output),
            "exais:projection_quality_required_before_workbench_import": True,
        },
    }

    quality = validate_projection(component_rows, relation_rows, sections)
    manifest = {
        "schema_version": 1,
        "projection_schema": WORKBENCH_PROJECTION_SCHEMA,
        "source_output": str(source_output),
        "generated_at": generated_at,
        "boundary": "Projection-only. This script reads saved Topeka artifacts and writes workbench JSON; it does not ingest, vectorize, or write to Qdrant/Postgres/MinIO.",
        "canonical_document_schema": CANONICAL_DOCUMENT_SCHEMA,
        "document_id": canonical_document["documentId"],
        "version_id": canonical_document["versionId"],
        "source_sha256": document_sha,
        "source_crawl_report": {
            "pages_fetched": crawl_report.get("pages_fetched"),
            "pages_failed": crawl_report.get("pages_failed"),
            "section_count": crawl_report.get("section_count"),
            "fetcher": crawl_report.get("fetcher"),
        },
        "source_quality": {
            "artifact_quality_passed": quality_report.get("passed"),
            "vectorization_allowed": quality_report.get("vectorization_allowed"),
        },
        "counts": {
            "source_sections": len(sections),
            "components": len(component_rows),
            "component_projection_rows": len(component_projection),
            "relations": len(relation_rows),
            "references": len(references),
            "slices": len(slices),
        },
        "quality": quality,
    }
    return {
        "canonical_document": canonical_document,
        "components": component_rows,
        "component_projection": component_projection,
        "relations": relation_rows,
        "slices": slices,
        "manifest": manifest,
    }


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"expected JSON object: {path}")
    return loaded


def manifest_nodes(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    nodes: dict[str, dict[str, Any]] = {}
    for row in rows:
        node_id = str(row.get("node_id") or "")
        if not node_id:
            continue
        nodes[node_id] = {
            "id": node_id,
            "type": str(row.get("parser_page_type") or row.get("level") or "container").lower(),
            "label": label_from_manifest(row),
            "properties": {
                "url": row.get("url"),
                "source_url": row.get("url"),
                "citation_url": row.get("url"),
                "citation": row.get("citation"),
                "title": row.get("name"),
                "manifest_level": row.get("level"),
                "manifest_id": row.get("id"),
                "parent_title": row.get("parent_title"),
                "parent_title_name": row.get("parent_title_name"),
                "parent_chapter": row.get("parent_chapter"),
                "manifest_row_number": row.get("row_number"),
            },
        }
    return nodes


def label_from_manifest(row: dict[str, Any]) -> str:
    citation = str(row.get("citation") or "").strip()
    name = str(row.get("name") or "").strip()
    return " ".join(part for part in (citation, name) if part).strip() or str(row.get("node_id") or "")


def node_from_section(section: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": section["id"],
        "type": "section",
        "label": " ".join(part for part in (section.get("citation"), section.get("title")) if part),
        "properties": {
            "url": section.get("source_url"),
            "source_url": section.get("source_url"),
            "citation_url": section.get("source_url"),
            "citation": section.get("citation"),
            "title": section.get("title"),
            "content_hash": section.get("content_hash"),
            "source_html_hash": section.get("source_html_hash"),
        },
    }


def included_component_keys(section_keys: set[str], parents_by_target: dict[str, list[dict[str, Any]]]) -> set[str]:
    included = set(section_keys)
    stack = list(section_keys)
    while stack:
        current = stack.pop()
        for edge in sorted(parents_by_target.get(current, []), key=edge_sort_key):
            parent = str(edge.get("source") or "")
            if parent and parent not in included:
                included.add(parent)
                stack.append(parent)
    return included


def parent_key_map(included_keys: set[str], parents_by_target: dict[str, list[dict[str, Any]]]) -> dict[str, str | None]:
    parents: dict[str, str | None] = {}
    for key in included_keys:
        choices = [
            str(edge.get("source") or "")
            for edge in sorted(parents_by_target.get(key, []), key=edge_sort_key)
            if str(edge.get("source") or "") in included_keys
        ]
        parents[key] = choices[0] if choices else None
    return parents


def ordinal_map(included_keys: set[str], children_by_source: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    ordinals: dict[str, int] = {}
    for parent, edges in children_by_source.items():
        children = [
            str(edge.get("target") or "")
            for edge in sorted(edges, key=edge_sort_key)
            if str(edge.get("target") or "") in included_keys
        ]
        for ordinal, child in enumerate(children):
            ordinals[child] = ordinal
    for key in included_keys:
        ordinals.setdefault(key, 0)
    return ordinals


def edge_sort_key(edge: dict[str, Any]) -> tuple[int, str, str]:
    props = edge.get("properties") if isinstance(edge.get("properties"), dict) else {}
    order = props.get("order", edge.get("order", 0))
    try:
        numeric_order = int(order)
    except (TypeError, ValueError):
        numeric_order = 0
    return numeric_order, str(edge.get("source") or ""), str(edge.get("target") or "")


def component_sort_key(key: str, nodes: dict[str, dict[str, Any]], ordinals: dict[str, int]) -> tuple[int, int, str]:
    props = nodes.get(key, {}).get("properties")
    if not isinstance(props, dict):
        props = {}
    row_number = props.get("manifest_row_number")
    try:
        row_order = int(row_number)
    except (TypeError, ValueError):
        row_order = 10_000_000
    return row_order, ordinals.get(key, 0), key


def hierarchy_component_row(
    *,
    key: str,
    node: dict[str, Any],
    section: dict[str, Any] | None,
    parent_key: str | None,
    ordinal: int,
    jurisdiction_id: str,
    code: str,
) -> dict[str, Any]:
    props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    source_url = first_text(section, "source_url") if section else first_text(props, "source_url", "url", "citation_url")
    citation = first_text(section, "citation") if section else first_text(props, "citation")
    title = first_text(section, "title") if section else first_text(props, "title")
    source_hash = first_text(section, "source_html_hash") if section else None
    content_hash = first_text(section, "content_hash") if section else None
    text = None
    if section and not section.get("blocks"):
        text = first_text(section, "text")
        content_hash = content_hash or sha256_text(text)
    return compact({
        "schema": "exais.workbench_component.v1",
        "source_component_key": key,
        "workbench_component_id": stable_uuid(key),
        "parent_source_component_key": parent_key,
        "parent_workbench_component_id": stable_uuid(parent_key) if parent_key else None,
        "type": component_type(str(node.get("type") or props.get("manifest_level") or "container")),
        "ordinal": ordinal,
        "number": citation,
        "heading": title,
        "text": text,
        "citation": citation,
        "source_url": source_url,
        "citation_url": source_url,
        "source_html_hash": source_hash,
        "content_hash": content_hash,
        "attributes": compact({
            "jurisdiction_id": jurisdiction_id,
            "code": code,
            "source_record_type": "section" if section else "hierarchy",
            "manifest_level": props.get("manifest_level"),
            "manifest_id": props.get("manifest_id"),
            "manifest_row_number": props.get("manifest_row_number"),
            "text_chars": len(str(section.get("text") or "")) if section else None,
        }),
    })


def block_component_rows(section: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    blocks = section.get("blocks") if isinstance(section.get("blocks"), list) else []
    if not blocks and str(section.get("text") or "").strip():
        blocks = [{"order": 0, "kind": "paragraph", "marker": None, "text": section["text"]}]
    marker_counts = Counter(normalize_marker(block.get("marker")) for block in blocks if block.get("marker"))
    for order, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        text = str(block.get("text") or "").strip()
        if not text:
            continue
        block_order = int_value(block.get("order"), default=order)
        marker = str(block.get("marker") or "").strip() or None
        marker_slug = normalize_marker(marker)
        if marker_slug and marker_counts[marker_slug] == 1:
            suffix = f"marker:{marker_slug}"
        else:
            suffix = f"block:{block_order:04d}"
        key = f"{section['id']}:{suffix}"
        citation = block_citation(str(section.get("citation") or ""), marker)
        rows.append(compact({
            "schema": "exais.workbench_component.v1",
            "source_component_key": key,
            "workbench_component_id": stable_uuid(key),
            "parent_source_component_key": section["id"],
            "parent_workbench_component_id": stable_uuid(section["id"]),
            "type": block_component_type(str(block.get("kind") or "paragraph")),
            "ordinal": block_order,
            "number": marker,
            "heading": None,
            "text": text,
            "citation": citation,
            "source_url": section.get("source_url"),
            "citation_url": section.get("source_url"),
            "source_html_hash": section.get("source_html_hash"),
            "content_hash": sha256_text(text),
            "attributes": compact({
                "source_record_type": "block",
                "source_block_kind": block.get("kind") or "paragraph",
                "source_block_order": block_order,
                "marker": marker,
                "section_id": section.get("id"),
                "section_citation": section.get("citation"),
            }),
        }))
    return rows


def definition_component_rows(section: dict[str, Any], definitions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    block_count = len(section.get("blocks") or [])
    for offset, definition in enumerate(sorted(definitions, key=lambda row: str(row.get("term") or ""))):
        key = str(definition.get("id") or "")
        if not key:
            continue
        text = str(definition.get("text") or "").strip()
        rows.append(compact({
            "schema": "exais.workbench_component.v1",
            "source_component_key": key,
            "workbench_component_id": stable_uuid(key),
            "parent_source_component_key": section["id"],
            "parent_workbench_component_id": stable_uuid(section["id"]),
            "type": "definition",
            "ordinal": block_count + offset,
            "number": definition.get("term"),
            "heading": definition.get("term"),
            "text": text,
            "citation": section.get("citation"),
            "source_url": definition.get("source_url") or section.get("source_url"),
            "citation_url": definition.get("source_url") or section.get("source_url"),
            "source_html_hash": section.get("source_html_hash"),
            "content_hash": definition.get("content_hash") or sha256_text(text),
            "attributes": compact({
                "source_record_type": "definition",
                "term": definition.get("term"),
                "aliases": definition.get("aliases") if isinstance(definition.get("aliases"), list) else [],
                "section_id": section.get("id"),
                "section_citation": section.get("citation"),
            }),
        }))
    return rows


def component_type(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    return {
        "code": "code",
        "index": "index",
        "title": "title",
        "division": "division",
        "chapter": "chapter",
        "article": "article",
        "subarticle": "article",
        "appendix": "appendix",
        "table": "table",
        "section": "section",
        "subsection": "subsection",
        "container": "container",
        "unknown": "container",
    }.get(normalized, normalized or "container")


def block_component_type(value: str) -> str:
    normalized = value.strip().lower().replace("_", "-")
    if normalized == "list-item":
        return "paragraph"
    if normalized in {"paragraph", "table", "heading"}:
        return normalized
    return "paragraph"


def first_text(source: dict[str, Any] | None, *keys: str) -> str | None:
    if not source:
        return None
    for key in keys:
        value = source.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def normalize_marker(marker: str | None) -> str:
    if not marker:
        return ""
    return "".join(ch for ch in marker.lower() if ch.isalnum())[:64]


def block_citation(section_citation: str, marker: str | None) -> str | None:
    if not section_citation:
        return None
    if not marker:
        return section_citation
    return f"{section_citation}{marker.strip()}"


def int_value(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def compact(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if value is not None}


def relation_components(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for component in components:
        parent_key = component.get("parent_source_component_key")
        if not parent_key:
            continue
        rows.append({
            "id": relation_id("CONTAINS", str(parent_key), str(component["source_component_key"]), str(component.get("ordinal", 0))),
            "type": "CONTAINS",
            "source_component_key": parent_key,
            "source_workbench_component_id": stable_uuid(str(parent_key)),
            "target_component_key": component["source_component_key"],
            "target_workbench_component_id": component["workbench_component_id"],
            "properties": {
                "order": component.get("ordinal", 0),
                "source": "workbench_projection",
            },
        })
    return rows


def reference_relations(sections: list[dict[str, Any]], included_keys: set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for section in sections:
        source_key = str(section.get("id") or "")
        if source_key not in included_keys:
            continue
        references = section.get("references") if isinstance(section.get("references"), list) else []
        for ref in references:
            if not isinstance(ref, dict):
                continue
            target_key = str(ref.get("target_id") or "")
            rows.append(compact({
                "id": relation_id("REFERENCES", source_key, target_key or str(ref.get("url") or ""), str(ref.get("text") or "")),
                "type": "REFERENCES",
                "source_component_key": source_key,
                "source_workbench_component_id": stable_uuid(source_key),
                "target_component_key": target_key or None,
                "target_workbench_component_id": stable_uuid(target_key) if target_key in included_keys else None,
                "properties": compact({
                    "citation": ref.get("citation"),
                    "url": ref.get("url"),
                    "citation_url": ref.get("url"),
                    "text": ref.get("text"),
                    "target_in_projection": target_key in included_keys,
                    "source": "section_reference",
                }),
            }))
    return rows


def definition_relations(definitions: list[dict[str, Any]], included_keys: set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for definition in definitions:
        source_key = str(definition.get("section_id") or "")
        target_key = str(definition.get("id") or "")
        if source_key not in included_keys or not target_key:
            continue
        rows.append({
            "id": relation_id("DEFINES", source_key, target_key, str(definition.get("term") or "")),
            "type": "DEFINES",
            "source_component_key": source_key,
            "source_workbench_component_id": stable_uuid(source_key),
            "target_component_key": target_key,
            "target_workbench_component_id": stable_uuid(target_key),
            "properties": {
                "term": definition.get("term"),
                "citation_url": definition.get("source_url"),
                "source": "definition_extraction",
            },
        })
    return rows


def ordinance_history_relations(sections: list[dict[str, Any]], included_keys: set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for section in sections:
        source_key = str(section.get("id") or "")
        if source_key not in included_keys:
            continue
        for ordinal, history in enumerate(section.get("ordinance_history") or []):
            if not isinstance(history, dict) or not history.get("ordinance"):
                continue
            target_key = f"ks-topeka:ordinance:{history['ordinance']}"
            rows.append({
                "id": relation_id("HAS_ORDINANCE_HISTORY", source_key, target_key, str(ordinal), str(history.get("raw") or "")),
                "type": "HAS_ORDINANCE_HISTORY",
                "source_component_key": source_key,
                "source_workbench_component_id": stable_uuid(source_key),
                "target_component_key": target_key,
                "target_workbench_component_id": stable_uuid(target_key),
                "properties": compact({
                    "ordinance": history.get("ordinance"),
                    "section": history.get("section"),
                    "date": history.get("date"),
                    "raw": history.get("raw"),
                    "citation_url": section.get("source_url"),
                    "source": "ordinance_history_extraction",
                }),
            })
    return rows


def relation_id(kind: str, *parts: str) -> str:
    return f"rel:{sha256_text('|'.join([kind, *parts]))[:24]}"


def canonical_component_tree(components: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    by_key = {str(row["source_component_key"]): canonical_component(row) for row in components}
    parent_by_key = {str(row["source_component_key"]): row.get("parent_source_component_key") for row in components}
    source_rows = {str(row["source_component_key"]): row for row in components}
    children: dict[str | None, list[str]] = defaultdict(list)
    for key, parent in parent_by_key.items():
        children[parent].append(key)
    for parent, child_keys in children.items():
        child_keys.sort(key=lambda key: (int_value(source_rows[key].get("ordinal")), key))
    for parent, child_keys in children.items():
        if parent is None:
            continue
        if parent not in by_key:
            continue
        by_key[parent]["children"] = [by_key[key] for key in child_keys if key in by_key]
    roots = [by_key[key] for key in children.get(None, []) if key in by_key]
    if not roots and DEFAULT_ROOT_KEY in by_key:
        roots = [by_key[DEFAULT_ROOT_KEY]]

    subtree_hashes: dict[str, str] = {}
    for key, component in by_key.items():
        subtree_hashes[key] = canonical_sha256(component)
    return roots, subtree_hashes


def canonical_component(row: dict[str, Any]) -> dict[str, Any]:
    attributes = dict(row.get("attributes") or {})
    attributes.update(compact({
        "source_component_key": row.get("source_component_key"),
        "citation": row.get("citation"),
        "source_url": row.get("source_url"),
        "citation_url": row.get("citation_url"),
        "content_hash": row.get("content_hash"),
        "source_html_hash": row.get("source_html_hash"),
    }))
    return compact({
        "id": row["workbench_component_id"],
        "type": row["type"],
        "number": row.get("number"),
        "heading": row.get("heading"),
        "text": row.get("text"),
        "children": [],
        "attributes": attributes,
        "source": compact({
            "externalId": row.get("source_component_key"),
            "sourceHash": row.get("content_hash") or row.get("source_html_hash"),
        }),
        "extensions": {
            "exais:source_component_key": row.get("source_component_key"),
            "exais:source_schema": "topeka_municipal_code_v1",
        },
    })


def projection_rows(components: list[dict[str, Any]], subtree_hashes: dict[str, str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in components:
        rows.append(compact({
            "component_id": row["workbench_component_id"],
            "parent_component_id": row.get("parent_workbench_component_id"),
            "source_component_key": row["source_component_key"],
            "parent_source_component_key": row.get("parent_source_component_key"),
            "type": row["type"],
            "label": row.get("number") or row.get("heading"),
            "text": row.get("text") or "",
            "citation": row.get("citation"),
            "ordinal": row.get("ordinal", 0),
            "subtree_sha256": subtree_hashes.get(row["source_component_key"]),
            "source_url": row.get("source_url"),
            "citation_url": row.get("citation_url"),
            "content_hash": row.get("content_hash"),
            "source_html_hash": row.get("source_html_hash"),
        }))
    return rows


def canonical_references(sections: list[dict[str, Any]], included_keys: set[str]) -> list[dict[str, Any]]:
    refs: dict[str, dict[str, Any]] = {}
    for section in sections:
        source_key = str(section.get("id") or "")
        if source_key not in included_keys:
            continue
        for ref in section.get("references") or []:
            if not isinstance(ref, dict) or not ref.get("url"):
                continue
            raw = str(ref.get("text") or ref.get("citation") or ref.get("url"))
            target_key = str(ref.get("target_id") or "")
            ref_key = f"{source_key}|{target_key}|{ref.get('url')}|{raw}"
            refs[ref_key] = compact({
                "id": stable_uuid(f"reference:{ref_key}"),
                "kind": "internal-component" if target_key else "other",
                "raw": raw,
                "normalizedUri": ref.get("url"),
                "targetComponentId": stable_uuid(target_key) if target_key in included_keys else None,
                "resolution": "resolved" if target_key in included_keys else "unresolved",
                "source": "parser",
                "confidence": 0.85 if target_key in included_keys else 0.5,
                "candidates": [{"source_component_key": target_key, "url": ref.get("url")}] if target_key else [],
            })
    return [refs[key] for key in sorted(refs)]


def slice_rows(
    components: list[dict[str, Any]],
    sections_by_key: dict[str, dict[str, Any]],
    parent_key_by_key: dict[str, str | None],
) -> list[dict[str, Any]]:
    type_by_key = {str(row["source_component_key"]): str(row["type"]) for row in components}
    component_by_key = {str(row["source_component_key"]): row for row in components}
    rows: list[dict[str, Any]] = []
    for slice_type in ("title", "chapter", "appendix", "article"):
        grouped: dict[str, list[str]] = defaultdict(list)
        for section_key in sections_by_key:
            ancestor = nearest_ancestor(section_key, parent_key_by_key, type_by_key, slice_type)
            if ancestor:
                grouped[ancestor].append(section_key)
        for slice_key in sorted(grouped, key=lambda key: (component_by_key.get(key, {}).get("ordinal", 0), key)):
            section_keys = sorted(grouped[slice_key])
            section_hashes = [str(sections_by_key[key].get("content_hash") or "") for key in section_keys]
            row = component_by_key.get(slice_key, {})
            rows.append(compact({
                "schema": "exais.workbench_slice.v1",
                "slice_key": slice_key,
                "slice_type": slice_type,
                "workbench_component_id": row.get("workbench_component_id"),
                "citation": row.get("citation"),
                "title": row.get("heading") or row.get("number"),
                "section_count": len(section_keys),
                "section_component_keys": section_keys,
                "section_component_ids": [stable_uuid(key) for key in section_keys],
                "source_urls": [sections_by_key[key].get("source_url") for key in section_keys],
                "content_sha256": sha256_text("\n".join(section_hashes)),
            }))
    return rows


def nearest_ancestor(
    key: str,
    parent_key_by_key: dict[str, str | None],
    type_by_key: dict[str, str],
    target_type: str,
) -> str | None:
    current = parent_key_by_key.get(key)
    seen: set[str] = set()
    while current and current not in seen:
        seen.add(current)
        if type_by_key.get(current) == target_type:
            return current
        current = parent_key_by_key.get(current)
    return None


def document_source_hash(sections: list[dict[str, Any]], url_manifest: list[dict[str, Any]], crawl_report: dict[str, Any]) -> str:
    section_hashes = [
        {
            "id": row.get("id"),
            "content_hash": row.get("content_hash"),
            "source_html_hash": row.get("source_html_hash"),
        }
        for row in sections
    ]
    section_hashes.sort(key=lambda row: str(row.get("id") or ""))
    payload = {
        "section_hashes": section_hashes,
        "manifest_rows": len(url_manifest),
        "fetcher": crawl_report.get("fetcher"),
    }
    return canonical_sha256(payload)


def validate_projection(
    components: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    sections: list[dict[str, Any]],
) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    source_keys = [str(row.get("source_component_key") or "") for row in components]
    component_ids = [str(row.get("workbench_component_id") or "") for row in components]
    source_key_set = {key for key in source_keys if key}
    section_ids = {str(row.get("id") or "") for row in sections if row.get("id")}

    for key, count in Counter(source_keys).items():
        if key and count > 1:
            errors.append({"code": "DUPLICATE_SOURCE_COMPONENT_KEY", "component": key})
    for component_id, count in Counter(component_ids).items():
        if component_id and count > 1:
            errors.append({"code": "DUPLICATE_WORKBENCH_COMPONENT_ID", "component_id": component_id})
    if not sections:
        errors.append({"code": "NO_SOURCE_SECTIONS", "path": "sections.jsonl"})
    for row in components:
        key = str(row.get("source_component_key") or "")
        parent = row.get("parent_source_component_key")
        if parent and str(parent) not in source_key_set:
            errors.append({"code": "MISSING_PARENT_COMPONENT", "component": key, "parent": str(parent)})
        if row.get("type") == "section" and not row.get("source_url"):
            errors.append({"code": "SECTION_MISSING_SOURCE_URL", "component": key})
        if row.get("text") and not row.get("content_hash"):
            errors.append({"code": "TEXT_COMPONENT_MISSING_CONTENT_HASH", "component": key})
    section_component_keys = {key for key, row in ((str(item.get("source_component_key") or ""), item) for item in components) if row.get("type") == "section"}
    missing_section_components = sorted(section_ids - section_component_keys)
    for key in missing_section_components[:25]:
        errors.append({"code": "SOURCE_SECTION_MISSING_COMPONENT", "component": key})
    block_parents = Counter(str(row.get("parent_source_component_key") or "") for row in components if row.get("attributes", {}).get("source_record_type") == "block")
    for section in sections:
        section_key = str(section.get("id") or "")
        if not block_parents.get(section_key):
            warnings.append({"code": "SECTION_HAS_NO_BLOCK_COMPONENTS", "component": section_key})
    return {
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "counts": {
            "components": len(components),
            "relations": len(relations),
            "sections": len(sections),
            "section_components": len(section_component_keys),
            "text_components": sum(1 for row in components if row.get("text")),
        },
    }


def write_workbench_projection(output_dir: Path, projection: dict[str, Any]) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "canonical-document.json", projection["canonical_document"])
    write_jsonl(output_dir / "components.jsonl", projection["components"])
    write_jsonl(output_dir / "component-projection.jsonl", projection["component_projection"])
    write_jsonl(output_dir / "component-relations.jsonl", projection["relations"])
    write_jsonl(output_dir / "slices.jsonl", projection["slices"])

    files = {
        "canonical_document": "canonical-document.json",
        "components": "components.jsonl",
        "component_projection": "component-projection.jsonl",
        "component_relations": "component-relations.jsonl",
        "slices": "slices.jsonl",
    }
    manifest = dict(projection["manifest"])
    manifest["files"] = {
        key: {
            "path": value,
            "sha256": file_sha256(output_dir / value),
            "bytes": (output_dir / value).stat().st_size,
        }
        for key, value in files.items()
    }
    write_json(output_dir / "workbench-import-manifest.json", manifest)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Project Topeka JSON artifacts into workbench-ready canonical components.")
    parser.add_argument("--source-output", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--jurisdiction-id", default="ks-topeka")
    parser.add_argument("--code", default="TMC")
    parser.add_argument("--session", default="municipal-code-current")
    parser.add_argument("--document-title", default="Topeka Municipal Code")
    parser.add_argument("--allow-fail", action="store_true", help="Write the projection report but return 0 when projection quality fails.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = args.output_dir or args.source_output / "workbench"
    projection = build_workbench_projection(
        args.source_output,
        jurisdiction_id=args.jurisdiction_id,
        code=args.code,
        session=args.session,
        document_title=args.document_title,
    )
    manifest = write_workbench_projection(output_dir, projection)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    if not manifest["quality"]["passed"] and not args.allow_fail:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
