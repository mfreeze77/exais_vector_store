"""Build deterministic StateCivics handoff records from persisted Marker output."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from svs_common.marker_client import (
    FISCAL_TABLES_PAGE_AWARE_PROFILE,
    marker_options_for_profile,
)
from svs_common.marker_quality import extract_page_markers, summarize_markdown

HANDOFF_VERSION = "1"
RECORD_DIGEST_ALGORITHM = "statecivics-marker-extraction-canonical-json-v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class MarkerHandoffError(ValueError):
    """Persisted extraction metadata cannot prove a StateCivics handoff."""


@dataclass(frozen=True)
class MarkerHandoffArtifact:
    record: dict[str, Any]
    markdown_bytes: bytes


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MarkerHandoffError(f"{field} must be a non-empty string")
    return value.strip()


def _require_sha256(value: Any, field: str) -> str:
    candidate = _require_string(value, field)
    if not _SHA256_RE.fullmatch(candidate):
        raise MarkerHandoffError(f"{field} must be a lowercase SHA-256")
    return candidate


def _require_count(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MarkerHandoffError(f"{field} must be a non-negative integer")
    return value


def _require_binding(attributes: dict[str, Any], field: str, expected: Any) -> None:
    if attributes.get(field) != expected:
        raise MarkerHandoffError(
            f"persisted Marker attribute {field} does not match StateCivics source"
        )


def _record_digest(record: dict[str, Any]) -> str:
    shadow = json.loads(canonical_json(record))
    shadow.pop("record_digest_sha256", None)
    return _sha256(canonical_json(shadow).encode("utf-8"))


def build_marker_handoff(
    *,
    source_record: dict[str, Any],
    state_entry: dict[str, Any],
    file_metadata: dict[str, Any],
    markdown_bytes: bytes,
    vector_store_id: str,
    producer_commit: str,
) -> MarkerHandoffArtifact:
    """Verify persisted ExAIS output and bind it to one StateCivics revision."""
    if source_record.get("mime_type") != "application/pdf":
        raise MarkerHandoffError("Marker handoff source must be application/pdf")
    ingestion = source_record.get("ingestion")
    if not isinstance(ingestion, dict) or ingestion.get("action") != "upsert":
        raise MarkerHandoffError("Marker handoff source must be an upsert record")
    if state_entry.get("action") != "upsert":
        raise MarkerHandoffError("ingestion state does not contain an applied upsert")
    _require_binding(
        state_entry,
        "record_digest_sha256",
        source_record.get("record_digest_sha256"),
    )

    document_id = _require_string(state_entry.get("document_id"), "state.document_id")
    vector_store_file_id = _require_string(
        state_entry.get("vector_store_file_id"), "state.vector_store_file_id"
    )
    _require_binding(file_metadata, "document_id", document_id)
    _require_binding(file_metadata, "vector_store_file_id", vector_store_file_id)
    _require_binding(file_metadata, "vector_store_id", vector_store_id)
    if file_metadata.get("status") != "completed":
        raise MarkerHandoffError("vector-store file is not completed")

    attributes = file_metadata.get("attributes")
    if not isinstance(attributes, dict):
        raise MarkerHandoffError("vector-store file has no persisted attributes")
    source_revision_id = _require_string(
        source_record.get("source_revision_id"), "source_revision_id"
    )
    logical_document_id = _require_sha256(
        source_record.get("logical_document_id"), "logical_document_id"
    )
    source_hash = _require_sha256(
        source_record.get("content_hash_sha256"), "content_hash_sha256"
    )
    for field, expected in (
        ("source_revision_id", source_revision_id),
        ("logical_document_id", logical_document_id),
        ("source_content_hash_sha256", source_hash),
        ("custody_uri", source_record.get("custody_uri")),
        ("citation_url", source_record.get("citation_url")),
        ("pdf_parser", "runpod_marker"),
        ("marker_profile", FISCAL_TABLES_PAGE_AWARE_PROFILE),
        (
            "marker_options",
            marker_options_for_profile(FISCAL_TABLES_PAGE_AWARE_PROFILE),
        ),
        ("source_pdf_id", f"pdf_sha256_{source_hash[:16]}"),
    ):
        _require_binding(attributes, field, expected)

    try:
        markdown = markdown_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MarkerHandoffError("persisted Marker artifact is not UTF-8") from exc
    if not markdown.strip():
        raise MarkerHandoffError("persisted Marker artifact is empty")
    markdown_hash = _sha256(markdown_bytes)
    metrics = summarize_markdown(markdown)
    for field, expected in metrics.items():
        _require_binding(attributes, field, expected)
    page_markers = extract_page_markers(markdown)
    if page_markers != list(range(len(page_markers))):
        raise MarkerHandoffError(
            "persisted Marker pagination must be a complete zero-based sequence"
        )
    table_count = metrics["marker_table_count"]
    table_row_count = metrics["marker_table_row_count"]
    table_cell_count = metrics["marker_table_cell_count"]
    page_marker_count = metrics["marker_page_marker_count"]
    if not isinstance(page_marker_count, int) or page_marker_count < 1:
        raise MarkerHandoffError("persisted Marker artifact has no page delimiters")
    image_count = _require_count(
        attributes.get("marker_image_count"), "marker_image_count"
    )
    producer_commit = _require_string(producer_commit, "producer_commit")
    if not re.fullmatch(r"[0-9a-f]{40}", producer_commit):
        raise MarkerHandoffError("producer_commit must be a full Git SHA")

    identity_payload = {
        "source_revision_id": source_revision_id,
        "source_content_hash_sha256": source_hash,
        "markdown_content_hash_sha256": markdown_hash,
        "engine": "runpod_marker",
        "mode": "pdf_markdown_external_v1",
    }
    extraction_record_id = _sha256(canonical_json(identity_payload).encode("utf-8"))
    pages = attributes.get("marker_pages")
    if pages is not None:
        pages = _require_count(pages, "marker_pages")
    _require_binding(attributes, "marker_output_format", "markdown")
    output_format = "markdown"
    job_id = _require_string(attributes.get("marker_job_id"), "marker_job_id")

    record = {
        "schema_version": 1,
        "extraction_record_id": extraction_record_id,
        "source_revision_id": source_revision_id,
        "logical_document_id": logical_document_id,
        "source_content_hash_sha256": source_hash,
        "source_custody_uri": _require_string(
            source_record.get("custody_uri"), "source_custody_uri"
        ),
        "source_citation_url": _require_string(
            source_record.get("citation_url"), "source_citation_url"
        ),
        "redistribution": _require_string(
            source_record.get("redistribution"), "redistribution"
        ),
        "classification": "public",
        "extracted_artifact": {
            "mime_type": "text/markdown",
            "relative_path": f"extracted/{markdown_hash}.md",
            "content_hash_sha256": markdown_hash,
            "byte_count": len(markdown_bytes),
            "character_count": len(markdown),
            "page_marker_count": page_marker_count,
            "table_count": table_count,
            "table_row_count": table_row_count,
            "table_cell_count": table_cell_count,
        },
        "marker": {
            "engine": "runpod_marker",
            "mode": "pdf_markdown_external_v1",
            "profile": FISCAL_TABLES_PAGE_AWARE_PROFILE,
            "options": marker_options_for_profile(FISCAL_TABLES_PAGE_AWARE_PROFILE),
            "job_id": job_id,
            "output_format": output_format,
            "image_count": image_count,
            "pages": pages,
        },
        "exais": {
            "document_id": document_id,
            "vector_store_file_id": vector_store_file_id,
            "vector_store_id": vector_store_id,
            "content_api_path": f"/v1/files/{document_id}/content",
            "metadata_api_path": (
                f"/v1/vector_stores/{vector_store_id}/files/{vector_store_file_id}"
            ),
        },
        "producer": {
            "repository": "operator-source://exais_vector_store",
            "name": "kansas_fiscal_marker_extraction_exporter",
            "version": HANDOFF_VERSION,
            "code_commit": producer_commit,
        },
        "record_digest_algorithm": RECORD_DIGEST_ALGORITHM,
    }
    record["record_digest_sha256"] = _record_digest(record)
    return MarkerHandoffArtifact(record=record, markdown_bytes=markdown_bytes)


def render_handoff_manifest(artifacts: list[MarkerHandoffArtifact]) -> bytes:
    if not artifacts:
        raise MarkerHandoffError("Marker handoff contains no PDF extraction records")
    records = sorted(
        (artifact.record for artifact in artifacts),
        key=lambda value: value["logical_document_id"],
    )
    for field in ("logical_document_id", "source_revision_id", "extraction_record_id"):
        values = [record[field] for record in records]
        if len(values) != len(set(values)):
            raise MarkerHandoffError(f"Marker handoff contains duplicate {field}")
    return ("".join(canonical_json(record) + "\n" for record in records)).encode(
        "utf-8"
    )


__all__ = [
    "HANDOFF_VERSION",
    "MarkerHandoffArtifact",
    "MarkerHandoffError",
    "build_marker_handoff",
    "canonical_json",
    "render_handoff_manifest",
]
