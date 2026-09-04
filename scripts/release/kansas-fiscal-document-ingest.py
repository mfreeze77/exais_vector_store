#!/usr/bin/env python3
"""Converge a Kansas fiscal vector store from a StateCivics export manifest.

This is a custody consumer, never a collector. It validates the exact JSONL
manifest, resolves portable ``civic-custody://`` keys against an explicitly
mounted root, verifies every upsert byte stream against the ledger hash, and
uses only ExAIS HTTP APIs. It never writes Postgres, Qdrant, MinIO, or OpenSearch
directly.

Dry-run is the default. Use ``--apply`` only after reviewing the full plan.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from svs_common.marker_client import FISCAL_TABLES_PAGE_AWARE_PROFILE
from topeka_pipeline_common import (
    DEFAULT_CELL,
    DEFAULT_KNOWLEDGE_BASE_ID,
    api_json,
    api_json_via_api_container,
    api_json_via_cell_network,
    api_json_via_direct_http,
    api_json_via_host_curl,
    default_api_base,
    default_headers,
    ensure_vector_store,
    safe_filename,
)

DEFAULT_INSTANCE_SLUG = "ks-state-civics"
DEFAULT_VECTOR_STORE_SLUG = "kansas-fiscal-documents"
DEFAULT_VECTOR_STORE_NAME = "Kansas Fiscal Documents"
STATE_SCHEMA_VERSION = 1
RECORD_DIGEST_ALGORITHM = "statecivics-canonical-json-v1"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CUSTODY_RE = re.compile(
    r"^civic-custody://([a-z0-9_-]+)/([0-9a-f]{2})/([0-9a-f]{64})$"
)
_SUPPORTED_TEXT_MIME_TYPES = frozenset({"text/plain", "text/markdown"})
_EXPORTABLE_ARTIFACT_TYPES = frozenset(
    {
        "budget_report",
        "agency_budget_narrative",
        "comparison_report",
        "acfr",
        "account_footnotes",
        "fiscal_note",
        "supplemental_note",
        "session_law",
        "statute",
        "journal",
        "minutes",
        "testimony",
        "transcript",
        "external_fact_check",
    }
)
_LIFECYCLE_STATES = frozenset({"current", "superseded", "corrected", "withdrawn"})
_REDISTRIBUTION_VALUES = frozenset(
    {"full", "excerpt_and_metadata", "metadata_only", "restricted", "unknown"}
)
_CUSTODY_STATUSES = frozenset(
    {"metadata_only", "retained", "retained_restricted", "unavailable", "withdrawn"}
)


class FiscalIngestError(ValueError):
    """The manifest cannot be applied without weakening provenance or safety."""


@dataclass(frozen=True)
class LoadedManifest:
    path: Path
    sha256: str
    byte_count: int
    records: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class PlannedOperation:
    action: str
    logical_document_id: str
    reason: str
    record: dict[str, Any]
    content: bytes | None = None


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def record_digest(record: dict[str, Any]) -> str:
    shadow = json.loads(canonical_json(record))
    shadow.pop("record_digest_sha256", None)
    exporter = shadow.get("exporter")
    if isinstance(exporter, dict):
        exporter.pop("exported_at", None)
    return hashlib.sha256(canonical_json(shadow).encode("utf-8")).hexdigest()


def _require_sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise FiscalIngestError(f"{field} must be a lowercase SHA-256")
    return value


def _require_http_url(value: Any, field: str) -> str:
    candidate = str(value or "")
    parsed = urlsplit(candidate)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise FiscalIngestError(f"{field} must be an absolute HTTP(S) URL")
    return candidate


def _validate_record(
    record: dict[str, Any],
    *,
    line_number: int,
    instance_slug: str,
    vector_store_slug: str,
) -> None:
    prefix = f"manifest line {line_number}"
    for field in (
        "export_record_id",
        "logical_document_id",
        "source_revision_id",
        "content_hash_sha256",
        "custody_uri",
        "custody_status",
        "citation_url",
        "publisher",
        "jurisdiction",
        "artifact_type",
        "record_digest_algorithm",
        "record_digest_sha256",
        "exporter",
        "lifecycle",
        "redistribution",
        "ingestion",
    ):
        if field not in record:
            raise FiscalIngestError(f"{prefix}: missing {field}")

    _require_sha256(record["export_record_id"], f"{prefix} export_record_id")
    _require_sha256(record["logical_document_id"], f"{prefix} logical_document_id")
    _require_sha256(record["content_hash_sha256"], f"{prefix} content_hash_sha256")
    _require_sha256(record["record_digest_sha256"], f"{prefix} record_digest_sha256")
    _require_http_url(record["citation_url"], f"{prefix} citation_url")
    if (
        not isinstance(record["source_revision_id"], str)
        or not record["source_revision_id"].strip()
    ):
        raise FiscalIngestError(f"{prefix}: source_revision_id must not be blank")
    for field in ("publisher", "jurisdiction"):
        if not isinstance(record[field], str) or not record[field].strip():
            raise FiscalIngestError(f"{prefix}: {field} must not be blank")
    if record["artifact_type"] not in _EXPORTABLE_ARTIFACT_TYPES:
        raise FiscalIngestError(
            f"{prefix}: artifact type {record['artifact_type']!r} is not retrieval-exportable"
        )
    if record["custody_status"] not in _CUSTODY_STATUSES:
        raise FiscalIngestError(f"{prefix}: unknown custody status")
    if record["redistribution"] not in _REDISTRIBUTION_VALUES:
        raise FiscalIngestError(f"{prefix}: unknown redistribution value")
    if record["record_digest_algorithm"] != RECORD_DIGEST_ALGORITHM:
        raise FiscalIngestError(f"{prefix}: unsupported record digest algorithm")
    if record_digest(record) != record["record_digest_sha256"]:
        raise FiscalIngestError(f"{prefix}: record digest does not match its fields")

    lifecycle = record["lifecycle"]
    ingestion = record["ingestion"]
    if not isinstance(lifecycle, dict) or not isinstance(ingestion, dict):
        raise FiscalIngestError(f"{prefix}: lifecycle and ingestion must be objects")
    if lifecycle.get("state") not in _LIFECYCLE_STATES:
        raise FiscalIngestError(f"{prefix}: unknown lifecycle state")
    exporter = record["exporter"]
    if not isinstance(exporter, dict):
        raise FiscalIngestError(f"{prefix}: exporter must be an object")
    for field in ("name", "version"):
        if not isinstance(exporter.get(field), str) or not exporter[field].strip():
            raise FiscalIngestError(f"{prefix}: exporter.{field} must not be blank")
    if not isinstance(exporter.get("code_commit"), str) or not re.fullmatch(
        r"[0-9a-f]{40}", exporter["code_commit"]
    ):
        raise FiscalIngestError(
            f"{prefix}: exporter.code_commit must be a full commit SHA"
        )
    if ingestion.get("mode") != "api_only":
        raise FiscalIngestError(f"{prefix}: ingestion mode must be api_only")
    target_instance = ingestion.get("target_instance_slug")
    target_store = ingestion.get("target_vector_store_slug")
    if target_instance != instance_slug or target_store != vector_store_slug:
        raise FiscalIngestError(
            f"{prefix}: target must be {instance_slug}/{vector_store_slug}, got "
            f"{target_instance!r}/{target_store!r}"
        )

    indexable = (
        lifecycle.get("state") == "current"
        and record["redistribution"] == "full"
        and record["custody_status"] == "retained"
    )
    expected_action = "upsert" if indexable else "remove"
    if ingestion.get("action") != expected_action:
        raise FiscalIngestError(
            f"{prefix}: desired-state action must be {expected_action} for this record"
        )
    expected_removal = expected_action == "remove"
    if lifecycle.get("removal_required") is not expected_removal:
        raise FiscalIngestError(
            f"{prefix}: lifecycle.removal_required contradicts action"
        )
    if ingestion.get("recall_evaluation_required") is not (expected_action == "upsert"):
        raise FiscalIngestError(f"{prefix}: recall requirement contradicts action")

    custody_uri = record["custody_uri"]
    if expected_action == "upsert":
        if not isinstance(custody_uri, str) or not _CUSTODY_RE.fullmatch(custody_uri):
            raise FiscalIngestError(f"{prefix}: upsert requires a portable custody URI")
        mime_type = str(record.get("mime_type") or "").split(";", 1)[0].lower()
        if (
            mime_type != "application/pdf"
            and mime_type not in _SUPPORTED_TEXT_MIME_TYPES
        ):
            raise FiscalIngestError(
                f"{prefix}: unsupported upsert MIME type {mime_type!r}; "
                "only PDF and retained UTF-8 text are supported"
            )
    elif custody_uri is not None and (
        not isinstance(custody_uri, str) or not _CUSTODY_RE.fullmatch(custody_uri)
    ):
        raise FiscalIngestError(
            f"{prefix}: removal custody_uri must be portable or null"
        )


def load_manifest(
    path: Path,
    *,
    instance_slug: str = DEFAULT_INSTANCE_SLUG,
    vector_store_slug: str = DEFAULT_VECTOR_STORE_SLUG,
) -> LoadedManifest:
    payload = path.read_bytes()
    if payload and not payload.endswith(b"\n"):
        raise FiscalIngestError(f"{path}: JSONL manifest must end with a newline")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FiscalIngestError(f"{path}: manifest is not UTF-8") from exc

    records: list[dict[str, Any]] = []
    logical_ids: set[str] = set()
    record_ids: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise FiscalIngestError(f"{path}:{line_number}: invalid JSON") from exc
        if not isinstance(record, dict):
            raise FiscalIngestError(f"{path}:{line_number}: expected an object")
        _validate_record(
            record,
            line_number=line_number,
            instance_slug=instance_slug,
            vector_store_slug=vector_store_slug,
        )
        logical_id = record["logical_document_id"]
        record_id = record["export_record_id"]
        if logical_id in logical_ids:
            raise FiscalIngestError(
                f"{path}:{line_number}: duplicate logical_document_id"
            )
        if record_id in record_ids:
            raise FiscalIngestError(f"{path}:{line_number}: duplicate export_record_id")
        logical_ids.add(logical_id)
        record_ids.add(record_id)
        records.append(record)
    if not records:
        raise FiscalIngestError(f"{path}: manifest contains no records")
    records.sort(key=lambda item: item["logical_document_id"])
    return LoadedManifest(
        path=path,
        sha256=hashlib.sha256(payload).hexdigest(),
        byte_count=len(payload),
        records=tuple(records),
    )


def read_custody_object(custody_root: Path, record: dict[str, Any]) -> bytes:
    uri = str(record.get("custody_uri") or "")
    match = _CUSTODY_RE.fullmatch(uri)
    if match is None:
        raise FiscalIngestError(
            f"record {record.get('export_record_id')} has no custody object"
        )
    namespace, shard, digest = match.groups()
    root = custody_root.resolve()
    path = (root / namespace / shard / digest).resolve()
    if not path.is_relative_to(root):
        raise FiscalIngestError(f"custody URI escapes configured root: {uri}")
    if not path.is_file():
        raise FiscalIngestError(f"custody object is missing: {uri}")
    content = path.read_bytes()
    mime_type = str(record.get("mime_type") or "").split(";", 1)[0].lower()
    if mime_type == "application/pdf" and b"%PDF-" not in content[:1024]:
        raise FiscalIngestError(
            f"custody object declared as PDF has no PDF header: {uri}"
        )
    actual = hashlib.sha256(content).hexdigest()
    ledger_hash = record["content_hash_sha256"]
    if actual != digest or actual != ledger_hash:
        raise FiscalIngestError(
            f"custody hash mismatch for {uri}: object={actual}, key={digest}, ledger={ledger_hash}"
        )
    byte_size = record.get("byte_size")
    if isinstance(byte_size, int) and byte_size != len(content):
        raise FiscalIngestError(
            f"custody byte count mismatch for {uri}: object={len(content)}, ledger={byte_size}"
        )
    return content


def load_state(path: Path, *, vector_store_id: str) -> dict[str, Any]:
    if not path.exists():
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "vector_store_id": vector_store_id,
            "records": {},
        }
    value = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != STATE_SCHEMA_VERSION
    ):
        raise FiscalIngestError(f"{path}: unsupported ingestion state")
    if value.get("vector_store_id") != vector_store_id:
        raise FiscalIngestError(
            f"{path}: state belongs to vector store {value.get('vector_store_id')!r}, "
            f"not {vector_store_id!r}"
        )
    if not isinstance(value.get("records"), dict):
        raise FiscalIngestError(f"{path}: records must be an object")
    return value


def write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def plan_operations(
    manifest: LoadedManifest,
    *,
    custody_root: Path,
    state: dict[str, Any],
) -> list[PlannedOperation]:
    prior = state["records"]
    operations: list[PlannedOperation] = []
    for record in manifest.records:
        logical_id = record["logical_document_id"]
        action = record["ingestion"]["action"]
        previous = prior.get(logical_id)
        if action == "upsert":
            content = read_custody_object(custody_root, record)
            if (
                isinstance(previous, dict)
                and previous.get("action") == "upsert"
                and previous.get("record_digest_sha256")
                == record["record_digest_sha256"]
                and previous.get("vector_store_file_id")
            ):
                operations.append(
                    PlannedOperation(
                        "noop", logical_id, "record digest already applied", record
                    )
                )
            else:
                operations.append(
                    PlannedOperation(
                        "upsert",
                        logical_id,
                        "new or changed desired state",
                        record,
                        content,
                    )
                )
            continue
        if (
            isinstance(previous, dict)
            and previous.get("action") == "upsert"
            and previous.get("vector_store_file_id")
        ):
            operations.append(
                PlannedOperation(
                    "remove",
                    logical_id,
                    "manifest requires indexed content removal",
                    record,
                )
            )
        else:
            operations.append(
                PlannedOperation(
                    "noop", logical_id, "document is already absent", record
                )
            )
    return sorted(
        operations, key=lambda item: (item.action != "remove", item.logical_document_id)
    )


def ingest_idempotency_key(vector_store_id: str, record: dict[str, Any]) -> str:
    value = canonical_json(
        {
            "vector_store_id": vector_store_id,
            "logical_document_id": record["logical_document_id"],
            "record_digest_sha256": record["record_digest_sha256"],
            "action": record["ingestion"]["action"],
        }
    )
    return (
        "statecivics-fiscal-" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:48]
    )


def _record_attributes(record: dict[str, Any]) -> dict[str, Any]:
    effective = record.get("effective_period")
    exporter = record.get("exporter")
    return {
        "force_sync": True,
        "marker_profile": FISCAL_TABLES_PAGE_AWARE_PROFILE,
        "source_collection": "statecivics-kansas-fiscal-documents",
        "logical_document_id": record["logical_document_id"],
        "source_revision_id": record["source_revision_id"],
        "source_content_hash_sha256": record["content_hash_sha256"],
        "export_record_id": record["export_record_id"],
        "export_record_digest_sha256": record["record_digest_sha256"],
        "publisher": record.get("publisher") or "",
        "jurisdiction": record.get("jurisdiction") or "",
        "artifact_type": record.get("artifact_type") or "",
        "fiscal_year": (
            effective.get("fiscal_year") if isinstance(effective, dict) else None
        ),
        "citation_url": record["citation_url"],
        "custody_uri": record.get("custody_uri"),
        "statecivics_exporter_version": (
            exporter.get("version") if isinstance(exporter, dict) else None
        ),
        "statecivics_exporter_commit": (
            exporter.get("code_commit") if isinstance(exporter, dict) else None
        ),
    }


def _multipart_payload(
    fields: dict[str, str], *, filename: str, mime_type: str, content: bytes
) -> tuple[str, bytes]:
    boundary = "----exais-fiscal-" + hashlib.sha256(content).hexdigest()[:24]
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    safe_name = filename.replace('"', "_").replace("\r", "_").replace("\n", "_")
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{safe_name}"\r\n'.encode(),
            f"Content-Type: {mime_type}\r\n\r\n".encode(),
            content,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return boundary, b"".join(chunks)


def api_multipart(
    api_base: str,
    path: str,
    *,
    fields: dict[str, str],
    filename: str,
    mime_type: str,
    content: bytes,
    headers: dict[str, str],
    idempotency_key: str,
    timeout: int,
    cell: str,
    transport: str,
) -> dict[str, Any]:
    boundary, body = _multipart_payload(
        fields, filename=filename, mime_type=mime_type, content=content
    )
    request_headers = {
        key: value for key, value in headers.items() if key.lower() != "content-type"
    }
    request_headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    request_headers["Idempotency-Key"] = idempotency_key
    url = f"{api_base.rstrip('/')}{path}"
    if transport == "host-curl":
        return api_json_via_host_curl(
            "POST", url, body, headers=request_headers, timeout=timeout
        )
    if transport == "api-container":
        return api_json_via_api_container(
            "POST", url, body, headers=request_headers, timeout=timeout, cell=cell
        )
    if transport == "docker-network":
        return api_json_via_cell_network(
            "POST", url, body, headers=request_headers, timeout=timeout, cell=cell
        )
    if transport != "auto":
        raise FiscalIngestError(f"unsupported API transport {transport!r}")
    try:
        return api_json_via_direct_http(
            "POST", url, body, headers=request_headers, timeout=timeout
        )
    except Exception:
        try:
            return api_json_via_host_curl(
                "POST", url, body, headers=request_headers, timeout=timeout
            )
        except Exception:
            try:
                return api_json_via_api_container(
                    "POST",
                    url,
                    body,
                    headers=request_headers,
                    timeout=timeout,
                    cell=cell,
                )
            except Exception:
                return api_json_via_cell_network(
                    "POST",
                    url,
                    body,
                    headers=request_headers,
                    timeout=timeout,
                    cell=cell,
                )


def _document_title(record: dict[str, Any]) -> str:
    title = record.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    fiscal_year = record.get("effective_period", {}).get("fiscal_year")
    suffix = f" FY{fiscal_year}" if fiscal_year else ""
    return f"Kansas {record.get('artifact_type', 'fiscal document')}{suffix}"


def submit_upsert(
    operation: PlannedOperation,
    *,
    api_base: str,
    headers: dict[str, str],
    vector_store_id: str,
    knowledge_base_id: str,
    timeout: int,
    cell: str,
    transport: str,
) -> dict[str, Any]:
    record = operation.record
    content = operation.content
    if content is None:
        raise FiscalIngestError("upsert operation has no verified custody content")
    title = _document_title(record)
    mime_type = str(record.get("mime_type") or "").split(";", 1)[0].lower()
    key = ingest_idempotency_key(vector_store_id, record)
    attributes = _record_attributes(record)
    if mime_type == "application/pdf":
        fields = {
            "title": title,
            "mode": "auto_detect_v1",
            "vector_store_id": vector_store_id,
            "knowledge_base_id": knowledge_base_id,
            "security_level": "0",
            "classification": "public",
            "source_uri": record["citation_url"],
            "source_identity": record["logical_document_id"],
            "attributes_json": canonical_json(attributes),
        }
        response = api_multipart(
            api_base,
            "/api/v1/documents/upload",
            fields=fields,
            filename=safe_filename(title, suffix=".pdf"),
            mime_type=mime_type,
            content=content,
            headers=headers,
            idempotency_key=key,
            timeout=timeout,
            cell=cell,
            transport=transport,
        )
    else:
        try:
            text_content = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FiscalIngestError(
                f"record {record['export_record_id']} declares UTF-8 text but bytes do not decode"
            ) from exc
        response = api_json(
            "POST",
            api_base,
            "/api/v1/documents/ingest",
            {
                "vector_store_id": vector_store_id,
                "knowledge_base_id": knowledge_base_id,
                "title": title,
                "filename": safe_filename(title, suffix=".md"),
                "mime_type": mime_type,
                "content": text_content,
                "mode": "markdown_docs_v1",
                "source_uri": record["citation_url"],
                "source_identity": record["logical_document_id"],
                "attributes": attributes,
                "security_level": 0,
                "classification": "public",
                "source_trust": "statecivics_custody_ledger",
            },
            headers=headers,
            timeout=timeout,
            idempotency_key=key,
            cell=cell,
            transport=transport,
        )
    if response.get("status") not in {"completed", "deduplicated"}:
        raise FiscalIngestError(
            "fiscal adapter requires a completed synchronous response; "
            f"API returned {response.get('status')!r}"
        )
    if not response.get("document_id") or not response.get("vector_store_file_id"):
        raise FiscalIngestError(
            "API response omitted document_id or vector_store_file_id"
        )
    return response


def apply_operations(
    operations: list[PlannedOperation],
    *,
    state: dict[str, Any],
    state_path: Path,
    api_base: str,
    headers: dict[str, str],
    vector_store_id: str,
    knowledge_base_id: str,
    timeout: int,
    cell: str,
    transport: str,
) -> dict[str, int]:
    counts = {"upserted": 0, "removed": 0, "unchanged": 0}
    for operation in operations:
        record = operation.record
        logical_id = operation.logical_document_id
        if operation.action == "noop":
            # A removal that is already externally satisfied must still advance
            # local desired-state proof to this exact manifest record. Otherwise
            # every later run compares against stale rights/lifecycle metadata.
            if record["ingestion"]["action"] == "remove":
                previous = state["records"].get(logical_id)
                next_state = {
                    "action": "remove",
                    "record_digest_sha256": record["record_digest_sha256"],
                    "document_id": (
                        previous.get("document_id")
                        if isinstance(previous, dict)
                        else None
                    ),
                    "vector_store_file_id": None,
                }
                if previous != next_state:
                    state["records"][logical_id] = next_state
                    write_json_atomic(state_path, state)
            counts["unchanged"] += 1
            continue
        if operation.action == "remove":
            previous = state["records"][logical_id]
            file_id = previous["vector_store_file_id"]
            try:
                api_json(
                    "DELETE",
                    api_base,
                    f"/v1/vector_stores/{vector_store_id}/files/{file_id}",
                    None,
                    headers=headers,
                    timeout=timeout,
                    idempotency_key=ingest_idempotency_key(vector_store_id, record),
                    cell=cell,
                    transport=transport,
                )
            except RuntimeError as exc:
                if "HTTP 404" not in str(exc):
                    raise
            state["records"][logical_id] = {
                "action": "remove",
                "record_digest_sha256": record["record_digest_sha256"],
                "document_id": previous.get("document_id"),
                "vector_store_file_id": None,
            }
            counts["removed"] += 1
        else:
            response = submit_upsert(
                operation,
                api_base=api_base,
                headers=headers,
                vector_store_id=vector_store_id,
                knowledge_base_id=knowledge_base_id,
                timeout=timeout,
                cell=cell,
                transport=transport,
            )
            state["records"][logical_id] = {
                "action": "upsert",
                "record_digest_sha256": record["record_digest_sha256"],
                "document_id": response["document_id"],
                "vector_store_file_id": response["vector_store_file_id"],
            }
            counts["upserted"] += 1
        write_json_atomic(state_path, state)
    return counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cell", default=DEFAULT_CELL)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--custody-root", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--proof", type=Path)
    parser.add_argument("--instance-slug", default=DEFAULT_INSTANCE_SLUG)
    parser.add_argument("--vector-store-slug", default=DEFAULT_VECTOR_STORE_SLUG)
    parser.add_argument("--vector-store-id")
    parser.add_argument("--vector-store-name", default=DEFAULT_VECTOR_STORE_NAME)
    parser.add_argument("--knowledge-base-id", default=DEFAULT_KNOWLEDGE_BASE_ID)
    parser.add_argument("--allow-create-vector-store", action="store_true")
    parser.add_argument("--api")
    parser.add_argument("--auth-token-file", type=Path)
    parser.add_argument("--api-timeout-seconds", type=int, default=1800)
    parser.add_argument(
        "--api-transport",
        default="auto",
        choices=["auto", "host-curl", "api-container", "docker-network"],
    )
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest = load_manifest(
        args.manifest,
        instance_slug=args.instance_slug,
        vector_store_slug=args.vector_store_slug,
    )
    vector_store_id = args.vector_store_id or "vs_kansas_fiscal_documents_pending"
    if args.apply:
        headers = default_headers(cell=args.cell, auth_token_file=args.auth_token_file)
        vector_store_id = ensure_vector_store(
            api_base=args.api or default_api_base(args.cell),
            headers=headers,
            vector_store_id=args.vector_store_id,
            vector_store_name=args.vector_store_name,
            knowledge_base_id=args.knowledge_base_id,
            allow_create=args.allow_create_vector_store,
            timeout=args.api_timeout_seconds,
            cell=args.cell,
            transport=args.api_transport,
        )
    else:
        headers = {}
    state = load_state(args.state, vector_store_id=vector_store_id)
    operations = plan_operations(manifest, custody_root=args.custody_root, state=state)
    planned = {
        action: sum(1 for item in operations if item.action == action)
        for action in ("remove", "upsert", "noop")
    }
    result: dict[str, Any] = {
        "applied": args.apply,
        "manifest": str(manifest.path),
        "manifest_sha256": manifest.sha256,
        "manifest_byte_count": manifest.byte_count,
        "record_count": len(manifest.records),
        "vector_store_id": vector_store_id,
        "planned": planned,
        "examples": [
            {
                "action": item.action,
                "logical_document_id": item.logical_document_id,
                "reason": item.reason,
            }
            for item in operations[:10]
        ],
    }
    if args.apply:
        result["result"] = apply_operations(
            operations,
            state=state,
            state_path=args.state,
            api_base=args.api or default_api_base(args.cell),
            headers=headers,
            vector_store_id=vector_store_id,
            knowledge_base_id=args.knowledge_base_id,
            timeout=args.api_timeout_seconds,
            cell=args.cell,
            transport=args.api_transport,
        )
    if args.proof:
        write_json_atomic(args.proof, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    if not args.apply:
        print("\ndry-run only; no API calls or state writes were made")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
