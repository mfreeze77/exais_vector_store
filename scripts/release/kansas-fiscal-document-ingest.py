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
from svs_common.chunking import STATECIVICS_PAGE_MARKDOWN_PROFILE, statecivics_page_markdown_chunks
from svs_common.statecivics_statutes import (
    STATECIVICS_STATUTE_MARKDOWN_PROFILE, STATUTE_SOURCE_COLLECTION, STATUTE_EMBEDDING_PROFILE,
    StatuteHarvest, preflight_statute_harvest, parse_statute_markdown, MAX_DOCUMENT_BYTES,
)
from svs_common.statecivics_contract_pin import (
    DISPATCH_SHA256, DOCUMENT_BRANCH_SHA256, ENTITY_BRANCH_SHA256,
    ContractPinError, load_contract, verify_branch, verify_contract,
)
from svs_common.statecivics_record_adapter import (
    ENTITY_PATHS, LIVE_PATH,
    adapt_manifest, admit_entity_records, classify_record, dispatch_rule,
)
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
    source_page_chunking_profile: str | None = None
    statute_evidence: dict[str, Any] | None = None
    content_exclusion: str | None = None


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


def _validate_source_family(source_family: str, vector_store_slug: str | None = None) -> None:
    if source_family not in {'kansas-fiscal-documents', 'kansas-statutes'}:
        raise FiscalIngestError('unsupported source family')
    if source_family == 'kansas-statutes' and vector_store_slug is not None and vector_store_slug != 'kansas-statutes':
        raise FiscalIngestError('statute source family requires the kansas-statutes vector store slug')


def _validate_statute_record(record: dict[str, Any]) -> None:
    if record.get('artifact_type') != 'statute':
        raise FiscalIngestError('statute source family requires statute records')
    if record['ingestion']['action'] == 'upsert' and str(record.get('mime_type', '')).split(';', 1)[0].lower() != 'text/markdown':
        raise FiscalIngestError('statute upserts require retained Markdown')


def _statute_evidence(record: dict[str, Any], content: bytes, harvest: StatuteHarvest) -> dict[str, Any]:
    found = harvest.documents.get((record['citation_url'], record['content_hash_sha256']))
    if found is None:
        raise FiscalIngestError('approved export URL/rendered hash does not match the reviewed statute harvest')
    if len(content) != found['rendered_bytes']:
        raise FiscalIngestError('statute custody bytes differ from the reviewed harvest')
    parse_statute_markdown(content.decode('utf-8', errors='strict'),
                          expected_sha256=found['rendered_sha256'], expected_source_url=found['source_url'])
    return dict(found)


#: This consumer reads the document branch of the StateCivics retrieval-export
#: contract and nothing else.  Entity-projection records live behind a separate
#: branch with a separate pin (WAVE-134); a document run must neither validate
#: them nor be blocked by changes to them.
CONSUMED_CONTRACT_BRANCH = "document"


def verify_contract_pin(contract_path: Path, *, consumer: str = CONSUMED_CONTRACT_BRANCH) -> dict[str, str]:
    """Refuse to ingest against a contract other than the pinned one.

    Verifies the branch this consumer reads AND the top-level routing predicate
    that delivers records to it: a routing change alone can redirect a record to
    the other branch while leaving both branch subtrees byte-identical.

    The digests are computed from the schema this run was handed, never fetched,
    so the check cannot be satisfied by a contract the operator did not supply.
    """
    return verify_contract(load_contract(contract_path), consumer)


def load_manifest(
    path: Path,
    *,
    instance_slug: str = DEFAULT_INSTANCE_SLUG,
    vector_store_slug: str = DEFAULT_VECTOR_STORE_SLUG,
    source_family: str = "kansas-fiscal-documents",
    contract_schema: Path | None = None,
    entrypoint: str = "kansas-fiscal-document-ingest.py",
) -> LoadedManifest:
    """Load a desired-state manifest. ``contract_schema`` is REQUIRED.

    It is a keyword with a ``None`` default only so the refusal can name the
    entrypoint that omitted it. An optional pin is not a pin: for a while only
    one caller passed a schema while the source package declared the pin as
    though every caller did.

    This consumer's callers are NOT enumerated here. Any hand-written list of
    them goes stale silently, which is exactly how this defect survived two
    rounds. They are discovered instead by
    ``tests/test_statecivics_contract_pin.py::test_every_load_manifest_caller_enforces_the_pin``,
    which walks the tracked source tree with ``ast``, resolves each call's
    callee by module identity, and requires the discovered set to equal the
    ``contractPin.enforcedAt`` declaration exactly in both directions.
    """
    _validate_source_family(source_family, vector_store_slug)
    if contract_schema is None:
        raise FiscalIngestError(
            f"{entrypoint}: --contract-schema is required; refusing to ingest "
            f"{path} without verifying the StateCivics contract pin"
        )
    verify_contract_pin(contract_schema)
    # The routing predicate, taken from the contract rather than guessed. The
    # dispatch pin verified just above is computed over exactly this object.
    rule = dispatch_rule(load_contract(contract_schema))
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
        if classify_record(record, rule) != rule.absent_pin:
            # The contract's OWN dispatch, read from the schema this run was
            # handed. Before this guard an entity record failed here as
            # "missing logical_document_id" -- a shape error wearing a data
            # error's clothes, which is the defect WAVE-134 opened on.
            #
            # Document behaviour is untouched: for an untagged record this is a
            # two-key read that returns the document branch and falls through.
            raise FiscalIngestError(
                f"{path}:{line_number}: this is an ENTITY record and the document consumer "
                f"cannot ingest it. Read it with --record-kind entity, which routes through "
                f"the entity branch of the contract and its own pin."
            )
        _validate_record(
            record,
            line_number=line_number,
            instance_slug=instance_slug,
            vector_store_slug=vector_store_slug,
        )
        if source_family == "kansas-statutes":
            _validate_statute_record(record)
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


#: Entity records are read by their OWN entrypoint, which verifies the ENTITY
#: and DISPATCH pins -- never the document pin. A consumer must not verify a
#: branch it does not read, or unrelated upstream work blocks it.
CONSUMED_ENTITY_CONTRACT_BRANCH = "entity"


@dataclass(frozen=True)
class LoadedEntityManifest:
    """Entity projections admitted for ONE path, and nothing else.

    Deliberately not a ``LoadedManifest``: a caller holding one of these cannot
    hand it to ``plan_operations``, which speaks in ``logical_document_id``.
    The two kinds stay separable in the type system, not by convention.
    """

    path: Path
    sha256: str
    byte_count: int
    entity_path: str
    records: tuple[dict[str, Any], ...]
    verified_pins: tuple[str, ...]
    unvalidated_remote_refs: tuple[str, ...]


def load_entity_manifest(
    path: Path,
    *,
    contract_schema: Path | None = None,
    entity_path: str = LIVE_PATH,
    entrypoint: str = "kansas-fiscal-document-ingest.py --record-kind entity",
) -> LoadedEntityManifest:
    """Read a manifest of ENTITY projections for one path, or refuse.

    ``contract_schema`` is REQUIRED, for the same reason it is on the document
    consumer and with the same shape of refusal: an optional pin is not a pin.

    The refusal order is the point of this function, and it is structural.
    ``adapt_manifest`` verifies the entity and dispatch pins, validates every
    record against the branch the contract's own dispatch chose, and enforces
    envelope/payload agreement. Only then does ``admit_entity_records`` apply
    the eligibility gate, which refuses a ``candidate`` revision for the live
    store BEFORE this function returns -- so a caller never holds records it
    could embed. Nothing here calls an API, an embedding provider or an index.
    """
    if entity_path not in ENTITY_PATHS:
        raise FiscalIngestError(
            f"{entrypoint}: unknown --entity-path {entity_path!r}; expected one of "
            f"{list(ENTITY_PATHS)}"
        )
    if contract_schema is None:
        raise FiscalIngestError(
            f"{entrypoint}: --contract-schema is required; refusing to ingest "
            f"{path} without verifying the StateCivics contract pin"
        )
    adapted = adapt_manifest(path, contract_schema=contract_schema)
    if adapted.document_records:
        raise FiscalIngestError(
            f"{path}: contains {len(adapted.document_records)} DOCUMENT record(s); the entity "
            "entrypoint reads the entity branch only. Split the manifest, or read it without "
            "--record-kind entity."
        )
    if not adapted.entity_records:
        raise FiscalIngestError(f"{path}: manifest contains no entity records")
    # THE GATE. Raises CandidateRecordRefused for a candidate on the live path,
    # and RemovalRecordNotStageable for a tombstone, before anything is returned.
    admitted = admit_entity_records(adapted.entity_records, path=entity_path)
    payload = Path(path).read_bytes()
    return LoadedEntityManifest(
        path=Path(path),
        sha256=hashlib.sha256(payload).hexdigest(),
        byte_count=len(payload),
        entity_path=entity_path,
        records=admitted,
        verified_pins=adapted.verified_pins,
        unvalidated_remote_refs=adapted.unvalidated_remote_refs,
    )


def read_custody_object(custody_root: Path, record: dict[str, Any], *, max_bytes: int | None = None) -> bytes:
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
    if max_bytes is not None:
        with path.open('rb') as stream:
            content = stream.read(max_bytes + 1)
        if len(content) > max_bytes:
            raise FiscalIngestError('custody object exceeds the source byte bound')
    else:
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
    source_page_chunking_profile: str | None = None,
    source_family: str = "kansas-fiscal-documents",
    statute_harvest: StatuteHarvest | None = None,
) -> list[PlannedOperation]:
    _validate_source_family(source_family)
    if source_family == "kansas-statutes" and (statute_harvest is None or source_page_chunking_profile is not None):
        raise FiscalIngestError("statutes require reviewed harvest and reject the fiscal page profile")
    if source_family != "kansas-statutes" and statute_harvest is not None:
        raise FiscalIngestError("statute harvest requires explicit statute source family")
    if source_page_chunking_profile not in (None, STATECIVICS_PAGE_MARKDOWN_PROFILE):
        raise FiscalIngestError('unsupported source page chunking profile')
    prior = state["records"]
    operations: list[PlannedOperation] = []
    for record in manifest.records:
        logical_id = record["logical_document_id"]
        action = record["ingestion"]["action"]
        previous = prior.get(logical_id)
        if source_family == 'kansas-statutes':
            _validate_statute_record(record)
        evidence = None
        if action == "upsert":
            content = read_custody_object(custody_root, record, **({'max_bytes': MAX_DOCUMENT_BYTES} if source_family == 'kansas-statutes' else {}))
            if source_family == 'kansas-statutes':
                evidence = _statute_evidence(record, content, statute_harvest)
                if evidence['classification'] != 'substantive_body':
                    removal = isinstance(previous, dict) and previous.get('action') == 'upsert' and previous.get('vector_store_file_id')
                    operations.append(PlannedOperation('remove' if removal else 'noop', logical_id,
                        'statute content excluded: ' + evidence['classification'], record,
                        statute_evidence=evidence, content_exclusion=evidence['classification']))
                    continue
            mime_type = str(record.get('mime_type') or '').split(';', 1)[0].lower()
            desired_profile = source_page_chunking_profile if mime_type in _SUPPORTED_TEXT_MIME_TYPES else None
            if desired_profile:
                _page_chunking_attributes(record, content)
            if (
                isinstance(previous, dict)
                and previous.get("action") == "upsert"
                and previous.get("record_digest_sha256")
                == record["record_digest_sha256"]
                and previous.get("vector_store_file_id")
                and (desired_profile is None or previous.get('source_page_chunking_profile') == desired_profile)
                and (evidence is None or (previous.get('source_text_chunking_profile') == STATECIVICS_STATUTE_MARKDOWN_PROFILE
                     and previous.get('statute_evidence_context_sha256') == evidence['evidence_context_sha256']))
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
                        desired_profile,
                        evidence,
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


def ingest_idempotency_key(vector_store_id: str, record: dict[str, Any], *, source_page_chunking_profile: str | None = None, statute_evidence: dict[str, Any] | None = None) -> str:
    fields = {
            "vector_store_id": vector_store_id,
            "logical_document_id": record["logical_document_id"],
            "record_digest_sha256": record["record_digest_sha256"],
            "action": record["ingestion"]["action"],
        }
    if source_page_chunking_profile is not None:
        fields['source_page_chunking_profile'] = source_page_chunking_profile
    if statute_evidence is not None:
        fields['source_text_chunking_profile'] = STATECIVICS_STATUTE_MARKDOWN_PROFILE
        fields['statute_evidence_context_sha256'] = statute_evidence['evidence_context_sha256']
    value = canonical_json(fields)
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


def _page_chunking_attributes(record: dict[str, Any], content: bytes) -> dict[str, Any]:
    """Validate the exact retained text; this does not assert PDF extraction QA."""
    if len(content) > 16 * 1024 * 1024:
        raise FiscalIngestError('page Markdown exceeds 16 MiB UTF-8')
    declared_counts = [record[key] for key in ('source_page_count', 'page_count', 'pages') if key in record]
    if any(value is not None and (type(value) is not int or not 1 <= value <= 10000) for value in declared_counts):
        raise FiscalIngestError('declared source page counts must be integers in 1..10000')
    if declared_counts and any(value != declared_counts[0] for value in declared_counts):
        raise FiscalIngestError('conflicting declared source page counts')
    declared_count = declared_counts[0] if declared_counts else None
    try:
        chunks = statecivics_page_markdown_chunks(content.decode('utf-8', errors='strict'),
                                                expected_sha256=record['content_hash_sha256'],
                                                declared_page_count=declared_count)
    except (UnicodeError, ValueError) as exc:
        raise FiscalIngestError(f'invalid retained page Markdown: {exc}') from exc
    if not chunks:
        raise FiscalIngestError('retained page Markdown has no content chunks')
    attrs = {
        'source_page_chunking_profile': STATECIVICS_PAGE_MARKDOWN_PROFILE,
        'extraction_content_hash_sha256': record['content_hash_sha256'],
        'parsed_page_count': chunks[0].metadata['parsed_page_count'],
    }
    if declared_count is not None:
        attrs['source_page_count'] = declared_count
    return attrs


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
    key = ingest_idempotency_key(vector_store_id, record, source_page_chunking_profile=operation.source_page_chunking_profile, statute_evidence=operation.statute_evidence)
    attributes = _record_attributes(record)
    if operation.statute_evidence is not None:
        _validate_statute_record(record)
        if operation.content_exclusion or operation.statute_evidence.get('classification') != 'substantive_body':
            raise FiscalIngestError('excluded statute content cannot be submitted')
        if operation.source_page_chunking_profile is not None:
            raise FiscalIngestError('simultaneous statute/page chunking is forbidden')
        attributes.pop('marker_profile', None)
        attributes.pop('fiscal_year', None)
        attributes.update({
            'source_collection': STATUTE_SOURCE_COLLECTION,
            'source_text_chunking_profile': STATECIVICS_STATUTE_MARKDOWN_PROFILE,
            'extraction_content_hash_sha256': record['content_hash_sha256'],
            'statute_harvest_evidence': operation.statute_evidence,
        })
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
        if operation.source_page_chunking_profile is not None:
            if operation.source_page_chunking_profile != STATECIVICS_PAGE_MARKDOWN_PROFILE:
                raise FiscalIngestError('unsupported source page chunking profile')
            attributes.update(_page_chunking_attributes(record, content))
        try:
            text_content = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise FiscalIngestError(
                f"record {record['export_record_id']} declares UTF-8 text but bytes do not decode"
            ) from exc
        document_request = {
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
            }
        if operation.source_page_chunking_profile is not None or operation.statute_evidence is not None:
            desired_chunker = STATECIVICS_STATUTE_MARKDOWN_PROFILE if operation.statute_evidence is not None else STATECIVICS_PAGE_MARKDOWN_PROFILE
            preview = api_json(
                'POST', api_base, '/api/v1/ingestion/preview', {**document_request, 'persist': False},
                headers=headers, timeout=timeout, cell=cell, transport=transport,
            )
            if (not isinstance(preview, dict)
                    or preview.get('chunker') != desired_chunker
                    or preview.get('mode') != document_request['mode']
                    or type(preview.get('estimated_chunks')) is not int
                    or not 1 <= preview['estimated_chunks'] <= 20000
                    or (operation.statute_evidence is not None and preview.get('embedding_profile_id') != STATUTE_EMBEDDING_PROFILE)):
                raise FiscalIngestError('server preview did not confirm the requested page/text chunking profile, embedding profile and valid chunk count')
        response = api_json(
            "POST", api_base, "/api/v1/documents/ingest", document_request,
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
            if record["ingestion"]["action"] == "remove" or operation.content_exclusion is not None:
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
            if operation.source_page_chunking_profile is not None:
                state['records'][logical_id]['source_page_chunking_profile'] = operation.source_page_chunking_profile
            if operation.statute_evidence is not None:
                state['records'][logical_id]['source_text_chunking_profile'] = STATECIVICS_STATUTE_MARKDOWN_PROFILE
                state['records'][logical_id]['statute_evidence_context_sha256'] = operation.statute_evidence['evidence_context_sha256']
            counts["upserted"] += 1
        write_json_atomic(state_path, state)
    return counts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-family', choices=['kansas-fiscal-documents', 'kansas-statutes'], default='kansas-fiscal-documents')
    parser.add_argument('--harvest-manifest', type=Path)
    parser.add_argument('--harvest-root', type=Path)
    parser.add_argument('--harvest-manifest-sha256')
    parser.add_argument("--cell", default=DEFAULT_CELL)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--contract-schema", type=Path, required=True,
        help=("Path to the StateCivics retrieval-export schema this manifest was produced "
              "against. Its document branch must match the pinned digest; the entity branch "
              "is pinned separately and is not read here."),
    )
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
    parser.add_argument(
        "--record-kind", choices=["document", "entity"], default="document",
        help="which branch of the StateCivics contract this manifest carries",
    )
    parser.add_argument(
        "--entity-path", choices=list(ENTITY_PATHS), default=LIVE_PATH,
        help="destination for --record-kind entity; the live store refuses candidates",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument('--source-page-chunking-profile', choices=[STATECIVICS_PAGE_MARKDOWN_PROFILE],
                        help='opt retained text into exact page coordinates; PDF/Marker requests remain unchanged')
    return parser.parse_args()


def _report_entity_manifest(
    manifest: LoadedEntityManifest, *, proof: Path | None, apply_requested: bool
) -> int:
    """Report what the entity branch admitted. No API call, ever, from here."""
    result: dict[str, Any] = {
        "applied": False,
        "record_kind": "entity",
        "entity_path": manifest.entity_path,
        "manifest": str(manifest.path),
        "manifest_sha256": manifest.sha256,
        "manifest_byte_count": manifest.byte_count,
        "record_count": len(manifest.records),
        "verified_pins": list(manifest.verified_pins),
        "unvalidated_remote_refs": list(manifest.unvalidated_remote_refs),
        "admitted": [
            {
                "entity_type": record["entity_type"],
                "entity_logical_id": record["entity_logical_id"],
                "entity_revision": record["entity_revision"],
                "eligibility_status": record["eligibility"]["status"],
            }
            for record in manifest.records
        ],
    }
    if proof:
        write_json_atomic(proof, result)
    print(json.dumps(result, indent=2, sort_keys=True))
    print(
        "\nentity manifest read and gated; descriptor staging is not implemented in this "
        "entrypoint, so no API call, embedding or index write was made"
        + (" (--apply was requested and is not honoured here)" if apply_requested else "")
    )
    return 0


def main() -> int:
    args = parse_args()
    source_family = getattr(args, 'source_family', 'kansas-fiscal-documents')
    _validate_source_family(source_family, args.vector_store_slug)
    harvest = None
    if source_family == 'kansas-statutes':
        if not all((args.harvest_manifest, args.harvest_root, args.harvest_manifest_sha256)):
            raise FiscalIngestError('statute source requires --harvest-manifest, --harvest-root and --harvest-manifest-sha256')
        if args.allow_create_vector_store or (args.apply and not args.vector_store_id):
            raise FiscalIngestError('statute application requires an existing explicit vector store; creation is not supported')
        harvest = preflight_statute_harvest(args.harvest_manifest, args.harvest_root,
                                          expected_manifest_sha256=args.harvest_manifest_sha256)
    elif any(getattr(args, k, None) is not None for k in ('harvest_manifest', 'harvest_root', 'harvest_manifest_sha256')):
        raise FiscalIngestError('harvest flags require the explicit statute source family')
    if getattr(args, "record_kind", "document") == "entity":
        # The entity branch, read and gated BEFORE any API work. `--apply` has
        # not been consulted yet and no header, token or store has been touched,
        # so a candidate offered to the live store is refused having cost
        # nothing. Staging entity descriptors is not implemented here: this
        # entrypoint reads, validates and gates, and deployment stays deferred.
        return _report_entity_manifest(
            load_entity_manifest(
                args.manifest,
                contract_schema=args.contract_schema,
                entity_path=args.entity_path,
            ),
            proof=args.proof,
            apply_requested=args.apply,
        )
    if getattr(args, "entity_path", LIVE_PATH) != LIVE_PATH:
        raise FiscalIngestError("--entity-path requires --record-kind entity")
    manifest = load_manifest(
        args.manifest,
        instance_slug=args.instance_slug,
        vector_store_slug=args.vector_store_slug,
        source_family=source_family,
        contract_schema=args.contract_schema,
    )
    vector_store_id = args.vector_store_id or ("vs_kansas_statutes_pending" if source_family == "kansas-statutes" else "vs_kansas_fiscal_documents_pending")
    prepared = None
    if source_family == 'kansas-statutes':
        state = load_state(args.state, vector_store_id=vector_store_id)
        prepared = plan_operations(manifest, custody_root=args.custody_root, state=state,
                                   source_family=source_family, statute_harvest=harvest,
                                   source_page_chunking_profile=args.source_page_chunking_profile)
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
            attributes={
                "corpus": "kansas_fiscal_documents",
                "source_collection": "statecivics-fiscal-ledger",
                "production_ready": "false",
                "created_by": "scripts/release/kansas-fiscal-document-ingest.py",
            },
        )
    else:
        headers = {}
    state = load_state(args.state, vector_store_id=vector_store_id)
    operations = prepared if prepared is not None else plan_operations(manifest, custody_root=args.custody_root, state=state,
                                 source_page_chunking_profile=args.source_page_chunking_profile)
    planned = {
        action: sum(1 for item in operations if item.action == action)
        for action in ("remove", "upsert", "noop")
    }
    result: dict[str, Any] = {
        "applied": args.apply,
        "source_family": source_family,
        "harvest_manifest_sha256": harvest.manifest_sha256 if harvest else None,
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
