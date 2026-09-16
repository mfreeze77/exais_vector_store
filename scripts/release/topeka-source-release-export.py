#!/usr/bin/env python3
"""Export a jurisdiction document release from retained Topeka source inputs.

Reads only artifacts that already exist on disk: the retained TMC capture set
and the retained ordinance PDF/extraction seed. It does not download, does not
embed, does not call an ExAIS API and does not touch a StateCivics database, so
it runs on a bare checkout with no credentials.

    python scripts/release/topeka-source-release-export.py \
        --select tmc:14.40.010 \
        --select ordinance:20407 \
        --select charter-ordinance:126 \
        --output-dir instances/.../releases/<release-id>

Every released document carries its own hashes; the release manifest carries the
inventory. ``jurisdiction-release-validate.py`` re-derives both from the bytes.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jurisdiction_release_contract import (  # noqa: E402
    CODE_ROOT,
    CONTRACT_VERSION,
    COLLECTIONS_BY_ID,
    COLLECTIONS_BY_SLUG,
    JURISDICTION_ALIASES,
    JURISDICTION_KEY,
    JURISDICTION_NAME,
    RELEASE_MANIFEST_SCHEMA_ID,
    ROOT,
    SOURCE_DOCUMENT_SCHEMA_ID,
    WORKBENCH_COMPONENT_NAMESPACE,
    WORKBENCH_COMPONENT_SCHEMA,
    CollectionSpec,
    canonical_json_bytes,
    canonical_source_url,
    component_id,
    document_version_id,
    inventory_fingerprint,
    load_release_schemas,
    payload_fingerprint,
    resolve_capture,
    route_document,
    sha256_bytes,
    sha256_file,
    sha256_text,
    source_document_id,
    stage,
)

DEFAULT_TMC_CORPUS = (
    ROOT / ".tmp" / "topeka-decodo-window-batches-20260827220454" / "combined-full-corpus-20260828-v2"
)
DEFAULT_ORDINANCE_SEED = (
    ROOT / "instances" / "ks-state-civics" / "vector-stores" / "topeka-municipal-code"
    / "sources" / "topeka-ordinances" / "seed"
)

EXPORTER_PATH = "scripts/release/topeka-source-release-export.py"
TMC_CONNECTOR = "scripts/release/topeka-code-ingest.py"
ORDINANCE_CONNECTOR = "scripts/release/topeka-ordinances-collect.py"

# The retained ordinance markdown carries an ExAIS provenance preamble ahead of
# the extractor's own output. It is stripped for the reading text and recorded
# as a named normalization rather than silently dropped.
_MD_HEADER_FIELD = re.compile(r"^(Source collection|Ordinance number|Official PDF|Resolution number):\s")
_MD_TITLE = re.compile(r"^#\s+\S")
_MD_HEADING = re.compile(r"^(#{2,6})\s+(.*\S)\s*$")
# Marker renders the margin line-numbering of Topeka's legal PDFs as standalone
# numeric blocks. They are left in place; removing them would risk deleting real
# numbers from the instrument's text.
_MARGIN_NUMBER = re.compile(r"^\d{1,3}$")


def relative_to_root(path: Path) -> str:
    """Repo-relative where possible, so a pointer written inside a container is
    still meaningful on the host that reads it."""
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


# Paths whose contents are pipeline output rather than the code that produced it.
_ARTIFACT_PREFIXES = ("instances/", ".release/", ".tmp/")


def git_commit() -> tuple[str, bool, list[str]]:
    """(commit, code is dirty, sample of dirty code paths).

    Only *code* dirtiness breaks reproduction. A refresh writes its discovery,
    extraction and destination artifacts into the tree before the export stage
    runs, so a whole-tree dirty check reports every full pipeline run as
    unreproducible and the signal stops meaning anything.
    """
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=CODE_ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        porcelain = subprocess.run(
            ["git", "status", "--porcelain"], cwd=CODE_ROOT, capture_output=True, text=True, check=True
        ).stdout.splitlines()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return ("unknown", True, ["git unavailable"])

    dirty_code: list[str] = []
    for line in porcelain:
        path = line[3:].strip().strip('"')
        if path and not path.startswith(_ARTIFACT_PREFIXES):
            dirty_code.append(path)
    return (commit, bool(dirty_code), sorted(dirty_code)[:10])


def normalize_reading_text(raw: str) -> tuple[str, list[dict[str, str]]]:
    """Reading text plus the named transformations that produced it."""
    applied: list[dict[str, str]] = []
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    if text != raw:
        applied.append({
            "name": "line_endings_to_lf",
            "description": "CRLF/CR line endings rewritten to LF.",
        })

    lines = text.split("\n")
    cursor = 0
    if lines and _MD_TITLE.match(lines[0]):
        stripped = 1
        while stripped < len(lines) and (not lines[stripped].strip() or _MD_HEADER_FIELD.match(lines[stripped])):
            if lines[stripped].strip() and not _MD_HEADER_FIELD.match(lines[stripped]):
                break
            stripped += 1
        # only treat it as the ExAIS preamble when at least one provenance field was present
        if any(_MD_HEADER_FIELD.match(line) for line in lines[1:stripped]):
            cursor = stripped
            applied.append({
                "name": "strip_exais_provenance_preamble",
                "description": (
                    "Removed the ExAIS-added title and Source collection/Ordinance number/Official PDF "
                    "lines prepended to the retained extraction; the same facts are carried in source.*."
                ),
            })
    body = "\n".join(lines[cursor:]).strip("\n")
    normalized = body + "\n" if body else ""
    if normalized != text:
        applied.append({
            "name": "trim_terminal_whitespace_to_single_lf",
            "description": (
                "Leading/trailing blank lines collapsed to exactly one terminal LF. This is the same "
                "class of transformation that separates the STO extraction's manifest hash from its "
                "on-disk hash, so it is always recorded rather than absorbed."
            ),
        })
    return normalized, applied


def char_span(haystack: str, needle: str, *, start: int = 0) -> tuple[int, int] | None:
    index = haystack.find(needle, start)
    if index < 0:
        return None
    return (index, index + len(needle))


@dataclass
class BuiltDocument:
    spec: CollectionSpec
    record: dict[str, Any]
    files: dict[str, tuple[str, bytes]]
    """role -> (filename, bytes). 'record' is added by the writer."""
    original_path: Path
    original_role_present: bool


# --------------------------------------------------------------------------
# TMC code sections
# --------------------------------------------------------------------------

def build_tmc_section(citation: str, corpus: Path, *, include_original: bool) -> BuiltDocument:
    sections = {row["citation"]: row for row in read_jsonl(corpus / "sections.jsonl")}
    section = sections.get(citation)
    if section is None:
        raise SystemExit(f"TMC section {citation!r} is not present in {corpus / 'sections.jsonl'}")

    spec = route_document(official_url=section["source_url"])
    doc_id = source_document_id(spec, citation)

    html_hash = section["source_html_hash"]
    capture = resolve_capture(corpus / "raw", html_hash)
    if capture is None:
        raise SystemExit(
            f"no retained HTML capture in {corpus / 'raw'} hashes to the source_html_hash "
            f"{html_hash} recorded for {citation}"
        )
    capture_bytes = capture.read_bytes()
    capture_sha = sha256_bytes(capture_bytes)

    version_id = document_version_id(doc_id, capture_sha)

    verbatim_bytes = canonical_json_bytes(section)
    verbatim_sha = sha256_bytes(verbatim_bytes)

    normalized, normalizations = normalize_reading_text(section["text"])
    normalized_sha = sha256_text(normalized)

    root_key = f"{doc_id}:section"
    components: list[dict[str, Any]] = [{
        "schema": WORKBENCH_COMPONENT_SCHEMA,
        "source_component_key": root_key,
        "workbench_component_id": component_id(root_key),
        "parent_source_component_key": None,
        "type": "section",
        "ordinal": 0,
        "citation": citation,
        "heading": section["title"],
        "citation_url": section["source_url"],
        "source_url": section["source_url"],
        "content_hash": section["content_hash"],
        "text": normalized.strip("\n"),
        "attributes": {
            "code": section["code"],
            "legacy_node_id": section["id"],
            "page_type": section["page_type"],
        },
    }]
    references: list[dict[str, Any]] = []

    search_from = 0
    for block in section.get("blocks", []):
        order = int(block.get("order", len(components)))
        key = f"{doc_id}:block:{order}"
        block_text = str(block.get("text") or "")
        components.append({
            "schema": WORKBENCH_COMPONENT_SCHEMA,
            "source_component_key": key,
            "workbench_component_id": component_id(key),
            "parent_source_component_key": root_key,
            "type": str(block.get("kind") or "paragraph"),
            "ordinal": order,
            "citation": citation,
            "heading": None,
            "citation_url": section["source_url"],
            "source_url": section["source_url"],
            "content_hash": sha256_text(block_text),
            "text": block_text,
            "attributes": {"block_kind": str(block.get("kind") or "paragraph")},
        })
        span = char_span(normalized, block_text, start=search_from)
        if span is None:
            references.append({
                "ref_id": f"{key}#text",
                "artifact": "normalized_text",
                "availability": "unavailable",
                "unavailable_reason": "block text is not contiguous in the normalized reading text",
                "locator": {"convention": "utf8_char_offset", "block_index": order},
                "quote": None,
                "label": f"TMC {citation} block {order}",
            })
            continue
        search_from = span[1]
        references.append({
            "ref_id": f"{key}#text",
            "artifact": "normalized_text",
            "availability": "available",
            "unavailable_reason": None,
            "locator": {
                "convention": "utf8_char_offset",
                "start": span[0],
                "end": span[1],
                "block_index": order,
                "component_id": component_id(key),
                "source_component_key": key,
            },
            "quote": block_text,
            "label": f"TMC {citation} block {order}",
        })

    for index, table in enumerate(section.get("tables", [])):
        key = f"{doc_id}:table:{index}"
        components.append({
            "schema": WORKBENCH_COMPONENT_SCHEMA,
            "source_component_key": key,
            "workbench_component_id": component_id(key),
            "parent_source_component_key": root_key,
            "type": "table",
            "ordinal": index,
            "citation": citation,
            "heading": None,
            "citation_url": section["source_url"],
            "source_url": section["source_url"],
            "content_hash": sha256_bytes(canonical_json_bytes(table)),
            "text": None,
            "attributes": {"table": table},
        })

    for index, definition in enumerate(section.get("definitions", [])):
        key = f"{doc_id}:definition:{index}"
        components.append({
            "schema": WORKBENCH_COMPONENT_SCHEMA,
            "source_component_key": key,
            "workbench_component_id": component_id(key),
            "parent_source_component_key": root_key,
            "type": "definition",
            "ordinal": index,
            "citation": citation,
            "heading": None,
            "citation_url": section["source_url"],
            "source_url": section["source_url"],
            "content_hash": sha256_text(str(definition)),
            "text": None,
            "attributes": {"legacy_definition_id": definition},
        })

    structured = {
        "schema": "exais.jurisdiction.structured_content.v1",
        "component_schema": WORKBENCH_COMPONENT_SCHEMA,
        "component_id_namespace": str(WORKBENCH_COMPONENT_NAMESPACE),
        "root_source_component_key": root_key,
        "components": components,
    }
    structured_bytes = canonical_json_bytes(structured)

    # A code page has no pagination. Say so instead of leaving the convention absent.
    references.append({
        "ref_id": f"{doc_id}#page",
        "artifact": "retained_original",
        "availability": "unavailable",
        "unavailable_reason": (
            "the retained original is a rendered HTML page; it has no page coordinate space and none "
            "may be inferred from block ordinals or line numbers"
        ),
        "locator": None,
        "quote": None,
        "label": "page coordinates",
    })

    history = section.get("ordinance_history") or []
    relationships: list[dict[str, Any]] = []
    dates: list[dict[str, Any]] = []
    # A section can print several history rows for one ordinance -- an adoption
    # line and a section-level amendment line, say. They are distinct evidence
    # and each needs its own reference, so a repeat gets a disambiguating
    # suffix. The first occurrence keeps the plain id, which is what existing
    # released records already carry.
    seen_history: Counter[str] = Counter()
    linked_targets: set[str] = set()
    for entry in history:
        number = str(entry.get("ordinance") or "").strip()
        if not number:
            continue
        ordinance_spec = COLLECTIONS_BY_SLUG["ordinances"]
        raw = str(entry.get("raw") or "")
        seen_history[number] += 1
        occurrence = seen_history[number]
        ref_id = f"{doc_id}#history:{number}" if occurrence == 1 else f"{doc_id}#history:{number}:{occurrence}"
        span = char_span(normalized, raw)
        references.append({
            "ref_id": ref_id,
            "artifact": "normalized_text",
            "availability": "available" if span else "unavailable",
            "unavailable_reason": None if span else "history line is not present verbatim in the reading text",
            "locator": (
                {"convention": "utf8_char_offset", "start": span[0], "end": span[1]} if span else None
            ),
            "quote": raw if span else None,
            "label": f"publisher ordinance-history row for Ordinance {number}",
        })
        target_id = source_document_id(ordinance_spec, number)
        if target_id in linked_targets:
            # One relationship per target; the extra history rows stay as
            # evidence rather than becoming duplicate claims about the same link.
            if entry.get("date"):
                dates.append({
                    "kind": "ordinance_history_date",
                    "value": str(entry["date"]),
                    "precision": "day",
                    "evidence_ref": ref_id,
                    "note": "publisher-printed history date in m-d-yy form; not independently verified against the ordinance",
                })
            continue
        linked_targets.add(target_id)
        relationships.append({
            "predicate": "amended_by",
            "target": {
                "kind": "source_document_id",
                "value": target_id,
                "collection_id": ordinance_spec.collection_id,
            },
            "resolved": True,
            "basis": "publisher ordinance-history row on the code section page",
            "evidence_ref": ref_id,
            "note": (
                "the row evidences that the publisher attributes this section to that ordinance; it is "
                "not itself proof that the ordinance PDF has been retained or reviewed"
            ),
        })
        if entry.get("date"):
            dates.append({
                "kind": "ordinance_history_date",
                "value": str(entry["date"]),
                "precision": "day",
                "evidence_ref": ref_id,
                "note": "publisher-printed history date in m-d-yy form; not independently verified against the ordinance",
            })

    limitations: list[dict[str, Any]] = []
    if re.search(r"adopted by reference", normalized, re.IGNORECASE):
        limitations.append({
            "code": "incorporated_code_not_retained",
            "description": (
                "This section adopts an external code by reference. The release contains the adopting "
                "text only; the incorporated edition itself is not retained or released here."
            ),
            "affects": "completeness",
        })

    record = {
        "schema": SOURCE_DOCUMENT_SCHEMA_ID,
        "schema_version": CONTRACT_VERSION,
        "identity": {
            "jurisdiction_key": JURISDICTION_KEY,
            "jurisdiction_aliases": list(JURISDICTION_ALIASES),
            "collection_id": spec.collection_id,
            "source_document_id": doc_id,
            "document_version_id": version_id,
            "version_ordinal": 1,
            "prior_version_id": None,
            "legacy_ids": [
                {"system": "topeka_code_scraper_v1", "id": section["id"], "note": "node id in sections.jsonl"},
            ],
            "supersedes": [],
            "component_id_namespace": str(WORKBENCH_COMPONENT_NAMESPACE),
        },
        "source": {
            "official_url": canonical_source_url(section["source_url"]),
            "listing_url": spec.master_source_url,
            "retained_original": {
                "reference_uri": f"seed://topeka-codified-code/raw/{capture.name}",
                "local_path": f"files/{capture.name}" if include_original else None,
                "media_type": "text/html",
                "byte_count": len(capture_bytes),
                "sha256": capture_sha,
                "retrieved_at": section["retrieved_at"],
            },
            "acquisition": {
                "acquired_at": section["retrieved_at"],
                "method": "playwright_rendered_capture",
                "connector_entrypoint": TMC_CONNECTOR,
                "connector_revision": "combined-full-corpus-20260828-v2",
            },
            "extractor": {
                "name": "topeka-code-scraper",
                "version": "0.1.1",
                "mode": "playwright_html_parse",
            },
            "source_schema_version": "topeka_municipal_code_v1",
            "lineage": [
                {
                    "step": "capture",
                    "tool": TMC_CONNECTOR,
                    "tool_version": "0.1.1",
                    "input_sha256": capture_sha,
                    "output_sha256": capture_sha,
                    "note": "rendered HTML retained unmodified; input and output are the same bytes",
                },
                {
                    "step": "parse",
                    "tool": "topeka-code-scraper",
                    "tool_version": "0.1.1",
                    "input_sha256": capture_sha,
                    "output_sha256": verbatim_sha,
                    "note": "parser section record, canonical JSON",
                },
                {
                    "step": "normalize",
                    "tool": EXPORTER_PATH,
                    "tool_version": CONTRACT_VERSION,
                    "input_sha256": verbatim_sha,
                    "output_sha256": normalized_sha,
                },
                {
                    "step": "structure",
                    "tool": EXPORTER_PATH,
                    "tool_version": CONTRACT_VERSION,
                    "input_sha256": verbatim_sha,
                    "output_sha256": sha256_bytes(structured_bytes),
                },
            ],
        },
        "content": {
            "verbatim": {
                "form": "parser_section_record_json",
                "path": "verbatim.json",
                "sha256": verbatim_sha,
                "byte_count": len(verbatim_bytes),
                "char_count": len(verbatim_bytes.decode("utf-8")),
            },
            "normalized_text": {
                "path": "normalized.txt",
                "sha256": normalized_sha,
                "char_count": len(normalized),
                "normalizations": normalizations,
            },
            "structured": {
                "path": "structured.json",
                "sha256": sha256_bytes(structured_bytes),
                "block_count": len(section.get("blocks", [])),
                "table_count": len(section.get("tables", [])),
                "definition_count": len(section.get("definitions", [])),
                "component_schema": WORKBENCH_COMPONENT_SCHEMA,
                "root_component_id": component_id(root_key),
                "root_source_component_key": root_key,
            },
        },
        "evidence": {
            "source_revision": {
                "kind": "rendered_html_capture",
                "value": capture.name,
                "artifact_sha256": capture_sha,
                "captured_at": section["retrieved_at"],
            },
            "coordinate_conventions": [
                {
                    "name": "utf8_char_offset",
                    "unit": "unicode codepoint",
                    "origin": "0 at the first character of normalized.txt",
                    "applies_to": "normalized_text",
                    "note": "half-open [start, end); end is exclusive",
                },
                {
                    "name": "block_ordinal",
                    "unit": "parser block index",
                    "origin": "0 at the first block of the section",
                    "applies_to": "structured",
                },
            ],
            "references": references,
        },
        "meaning": {
            "document_type": "code_section",
            "document_subtype": None,
            "title": section["title"],
            "publisher_number": citation,
            "status": {
                "value": "adopted",
                "basis": (
                    "the publisher serves this section as current text of the codified Topeka Municipal "
                    "Code and prints an ordinance-history attribution for it"
                ),
                "evidence_ref": f"{doc_id}#history:{history[0]['ordinance']}" if history else None,
            },
            "dates": dates,
            "citations": [
                {"label": f"TMC {citation}", "url": canonical_source_url(section["source_url"]), "scope": "document"},
            ],
            "relationships": relationships,
            "extraction_quality": {
                "grade": "good",
                "usable_text": bool(normalized.strip()),
                "limitations": limitations,
            },
            "review": {
                "status": "unreviewed",
                "reviewer": None,
                "reviewed_at": None,
                "notes": ["structured parse not compared against the publisher page by a human reviewer"],
            },
        },
        "readiness": {
            "acquisition": stage("complete", detail="rendered capture retained and hash-verified"),
            "extraction": stage("complete", detail="parser record retained; text and blocks present"),
            "validation": stage("complete", detail="validated by jurisdiction-release-validate.py"),
            "review": stage("pending", detail="no human legal review recorded"),
            "artifact_publication": stage("complete", detail="record and artifacts written to this bundle"),
            "vector_indexing": stage("pending", detail="not ingested through the ExAIS API in this release"),
            "graph": stage("pending", detail="graph edges not built or loaded for this release"),
        },
    }

    files = {
        "verbatim": ("verbatim.json", verbatim_bytes),
        "normalized_text": ("normalized.txt", normalized.encode("utf-8")),
        "structured": ("structured.json", structured_bytes),
    }
    if include_original:
        files["retained_original"] = (f"files/{capture.name}", capture_bytes)
    return BuiltDocument(spec, record, files, capture, include_original)


# --------------------------------------------------------------------------
# ordinance / charter-ordinance PDFs
# --------------------------------------------------------------------------

def _ordinance_rows(seed: Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    manifest = read_jsonl(seed / "manifests" / "ordinances.jsonl")
    extractions = {row["id"]: row for row in read_jsonl(seed / "manifests" / "ordinance-extractions.jsonl")}
    return manifest, extractions


def _publisher_key_for(row: dict[str, Any]) -> str:
    """Publisher document key. Falls back to the official URL stem.

    The Standard Traffic Ordinance carries no number; it still needs a stable
    identity, so the publisher's own file stem supplies one rather than the
    document being dropped for being unnumbered.
    """
    number = str(row.get("ordinance_number") or "").strip()
    if number:
        return number
    stem = Path(canonical_source_url(row["pdf_url"])).stem
    if not stem:
        raise SystemExit(f"cannot derive a stable publisher key for {row['id']}")
    return stem


def build_ordinance(
    row: dict[str, Any],
    extraction: dict[str, Any],
    seed: Path,
    *,
    include_original: bool,
) -> BuiltDocument:
    spec = route_document(official_url=row["pdf_url"], listing_category=row.get("category"))
    doc_id = source_document_id(spec, _publisher_key_for(row))

    pdf_path = seed / row["saved_path"]
    if not pdf_path.exists():
        raise SystemExit(f"retained original for {row['id']} is missing at {pdf_path}")
    pdf_sha = sha256_file(pdf_path)
    if pdf_sha != row["sha256"]:
        raise SystemExit(f"{pdf_path} hashes to {pdf_sha} but the manifest records {row['sha256']}")
    pdf_bytes = pdf_path.read_bytes()

    md_path = seed / extraction["markdown_path"]
    if not md_path.exists():
        raise SystemExit(f"retained extraction for {row['id']} is missing at {md_path}")
    md_bytes = md_path.read_bytes()
    md_sha = sha256_bytes(md_bytes)

    version_id = document_version_id(doc_id, pdf_sha)

    lineage = [
        {
            "step": "download",
            "tool": ORDINANCE_CONNECTOR,
            "tool_version": "observed-2026-08-27",
            "input_sha256": pdf_sha,
            "output_sha256": pdf_sha,
            "note": "publisher PDF retained unmodified; input and output are the same bytes",
        },
        {
            "step": "extract",
            "tool": "marker",
            "tool_version": "runpod-hosted-2026-08",
            "input_sha256": pdf_sha,
            "output_sha256": extraction["markdown_sha256"],
            "note": "Markdown produced by the bounded remote extraction path",
        },
    ]

    manifest_sha = extraction["markdown_sha256"]
    if md_sha != manifest_sha:
        # Fail closed unless the difference is the one transformation that is
        # traceable from the bytes themselves. Adjusting the expected hash on its
        # own would be hash-swapping, not provenance repair.
        if md_bytes.endswith(b"\n") and sha256_bytes(md_bytes[:-1]) == manifest_sha:
            lineage.append({
                "step": "terminal_newline_appended",
                "tool": "post-extraction file normalization",
                "tool_version": "unversioned",
                "input_sha256": manifest_sha,
                "output_sha256": md_sha,
                "note": (
                    "the retained file is the extractor output plus one terminal LF; content is otherwise "
                    "byte-identical, proven by re-hashing the file without its final byte"
                ),
            })
        else:
            raise SystemExit(
                f"{md_path} hashes to {md_sha} but the extraction manifest records {manifest_sha}; "
                "the difference is not the known terminal-newline transformation"
            )

    raw_text = md_bytes.decode("utf-8")
    normalized, normalizations = normalize_reading_text(raw_text)
    normalized_sha = sha256_text(normalized)
    if not normalized.strip():
        raise SystemExit(f"{md_path} normalizes to empty text; it must not be released as extracted")

    root_key = f"{doc_id}:document"
    components: list[dict[str, Any]] = [{
        "schema": WORKBENCH_COMPONENT_SCHEMA,
        "source_component_key": root_key,
        "workbench_component_id": component_id(root_key),
        "parent_source_component_key": None,
        "type": "instrument",
        "ordinal": 0,
        "citation": row.get("title") or doc_id,
        "heading": row.get("title") or None,
        "citation_url": canonical_source_url(row["pdf_url"]),
        "source_url": canonical_source_url(row["pdf_url"]),
        "content_hash": normalized_sha,
        "text": None,
        "attributes": {
            "listing_category": row.get("category"),
            "legacy_record_id": row["id"],
        },
    }]
    references: list[dict[str, Any]] = []

    search_from = 0
    heading_index = 0
    for line in normalized.split("\n"):
        match = _MD_HEADING.match(line)
        if not match:
            continue
        heading_text = match.group(2)
        key = f"{doc_id}:heading:{heading_index}"
        span = char_span(normalized, heading_text, start=search_from)
        if span:
            search_from = span[1]
        components.append({
            "schema": WORKBENCH_COMPONENT_SCHEMA,
            "source_component_key": key,
            "workbench_component_id": component_id(key),
            "parent_source_component_key": root_key,
            "type": "heading",
            "ordinal": heading_index,
            "citation": heading_text,
            "heading": heading_text,
            "citation_url": canonical_source_url(row["pdf_url"]),
            "source_url": canonical_source_url(row["pdf_url"]),
            "content_hash": sha256_text(heading_text),
            "text": heading_text,
            "attributes": {"markdown_level": len(match.group(1))},
        })
        references.append({
            "ref_id": f"{key}#text",
            "artifact": "normalized_text",
            "availability": "available" if span else "unavailable",
            "unavailable_reason": None if span else "heading text not located in the normalized reading text",
            "locator": (
                {
                    "convention": "utf8_char_offset",
                    "start": span[0],
                    "end": span[1],
                    "component_id": component_id(key),
                    "source_component_key": key,
                }
                if span
                else None
            ),
            "quote": heading_text if span else None,
            "label": heading_text[:120],
        })
        heading_index += 1

    # The single most important coordinate statement in this release.
    references.append({
        "ref_id": f"{doc_id}#page",
        "artifact": "retained_original",
        "availability": "unavailable",
        "unavailable_reason": (
            "the retained extraction carries no page boundary markers, so no PDF page number is known "
            "for any span; markdown line numbers are not page numbers and are never converted into one"
        ),
        "locator": None,
        "quote": None,
        "label": "PDF page coordinates",
    })

    structured = {
        "schema": "exais.jurisdiction.structured_content.v1",
        "component_schema": WORKBENCH_COMPONENT_SCHEMA,
        "component_id_namespace": str(WORKBENCH_COMPONENT_NAMESPACE),
        "root_source_component_key": root_key,
        "components": components,
    }
    structured_bytes = canonical_json_bytes(structured)

    lineage.extend([
        {
            "step": "normalize",
            "tool": EXPORTER_PATH,
            "tool_version": CONTRACT_VERSION,
            "input_sha256": md_sha,
            "output_sha256": normalized_sha,
        },
        {
            "step": "structure",
            "tool": EXPORTER_PATH,
            "tool_version": CONTRACT_VERSION,
            "input_sha256": md_sha,
            "output_sha256": sha256_bytes(structured_bytes),
        },
    ])

    limitations = [{
        "code": "no_page_coordinates",
        "description": (
            "The retained Markdown has no page boundaries, so page-level citation into the original PDF "
            "is unavailable for this document."
        ),
        "affects": "evidence",
    }]
    margin_lines = sum(1 for line in normalized.split("\n") if _MARGIN_NUMBER.match(line.strip()))
    if margin_lines >= 10:
        limitations.append({
            "code": "margin_line_numbers_in_text",
            "description": (
                f"{margin_lines} standalone numeric lines are present; these are the PDF's margin line "
                "numbering rendered as body text. They are retained rather than stripped, because "
                "removing them risks deleting real numbers from the instrument."
            ),
            "affects": "readable_text",
        })
    if re.search(r"\b(19|20)\d{2}(19|20)\d{2}\b", normalized):
        limitations.append({
            "code": "redline_markup_flattened",
            "description": (
                "The publisher's PDF shows amendments as struck and inserted text. The extractor "
                "flattened that markup, so struck and inserted values appear concatenated (for example "
                "a four-digit year immediately followed by another). Amended values must be read from "
                "the original PDF, not from this text."
            ),
            "affects": "readable_text",
        })

    grade = "degraded" if len(limitations) > 1 else "good"

    dates: list[dict[str, Any]] = []
    published = re.search(r"\(Published in [^)]*?((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4})", normalized)
    if published:
        span = char_span(normalized, published.group(0))
        ref_id = f"{doc_id}#published"
        references.append({
            "ref_id": ref_id,
            "artifact": "normalized_text",
            "availability": "available" if span else "unavailable",
            "unavailable_reason": None if span else "publication line not located",
            "locator": {"convention": "utf8_char_offset", "start": span[0], "end": span[1]} if span else None,
            "quote": published.group(0) if span else None,
            "label": "publication line",
        })
        dates.append({
            "kind": "published",
            "value": published.group(1),
            "precision": "day",
            "evidence_ref": ref_id,
            "note": "publication line printed on the instrument; not a certification of effective date",
        })

    relationships: list[dict[str, Any]] = []
    for amended in sorted(set(re.findall(r"\b(\d{1,2}\.\d{2}\.\d{2,3})\b", normalized))):
        code_spec = COLLECTIONS_BY_SLUG["municipal-code"]
        span = char_span(normalized, amended)
        ref_id = f"{doc_id}#cites:{amended}"
        references.append({
            "ref_id": ref_id,
            "artifact": "normalized_text",
            "availability": "available" if span else "unavailable",
            "unavailable_reason": None if span else "citation not located in the reading text",
            "locator": {"convention": "utf8_char_offset", "start": span[0], "end": span[1]} if span else None,
            "quote": amended if span else None,
            "label": f"TMC {amended} citation",
        })
        relationships.append({
            "predicate": "cites_code_section",
            "target": {
                "kind": "source_document_id",
                "value": source_document_id(code_spec, amended),
                "collection_id": code_spec.collection_id,
            },
            "resolved": False,
            "basis": "TMC-shaped citation matched in the extracted text of this instrument",
            "evidence_ref": ref_id,
            "note": (
                "textual citation only. It is not evidence that this instrument amended that section; "
                "the publisher's own ordinance-history row on the code side carries that claim"
            ),
        })

    record = {
        "schema": SOURCE_DOCUMENT_SCHEMA_ID,
        "schema_version": CONTRACT_VERSION,
        "identity": {
            "jurisdiction_key": JURISDICTION_KEY,
            "jurisdiction_aliases": list(JURISDICTION_ALIASES),
            "collection_id": spec.collection_id,
            "source_document_id": doc_id,
            "document_version_id": version_id,
            "version_ordinal": 1,
            "prior_version_id": None,
            "legacy_ids": [
                {"system": "topeka_ordinance_seed_v1", "id": row["id"], "note": "id in manifests/ordinances.jsonl"},
            ],
            "supersedes": [],
            "component_id_namespace": str(WORKBENCH_COMPONENT_NAMESPACE),
        },
        "source": {
            "official_url": canonical_source_url(row["pdf_url"]),
            "listing_url": row.get("source_page_url") or spec.master_source_url,
            "retained_original": {
                "reference_uri": f"seed://topeka-ordinances/{row['saved_path']}",
                "local_path": f"files/{pdf_path.name}" if include_original else None,
                "media_type": "application/pdf",
                "byte_count": len(pdf_bytes),
                "sha256": pdf_sha,
                "retrieved_at": row["retrieved_at"],
            },
            "acquisition": {
                "acquired_at": row["retrieved_at"],
                "method": "official_city_document_center_download",
                "connector_entrypoint": ORDINANCE_CONNECTOR,
                "connector_revision": "observed-2026-08-27",
            },
            "extractor": {
                "name": "marker",
                "version": "runpod-hosted-2026-08",
                "mode": "remote_pdf_to_markdown",
            },
            "source_schema_version": "topeka_ordinance_seed_v1",
            "lineage": lineage,
        },
        "content": {
            "verbatim": {
                "form": "retained_extraction_markdown",
                "path": f"verbatim{md_path.suffix}",
                "sha256": md_sha,
                "byte_count": len(md_bytes),
                "char_count": len(raw_text),
            },
            "normalized_text": {
                "path": "normalized.md",
                "sha256": normalized_sha,
                "char_count": len(normalized),
                "normalizations": normalizations,
            },
            "structured": {
                "path": "structured.json",
                "sha256": sha256_bytes(structured_bytes),
                "block_count": len(components) - 1,
                "table_count": 0,
                "definition_count": 0,
                "component_schema": WORKBENCH_COMPONENT_SCHEMA,
                "root_component_id": component_id(root_key),
                "root_source_component_key": root_key,
            },
        },
        "evidence": {
            "source_revision": {
                "kind": "retained_publisher_pdf",
                "value": pdf_path.name,
                "artifact_sha256": pdf_sha,
                "captured_at": row["retrieved_at"],
            },
            "coordinate_conventions": [
                {
                    "name": "utf8_char_offset",
                    "unit": "unicode codepoint",
                    "origin": "0 at the first character of normalized.md",
                    "applies_to": "normalized_text",
                    "note": "half-open [start, end); end is exclusive",
                },
            ],
            "references": references,
        },
        "meaning": {
            "document_type": spec.document_type,
            "document_subtype": row.get("category"),
            "title": row.get("title") or None,
            "publisher_number": (str(row.get("ordinance_number")).strip() or None) if row.get("ordinance_number") else None,
            "status": {
                "value": "adopted",
                "basis": (
                    "the publisher lists this instrument in its official adopted "
                    f"{spec.name} library and the document carries an enacting clause"
                ),
                "evidence_ref": f"{doc_id}#published" if published else None,
            },
            "dates": dates,
            "citations": [
                {"label": row.get("title") or doc_id, "url": canonical_source_url(row["pdf_url"]), "scope": "document"},
            ],
            "relationships": relationships,
            "extraction_quality": {
                "grade": grade,
                "usable_text": True,
                "limitations": limitations,
            },
            "review": {
                "status": "review_needed" if grade == "degraded" else "unreviewed",
                "reviewer": None,
                "reviewed_at": None,
                "notes": [limitation["code"] for limitation in limitations],
            },
        },
        "readiness": {
            "acquisition": stage("complete", detail="publisher PDF retained and hash-verified against the manifest"),
            "extraction": stage("complete", detail="retained Markdown present and non-empty"),
            "validation": stage("complete", detail="validated by jurisdiction-release-validate.py"),
            "review": stage(
                "pending" if grade == "degraded" else "not_applicable",
                detail="flattened redline markup needs a human read against the PDF" if grade == "degraded" else "",
            ),
            "artifact_publication": stage("complete", detail="record and artifacts written to this bundle"),
            "vector_indexing": stage("pending", detail="not ingested through the ExAIS API in this release"),
            "graph": stage("pending", detail="graph edges not built or loaded for this release"),
        },
    }

    files = {
        "verbatim": (f"verbatim{md_path.suffix}", md_bytes),
        "normalized_text": ("normalized.md", normalized.encode("utf-8")),
        "structured": ("structured.json", structured_bytes),
    }
    if include_original:
        files["retained_original"] = (f"files/{pdf_path.name}", pdf_bytes)
    return BuiltDocument(spec, record, files, pdf_path, include_original)


# --------------------------------------------------------------------------
# documents acquired and extracted by this pipeline
# --------------------------------------------------------------------------

def build_acquired_document(entry: dict[str, Any], *, include_original: bool) -> BuiltDocument:
    """Release a document this pipeline acquired and extracted locally.

    ``entry`` is one row of a release selection: the acquisition receipt joined
    to its extraction result. Everything the contract needs is already recorded
    by those two stages, so nothing is re-derived from the publisher here.
    """
    spec = COLLECTIONS_BY_ID[entry["collection_id"]]
    doc_id = entry["source_document_id"]

    original = Path(entry["retained_artifact"])
    if not original.exists():
        raise SystemExit(f"{doc_id}: acquired original is missing at {original}")
    original_bytes = original.read_bytes()
    original_sha = sha256_bytes(original_bytes)
    if original_sha != entry["sha256"]:
        raise SystemExit(
            f"{doc_id}: acquired original hashes to {original_sha}, the receipt records {entry['sha256']}"
        )

    normalized_path = Path(entry["normalized_path"])
    structured_source = Path(entry["structured_path"])
    if not normalized_path.exists() or not structured_source.exists():
        raise SystemExit(f"{doc_id}: extraction artifacts are missing; it cannot be released as extracted")

    verbatim_bytes = structured_source.read_bytes()
    verbatim_sha = sha256_bytes(verbatim_bytes)
    raw_text = normalized_path.read_text(encoding="utf-8")
    normalized, normalizations = normalize_reading_text(raw_text)
    normalized_sha = sha256_text(normalized)
    if not normalized.strip():
        raise SystemExit(f"{doc_id}: normalizes to empty text; it must not be released as extracted")

    version_id = document_version_id(doc_id, original_sha)
    extractor = entry.get("extractor") or {}
    parsed = json.loads(verbatim_bytes.decode("utf-8"))

    root_key = f"{doc_id}:document"
    components: list[dict[str, Any]] = [{
        "schema": WORKBENCH_COMPONENT_SCHEMA,
        "source_component_key": root_key,
        "workbench_component_id": component_id(root_key),
        "parent_source_component_key": None,
        "type": "instrument",
        "ordinal": 0,
        "citation": entry.get("publisher_key") or doc_id,
        "heading": None,
        "citation_url": entry["source_uri"],
        "source_url": entry["source_uri"],
        "content_hash": normalized_sha,
        "text": None,
        "attributes": {"media_type": entry.get("media_type"), "origin": "acquisition"},
    }]
    references: list[dict[str, Any]] = []
    search_from = 0
    for block in parsed.get("blocks", []):
        order = int(block.get("order", len(components)))
        key = f"{doc_id}:block:{order}"
        block_text = str(block.get("text") or "")
        components.append({
            "schema": WORKBENCH_COMPONENT_SCHEMA,
            "source_component_key": key,
            "workbench_component_id": component_id(key),
            "parent_source_component_key": root_key,
            "type": str(block.get("kind") or "paragraph"),
            "ordinal": order,
            "citation": entry.get("publisher_key") or doc_id,
            "heading": block_text if block.get("kind") == "heading" else None,
            "citation_url": entry["source_uri"],
            "source_url": entry["source_uri"],
            "content_hash": sha256_text(block_text),
            "text": block_text,
            "attributes": {"block_kind": str(block.get("kind") or "paragraph")},
        })
        span = char_span(normalized, block_text, start=search_from)
        if span:
            search_from = span[1]
        references.append({
            "ref_id": f"{key}#text",
            "artifact": "normalized_text",
            "availability": "available" if span else "unavailable",
            "unavailable_reason": None if span else "block text is not contiguous in the reading text",
            "locator": (
                {"convention": "utf8_char_offset", "start": span[0], "end": span[1],
                 "block_index": order, "component_id": component_id(key),
                 "source_component_key": key} if span else None
            ),
            "quote": block_text if span else None,
            "label": f"{doc_id.rsplit(':', 1)[-1]} block {order}",
        })

    references.append({
        "ref_id": f"{doc_id}#page",
        "artifact": "retained_original",
        "availability": "unavailable",
        "unavailable_reason": (
            entry.get("page_unavailable_reason")
            or "the source format carries no fixed pagination, so no page coordinate is known"
        ),
        "locator": None,
        "quote": None,
        "label": "page coordinates",
    })

    structured = {
        "schema": "exais.jurisdiction.structured_content.v1",
        "component_schema": WORKBENCH_COMPONENT_SCHEMA,
        "component_id_namespace": str(WORKBENCH_COMPONENT_NAMESPACE),
        "root_source_component_key": root_key,
        "components": components,
    }
    structured_bytes = canonical_json_bytes(structured)

    lineage = [{
        "step": "download",
        "tool": ORDINANCE_CONNECTOR,
        "tool_version": "topeka-collection-acquire",
        "input_sha256": original_sha,
        "output_sha256": original_sha,
        "note": "publisher bytes retained unmodified",
    }]
    if entry.get("url_resolution"):
        lineage.append({
            "step": "evidenced_url_correction",
            "tool": "scripts/release/topeka-collection-acquire.py",
            "tool_version": CONTRACT_VERSION,
            "input_sha256": original_sha,
            "output_sha256": original_sha,
            "note": (
                f"the listed URL {entry.get('listing_url')} did not resolve; bytes came from "
                f"{entry['source_uri']}, corroborated by the publisher's own naming convention"
            ),
        })
    lineage += [
        {
            "step": "extract",
            "tool": extractor.get("name", "unknown"),
            "tool_version": extractor.get("version", "unknown"),
            "input_sha256": original_sha,
            "output_sha256": verbatim_sha,
        },
        {
            "step": "normalize",
            "tool": EXPORTER_PATH,
            "tool_version": CONTRACT_VERSION,
            "input_sha256": verbatim_sha,
            "output_sha256": normalized_sha,
        },
        {
            "step": "structure",
            "tool": EXPORTER_PATH,
            "tool_version": CONTRACT_VERSION,
            "input_sha256": verbatim_sha,
            "output_sha256": sha256_bytes(structured_bytes),
        },
    ]

    limitations = [
        {"code": item, "description": entry["limitation_descriptions"][item], "affects": "readable_text"}
        for item in entry.get("limitations", [])
        if item in entry.get("limitation_descriptions", {})
    ]
    needs_review = any(item["code"] == "unresolved_tracked_changes" for item in limitations)

    record = {
        "schema": SOURCE_DOCUMENT_SCHEMA_ID,
        "schema_version": CONTRACT_VERSION,
        "identity": {
            "jurisdiction_key": JURISDICTION_KEY,
            "jurisdiction_aliases": list(JURISDICTION_ALIASES),
            "collection_id": spec.collection_id,
            "source_document_id": doc_id,
            "document_version_id": version_id,
            "version_ordinal": 1,
            "prior_version_id": None,
            "legacy_ids": [],
            "supersedes": [],
            "component_id_namespace": str(WORKBENCH_COMPONENT_NAMESPACE),
        },
        "source": {
            "official_url": entry["source_uri"],
            "listing_url": entry.get("listing_url") or spec.master_source_url,
            "retained_original": {
                "reference_uri": f"acquisition://{spec.slug}/{original.parent.name}/{original.name}",
                "local_path": f"files/{original.name}" if include_original else None,
                "media_type": entry.get("media_type") or "application/octet-stream",
                "byte_count": len(original_bytes),
                "sha256": original_sha,
                "retrieved_at": entry["observed_at"],
            },
            "acquisition": {
                "acquired_at": entry["observed_at"],
                "method": "official_city_document_center_download",
                "connector_entrypoint": "scripts/release/topeka-collection-acquire.py",
                "connector_revision": entry.get("run_id") or "unversioned",
            },
            "extractor": {
                "name": extractor.get("name", "unknown"),
                "version": extractor.get("version", "unknown"),
                "mode": extractor.get("mode", "unknown"),
            },
            "source_schema_version": "topeka_acquisition_v1",
            "lineage": lineage,
        },
        "content": {
            "verbatim": {
                "form": "extractor_structured_json",
                "path": "verbatim.json",
                "sha256": verbatim_sha,
                "byte_count": len(verbatim_bytes),
                "char_count": len(verbatim_bytes.decode("utf-8")),
            },
            "normalized_text": {
                "path": "normalized.txt",
                "sha256": normalized_sha,
                "char_count": len(normalized),
                "normalizations": normalizations,
            },
            "structured": {
                "path": "structured.json",
                "sha256": sha256_bytes(structured_bytes),
                "block_count": len(parsed.get("blocks", [])),
                "table_count": len(parsed.get("tables", [])),
                "definition_count": 0,
                "component_schema": WORKBENCH_COMPONENT_SCHEMA,
                "root_component_id": component_id(root_key),
                "root_source_component_key": root_key,
            },
        },
        "evidence": {
            "source_revision": {
                "kind": "acquired_publisher_file",
                "value": original.name,
                "artifact_sha256": original_sha,
                "captured_at": entry["observed_at"],
            },
            "coordinate_conventions": [{
                "name": "utf8_char_offset",
                "unit": "unicode codepoint",
                "origin": "0 at the first character of normalized.txt",
                "applies_to": "normalized_text",
                "note": "half-open [start, end); end is exclusive",
            }],
            "references": references,
        },
        "meaning": {
            "document_type": spec.document_type,
            "document_subtype": None,
            "title": entry.get("title") or None,
            "publisher_number": entry.get("publisher_key") or None,
            "status": {
                "value": "adopted",
                "basis": f"listed by the publisher in its official {spec.name} library",
                "evidence_ref": None,
            },
            "dates": [],
            "citations": [{
                "label": entry.get("publisher_key") or doc_id,
                "url": entry["source_uri"],
                "scope": "document",
            }],
            "relationships": [],
            "extraction_quality": {
                "grade": "degraded" if needs_review else "good",
                "usable_text": True,
                "limitations": limitations,
            },
            "review": {
                "status": "review_needed" if needs_review else "unreviewed",
                "reviewer": None,
                "reviewed_at": None,
                "notes": [item["code"] for item in limitations],
            },
        },
        "readiness": {
            "acquisition": stage("complete", detail="publisher bytes retained and hash-verified"),
            "extraction": stage("complete", detail=f"extracted by {extractor.get('name')}"),
            "validation": stage("complete", detail="validated by jurisdiction-release-validate.py"),
            "review": stage("pending" if needs_review else "not_applicable",
                            detail="tracked changes need a human read" if needs_review else ""),
            "artifact_publication": stage("complete", detail="record and artifacts written to this bundle"),
            "vector_indexing": stage("pending", detail="not ingested through the ExAIS API in this release"),
            "graph": stage("pending", detail="graph edges not built or loaded for this release"),
        },
    }

    files = {
        "verbatim": ("verbatim.json", verbatim_bytes),
        "normalized_text": ("normalized.txt", normalized.encode("utf-8")),
        "structured": ("structured.json", structured_bytes),
    }
    if include_original:
        files["retained_original"] = (f"files/{original.name}", original_bytes)
    return BuiltDocument(spec, record, files, original, include_original)


# --------------------------------------------------------------------------
# selection and assembly
# --------------------------------------------------------------------------

def resolve_selection(
    selector: str,
    *,
    tmc_corpus: Path,
    ordinance_seed: Path,
    include_originals: bool,
) -> BuiltDocument:
    kind, _, key = selector.partition(":")
    kind = kind.strip().lower()
    key = key.strip()
    if not key:
        raise SystemExit(f"--select {selector!r} needs the form <kind>:<publisher key>")

    if kind == "tmc":
        return build_tmc_section(key, tmc_corpus, include_original=include_originals)

    if kind in {"ordinance", "charter-ordinance", "resolution"}:
        rows, extractions = _ordinance_rows(ordinance_seed)
        wanted_category = {"ordinance": "ordinance", "charter-ordinance": "charter_ordinance"}.get(kind)
        matches = [
            row
            for row in rows
            if _publisher_key_for(row) == key
            and (wanted_category is None or row.get("category") == wanted_category)
        ]
        if not matches:
            raise SystemExit(f"{selector!r} matches no retained record in {ordinance_seed}")
        if len(matches) > 1:
            raise SystemExit(f"{selector!r} matches {len(matches)} retained records; identity is ambiguous")
        row = matches[0]
        extraction = extractions.get(row["id"])
        if extraction is None:
            raise SystemExit(f"{row['id']} has no extraction record; it cannot be released as extracted")
        return build_ordinance(row, extraction, ordinance_seed, include_original=include_originals)

    raise SystemExit(f"unknown selector kind {kind!r}")


def load_baseline(previous_manifest: Path | None, released_state: Path | None) -> dict[str, str]:
    """Version last published per document, cumulative state winning."""
    baseline: dict[str, str] = {}
    if previous_manifest and previous_manifest.exists():
        payload = json.loads(previous_manifest.read_text(encoding="utf-8"))
        baseline = {
            entry["source_document_id"]: entry["document_version_id"]
            for entry in payload.get("documents", [])
        }
    if released_state and released_state.exists():
        with released_state.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    row = json.loads(line)
                    baseline[row["source_document_id"]] = row["document_version_id"]
    return baseline


def finalize_versions(documents: list[BuiltDocument], baseline: dict[str, str]) -> None:
    """Stamp prior_version_id and version_ordinal before anything is hashed.

    These fields are part of the record that gets written, so they are part of
    what the record hashes to. Fingerprinting before stamping them compares one
    record and writes another: a retry of a release containing a revised
    document then sees "different content" against bytes it produced itself, and
    allocates a duplicate release instead of recognising its own work.
    """
    for built in documents:
        identity = built.record["identity"]
        prior = baseline.get(identity["source_document_id"])
        if prior is not None and prior != identity["document_version_id"]:
            identity["prior_version_id"] = prior
            identity["version_ordinal"] = 2


def planned_inventory_of(documents: list[BuiltDocument]) -> str:
    """The inventory fingerprint of these records exactly as they will be written."""
    return inventory_fingerprint([
        {
            "source_document_id": built.record["identity"]["source_document_id"],
            "document_version_id": built.record["identity"]["document_version_id"],
            "payload_sha256": payload_fingerprint(built.record),
        }
        for built in documents
    ])


def allocate_free_release(
    documents: list[BuiltDocument], *, release_id: str, output_dir: Path
) -> tuple[str, Path]:
    """The given id if it is free or already holds exactly this content, else the next free suffix.

    Suffixing rather than overwriting keeps every published identifier pointing
    at the bytes it was published with, which is what makes an old receipt still
    checkable.
    """
    planned = planned_inventory_of(documents)
    candidate_id, candidate_dir = release_id, output_dir
    for attempt in range(1, 1000):
        manifest = candidate_dir / "release-manifest.json"
        if not manifest.exists():
            return candidate_id, candidate_dir
        try:
            existing = json.loads(manifest.read_text(encoding="utf-8"))["inventory"]["inventory_sha256"]
        except (json.JSONDecodeError, KeyError):
            existing = None
        if existing == planned:
            return candidate_id, candidate_dir  # identical: re-running is idempotent
        candidate_id = f"{release_id}-{attempt + 1:03d}"
        candidate_dir = output_dir.parent / candidate_id
    raise SystemExit(f"could not allocate a free release id from {release_id!r}")


def build_from_selection(
    entry: dict[str, Any],
    *,
    tmc_corpus: Path,
    ordinance_seed: Path,
    include_original: bool,
) -> BuiltDocument:
    """Dispatch one selection row to the builder its extraction came from.

    The selection is a single eligibility set across retained TMC sections,
    retained Marker extractions and locally extracted documents, so the exporter
    has to be able to build any of them. Keeping a separate hardcoded list of
    "starter" documents alongside it is what let a run with nothing eligible
    still publish three documents.
    """
    builder = entry.get("builder")
    if builder == "tmc_section":
        return build_tmc_section(entry["citation"], tmc_corpus, include_original=include_original)
    if builder == "retained_ordinance":
        rows, extractions = _ordinance_rows(ordinance_seed)
        row = next((item for item in rows if item["id"] == entry["legacy_id"]), None)
        if row is None:
            raise SystemExit(f"{entry['source_document_id']}: retained row {entry['legacy_id']} is absent")
        extraction = extractions.get(row["id"])
        if extraction is None:
            raise SystemExit(f"{entry['source_document_id']}: retained extraction is absent")
        return build_ordinance(row, extraction, ordinance_seed, include_original=include_original)
    if builder in {"acquired_document", None}:
        return build_acquired_document(entry, include_original=include_original)
    raise SystemExit(f"{entry['source_document_id']}: unknown selection builder {builder!r}")


def document_dir_name(doc_id: str) -> str:
    return doc_id.replace(":", "__")


def write_bundle(
    documents: list[BuiltDocument],
    *,
    output_dir: Path,
    release_id: str,
    bundle_kind: str,
    previous_manifest: Path | None,
    command: list[str],
    released_state: Path | None = None,
) -> dict[str, Any]:
    release_schema, document_schema = load_release_schemas()
    commit, dirty, dirty_paths = git_commit()

    # A release is immutable. Writing different content under an identifier that
    # has already been published invalidates every receipt that cites it, and
    # the daily default identifier makes that an ordinary Tuesday rather than an
    # exotic case. Decide before a single byte is written.
    existing_manifest = output_dir / "release-manifest.json"
    existing_inventory: str | None = None
    if existing_manifest.exists():
        try:
            existing_inventory = json.loads(
                existing_manifest.read_text(encoding="utf-8")
            )["inventory"]["inventory_sha256"]
        except (json.JSONDecodeError, KeyError):
            existing_inventory = "unreadable"

    previous: dict[str, Any] | None = None
    if previous_manifest and previous_manifest.exists():
        previous = json.loads(previous_manifest.read_text(encoding="utf-8"))
    # The baseline must be the same cumulative state the selection step used, or
    # the two disagree about what "changed" means: a document published two
    # releases ago and revised now would export as new.
    previous_versions = load_baseline(previous_manifest, released_state)

    # Records must be finalized before they are hashed, and the same fingerprint
    # then drives allocation, the immutability comparison and the write.
    finalize_versions(documents, previous_versions)
    planned_inventory = planned_inventory_of(documents)
    if existing_inventory is not None and existing_inventory != planned_inventory:
        raise SystemExit(
            f"refusing to overwrite release {release_id!r} at {output_dir}: it already holds a "
            f"different inventory ({existing_inventory[:16]}… vs {planned_inventory[:16]}…). "
            "A release identifier is immutable. Allocate a new one, or pass --on-conflict allocate "
            "to have one allocated automatically."
        )
    if existing_inventory == planned_inventory:
        # Identical content under an identifier that already holds it. Rewriting
        # would move released_at and therefore the manifest hash, invalidating
        # every lock and receipt that cites this release -- for no change at all.
        # An idempotent retry must be a no-op on disk, not a re-render.
        existing_bytes = existing_manifest.read_bytes()
        return {
            "manifest": json.loads(existing_bytes.decode("utf-8")),
            "manifest_path": existing_manifest,
            "manifest_sha256": sha256_bytes(existing_bytes),
            "release_id": release_id,
            "output_dir": output_dir,
            "rewritten": False,
        }

    output_dir.mkdir(parents=True, exist_ok=True)

    manifest_documents: list[dict[str, Any]] = []
    unchanged: list[str] = []
    new: list[str] = []
    changed: list[dict[str, Any]] = []

    for built in documents:
        record = built.record
        doc_id = record["identity"]["source_document_id"]
        version_id = record["identity"]["document_version_id"]
        target = output_dir / "documents" / document_dir_name(doc_id)
        (target / "files").mkdir(parents=True, exist_ok=True)

        # Classification only; the identity fields were finalized before hashing.
        prior = record["identity"]["prior_version_id"] or previous_versions.get(doc_id)
        if prior is None:
            new.append(doc_id)
        elif prior == version_id:
            unchanged.append(doc_id)
        else:
            changed.append({
                "source_document_id": doc_id,
                "prior_version_id": prior,
                "document_version_id": version_id,
                "prior_retained": True,
            })

        errors = document_schema.validate(record)
        if errors:
            raise SystemExit(
                f"exporter produced an invalid record for {doc_id}:\n  "
                + "\n  ".join(str(error) for error in errors[:20])
            )

        files_entry: list[dict[str, Any]] = []
        for role, (name, payload) in sorted(built.files.items()):
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            files_entry.append({
                "path": f"documents/{document_dir_name(doc_id)}/{name}",
                "role": role,
                "sha256": sha256_bytes(payload),
                "byte_count": len(payload),
                "present": True,
                "reference_uri": None,
            })
        if "retained_original" not in built.files:
            original = record["source"]["retained_original"]
            files_entry.append({
                "path": f"documents/{document_dir_name(doc_id)}/files/{built.original_path.name}",
                "role": "retained_original",
                "sha256": original["sha256"],
                "byte_count": original["byte_count"],
                "present": False,
                "reference_uri": original["reference_uri"],
            })

        record_bytes = json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
        (target / "record.json").write_bytes(record_bytes)
        files_entry.append({
            "path": f"documents/{document_dir_name(doc_id)}/record.json",
            "role": "record",
            "sha256": sha256_bytes(record_bytes),
            "byte_count": len(record_bytes),
            "present": True,
            "reference_uri": None,
        })

        manifest_documents.append({
            "source_document_id": doc_id,
            "document_version_id": version_id,
            "collection_id": record["identity"]["collection_id"],
            "record_path": f"documents/{document_dir_name(doc_id)}/record.json",
            "record_sha256": sha256_bytes(record_bytes),
            "payload_sha256": payload_fingerprint(record),
            "files": sorted(files_entry, key=lambda entry: entry["path"]),
            "readiness": {
                "artifact_publication": record["readiness"]["artifact_publication"]["state"],
                "vector_indexing": record["readiness"]["vector_indexing"]["state"],
                "graph": record["readiness"]["graph"]["state"],
            },
        })

    manifest_documents.sort(key=lambda entry: entry["source_document_id"])
    by_collection_count: dict[str, int] = {}
    for entry in manifest_documents:
        by_collection_count[entry["collection_id"]] = by_collection_count.get(entry["collection_id"], 0) + 1

    collections = []
    for collection_id, count in sorted(by_collection_count.items()):
        spec = next(built.spec for built in documents if built.spec.collection_id == collection_id)
        collections.append({
            "collection_id": collection_id,
            "name": spec.name,
            "master_source_url": spec.master_source_url,
            "listing_category": spec.listing_category,
            "vector_store_id": spec.vector_store_id,
            "document_count": count,
            "coverage": {
                "state": "partial",
                "basis": (
                    "this release carries an explicitly selected subset; complete discovery against the "
                    "publisher master list has not been run for this collection"
                ),
                "discovered_count": None,
                "released_count": count,
            },
        })

    present_files = [f for entry in manifest_documents for f in entry["files"] if f["present"]]
    referenced_only = [f for entry in manifest_documents for f in entry["files"] if not f["present"]]

    manifest = {
        "schema": RELEASE_MANIFEST_SCHEMA_ID,
        "schema_version": CONTRACT_VERSION,
        "release": {
            "release_id": release_id,
            "released_at": utc_now(),
            "bundle_kind": bundle_kind,
            "producer": {
                "repository": "exai_vector_store",
                "commit": commit,
                "dirty_worktree": dirty,
                "dirty_code_paths": dirty_paths,
                "exporter": EXPORTER_PATH,
                "exporter_sha256": sha256_file(Path(__file__)),
                "command": command,
            },
            "schemas": [
                {
                    "role": "release_manifest",
                    "path": "contracts/jurisdiction-document-release.schema.json",
                    "schema_id": release_schema.schema_id,
                    "version": release_schema.version,
                    "sha256": release_schema.sha256,
                },
                {
                    "role": "source_document",
                    "path": "contracts/jurisdiction-source-document.schema.json",
                    "schema_id": document_schema.schema_id,
                    "version": document_schema.version,
                    "sha256": document_schema.sha256,
                },
            ],
        },
        "jurisdiction": {
            "key": JURISDICTION_KEY,
            "name": JURISDICTION_NAME,
            "aliases": list(JURISDICTION_ALIASES),
        },
        "collections": collections,
        "documents": manifest_documents,
        "inventory": {
            "document_count": len(manifest_documents),
            "file_count": sum(len(entry["files"]) for entry in manifest_documents),
            "present_byte_count": sum(f["byte_count"] for f in present_files),
            "referenced_only_count": len(referenced_only),
            "inventory_sha256": inventory_fingerprint(manifest_documents),
            "by_collection": [
                {"collection_id": collection_id, "document_count": count}
                for collection_id, count in sorted(by_collection_count.items())
            ],
        },
        "update": {
            "previous_release_id": (
                (previous or {}).get("release", {}).get("release_id")
                or ("released-state-ledger" if previous_versions else None)
            ),
            "outcomes": {
                "unchanged": sorted(unchanged),
                "new": sorted(new),
                "changed": sorted(changed, key=lambda entry: entry["source_document_id"]),
                "unavailable": [],
            },
            "stale_consumer_detection": {
                "method": "compare the held document_version_id against the released one for the same source_document_id",
                "compare_field": "document_version_id",
                "note": (
                    "payload_sha256 additionally decides whether re-import is needed when only volatile "
                    "readiness fields moved"
                ),
            },
        },
        "durable_pointers": [],
        "limitations": [
            {
                "code": "subset_release",
                "description": (
                    "This release is an explicitly selected subset of the retained Topeka corpus. It "
                    "establishes the document contract, not collection completeness."
                ),
                "scope": "release",
            },
            {
                "code": "no_vector_or_graph_proof",
                "description": (
                    "No document here has been ingested through the ExAIS API, embedded, or loaded into a "
                    "graph. Vector and graph readiness are reported as pending per document."
                ),
                "scope": "release",
            },
            {
                "code": "extraction_is_not_legal_review",
                "description": (
                    "Released text is extracted source content. It does not establish adoption, legal "
                    "completeness, effective dates or a final outcome beyond the evidence each record cites."
                ),
                "scope": "release",
            },
        ],
    }

    errors = release_schema.validate(manifest)
    if errors:
        raise SystemExit(
            "exporter produced an invalid release manifest:\n  "
            + "\n  ".join(str(error) for error in errors[:20])
        )

    manifest_path = output_dir / "release-manifest.json"
    manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False).encode("utf-8") + b"\n"
    manifest_path.write_bytes(manifest_bytes)
    return {
        "manifest": manifest,
        "manifest_path": manifest_path,
        "manifest_sha256": sha256_bytes(manifest_bytes),
        "release_id": release_id,
        "output_dir": output_dir,
        "rewritten": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--select", action="append", default=[], metavar="KIND:KEY",
                        help="tmc:14.40.010 | ordinance:20407 | charter-ordinance:126 | resolution:09749")
    parser.add_argument("--selection", type=Path, default=None,
                        help="JSONL of acquired+extracted documents to release, from "
                             "topeka-release-selection.py")
    parser.add_argument("--tmc-corpus", type=Path, default=DEFAULT_TMC_CORPUS)
    parser.add_argument("--ordinance-seed", type=Path, default=DEFAULT_ORDINANCE_SEED)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--release-id", default=None)
    parser.add_argument("--bundle-kind", choices=["production", "starter", "fixture"], default="starter")
    parser.add_argument("--no-release-receipt", type=Path, default=None,
                        help="where to record a quiet run (default: <releases>/proofs/"
                             "<release-id>-no-release.json). Never inside the release directory.")
    parser.add_argument("--release-pointer", type=Path, default=None,
                        help="write the release id and path actually used here, so downstream "
                             "stages act on the release that exists rather than the one requested")
    parser.add_argument("--on-conflict", choices=["refuse", "allocate"], default="refuse",
                        help="what to do when the release id already holds different content: refuse "
                             "(default) or allocate the next free suffixed id")
    parser.add_argument("--previous-manifest", type=Path, default=None)
    parser.add_argument("--released-state", type=Path, default=None,
                        help="cumulative ledger from topeka-release-ledger.py; must be the same "
                             "baseline topeka-release-selection.py was given")
    parser.add_argument("--allow-empty", action="store_true",
                        help="a selection with nothing eligible is a normal quiet refresh, not a "
                             "failure; write a no-op receipt and exit 0 instead of a release")
    parser.add_argument("--reference-originals", action="store_true",
                        help="record retained originals by URI and hash instead of copying them into the bundle")
    args = parser.parse_args()

    if not args.select and not args.selection:
        parser.error("at least one --select, or a --selection file, is required")

    release_id = args.release_id or f"topeka-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{args.bundle_kind}"
    documents = [
        resolve_selection(
            selector,
            tmc_corpus=args.tmc_corpus,
            ordinance_seed=args.ordinance_seed,
            include_originals=not args.reference_originals,
        )
        for selector in args.select
    ]
    if args.selection:
        with args.selection.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                documents.append(
                    build_from_selection(
                        json.loads(line),
                        tmc_corpus=args.tmc_corpus,
                        ordinance_seed=args.ordinance_seed,
                        include_original=not args.reference_originals,
                    )
                )
    if not documents:
        if not args.allow_empty:
            raise SystemExit("the selection is empty; there is nothing eligible to release")
        # No manifest is written: the release schema requires at least one
        # document, and an empty "release" would be a claim that something was
        # published. The receipt records the no-op instead.
        #
        # It goes BESIDE the release directory, never inside it. A quiet run
        # against an id that already holds a release would otherwise add a file
        # to a published bundle, which mutates something immutable and leaves
        # every lock's file count stale.
        receipt = {
            "artifact": "jurisdiction_document_release_noop",
            "release_id": release_id,
            "released_at": utc_now(),
            "reason": "nothing was eligible to release; no manifest written and no release claimed",
            "selection": str(args.selection) if args.selection else None,
        }
        receipt_path = args.no_release_receipt or (
            args.output_dir.parent / "proofs" / f"{release_id}-no-release.json"
        )
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(
            json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        if args.release_pointer:
            args.release_pointer.parent.mkdir(parents=True, exist_ok=True)
            args.release_pointer.write_text(json.dumps({
                "release_id": release_id,
                "output_dir": relative_to_root(args.output_dir),
                "manifest_path": None,
                "released": False,
                "reason": "nothing eligible",
                "no_release_receipt": relative_to_root(receipt_path),
            }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"release_id            {release_id}")
        print("documents             0 — nothing eligible; no release written")
        print(f"no-release receipt    {receipt_path}")
        return 0

    seen: dict[str, str] = {}
    for built in documents:
        doc_id = built.record["identity"]["source_document_id"]
        if doc_id in seen:
            raise SystemExit(f"{doc_id} selected twice; a release may not carry duplicate active documents")
        seen[doc_id] = built.record["identity"]["document_version_id"]

    # Finalize here too, so allocation compares the record that will be written
    # rather than a pre-stamp version of it.
    finalize_versions(documents, load_baseline(args.previous_manifest, args.released_state))
    if args.on_conflict == "allocate":
        release_id, args.output_dir = allocate_free_release(
            documents, release_id=release_id, output_dir=args.output_dir
        )

    result = write_bundle(
        documents,
        output_dir=args.output_dir,
        release_id=release_id,
        bundle_kind=args.bundle_kind,
        previous_manifest=args.previous_manifest,
        released_state=args.released_state,
        command=["python", EXPORTER_PATH, *sys.argv[1:]],
    )

    manifest = result["manifest"]
    # Downstream stages must act on the release that was actually written, which
    # is not necessarily the one that was requested: --on-conflict allocate can
    # move it. Emitting a machine-readable pointer is how the runner learns that
    # without re-deriving it and getting it wrong.
    if args.release_pointer:
        args.release_pointer.parent.mkdir(parents=True, exist_ok=True)
        args.release_pointer.write_text(json.dumps({
            "release_id": result["release_id"],
            "output_dir": relative_to_root(result["output_dir"]),
            "manifest_path": relative_to_root(result["manifest_path"]),
            "manifest_sha256": result["manifest_sha256"],
            "rewritten": result["rewritten"],
            "document_count": manifest["inventory"]["document_count"],
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"release_id            {result['release_id']}")
    print(f"output_dir            {result['output_dir']}")
    if not result["rewritten"]:
        print("bundle                unchanged — identical content already released under this id")
    print(f"manifest              {result['manifest_path']}")
    print(f"manifest_sha256       {result['manifest_sha256']}")
    print(f"documents             {manifest['inventory']['document_count']}")
    print(f"files                 {manifest['inventory']['file_count']}")
    print(f"inventory_sha256      {manifest['inventory']['inventory_sha256']}")
    for entry in manifest["documents"]:
        print(f"  {entry['collection_id']}  {entry['document_version_id']}  payload={entry['payload_sha256'][:16]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
