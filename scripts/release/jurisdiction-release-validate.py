#!/usr/bin/env python3
"""Validate a jurisdiction document release bundle at its delivered location.

Independently callable: it takes a bundle directory, not an exporter run, and
re-derives everything from the delivered bytes. It never imports the exporter,
so an exporter bug cannot validate itself away. Stdlib only; no embeddings, no
ExAIS API, no StateCivics database.

    python scripts/release/jurisdiction-release-validate.py --bundle <dir>

Exit status is 0 only when every check passed. A check that cannot be run is an
error, never a skip: a missing artifact fails the release rather than shrinking
the set of things the release claims.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jurisdiction_release_contract import (  # noqa: E402
    COLLECTIONS_BY_ID,
    RELEASE_MANIFEST_SCHEMA_ID,
    SOURCE_DOCUMENT_SCHEMA_ID,
    RoutingError,
    ValidationReport,
    canonical_source_url,
    document_version_id,
    inventory_fingerprint,
    load_release_schemas,
    payload_fingerprint,
    route_document,
    sha256_bytes,
    sha256_text,
)

TEXT_ARTIFACT_ROLES = {"normalized_text", "verbatim", "structured"}


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_bundle(bundle: Path, *, expect_kind: str | None = None) -> ValidationReport:
    report = ValidationReport(bundle=str(bundle))
    release_schema, document_schema = load_release_schemas()

    manifest_path = bundle / "release-manifest.json"
    if not manifest_path.exists():
        report.add("error", "MANIFEST_MISSING", str(manifest_path), "bundle has no release-manifest.json")
        return report

    manifest_bytes = manifest_path.read_bytes()
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        report.add("error", "MANIFEST_UNREADABLE", str(manifest_path), f"cannot parse manifest: {error}")
        return report

    report.checks["manifest_sha256"] = sha256_bytes(manifest_bytes)

    if manifest.get("schema") != RELEASE_MANIFEST_SCHEMA_ID:
        report.add(
            "error", "MANIFEST_SCHEMA_ID", "release-manifest.json",
            f"schema is {manifest.get('schema')!r}, expected {RELEASE_MANIFEST_SCHEMA_ID!r}",
        )
        return report

    for error in release_schema.validate(manifest):
        report.add("error", "MANIFEST_SCHEMA", f"release-manifest.json:{error.path}", str(error))
    if report.errors:
        return report

    _check_schema_provenance(manifest, release_schema, document_schema, report)
    _check_bundle_kind(manifest, expect_kind, report)

    declared_collections = {entry["collection_id"] for entry in manifest["collections"]}
    seen_documents: dict[str, str] = {}
    recomputed_files = 0
    recomputed_present_bytes = 0
    resolved_refs = 0
    unavailable_refs = 0

    for entry in manifest["documents"]:
        doc_id = entry["source_document_id"]
        location = entry["record_path"]

        if doc_id in seen_documents:
            report.add(
                "error", "DUPLICATE_DOCUMENT", location,
                f"{doc_id} appears twice in the inventory; a release carries one active version per document",
            )
        seen_documents[doc_id] = entry["document_version_id"]

        if entry["collection_id"] not in declared_collections:
            report.add(
                "error", "UNDECLARED_COLLECTION", location,
                f"{entry['collection_id']} is not declared in collections[]",
            )
        if entry["collection_id"] not in COLLECTIONS_BY_ID:
            report.add(
                "error", "UNREGISTERED_COLLECTION", location,
                f"{entry['collection_id']} is not a registered master collection",
            )

        record_path = bundle / entry["record_path"]
        if not record_path.exists():
            report.add("error", "RECORD_MISSING", location, "record file is absent from the bundle")
            continue
        record_bytes = record_path.read_bytes()
        actual_record_sha = sha256_bytes(record_bytes)
        if actual_record_sha != entry["record_sha256"]:
            report.add(
                "error", "RECORD_HASH_MISMATCH", location,
                f"record hashes to {actual_record_sha} but the manifest records {entry['record_sha256']}",
            )
        try:
            record = json.loads(record_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            report.add("error", "RECORD_UNREADABLE", location, f"cannot parse record: {error}")
            continue

        if record.get("schema") != SOURCE_DOCUMENT_SCHEMA_ID:
            report.add(
                "error", "RECORD_SCHEMA_ID", location,
                f"schema is {record.get('schema')!r}, expected {SOURCE_DOCUMENT_SCHEMA_ID!r}",
            )
            continue
        schema_errors = document_schema.validate(record)
        for error in schema_errors:
            report.add("error", "RECORD_SCHEMA", f"{location}:{error.path}", str(error))
        if schema_errors:
            continue

        _check_identity(record, entry, location, report)

        actual_payload = payload_fingerprint(record)
        if actual_payload != entry["payload_sha256"]:
            report.add(
                "error", "PAYLOAD_HASH_MISMATCH", location,
                f"payload fingerprint is {actual_payload} but the manifest records {entry['payload_sha256']}",
            )

        artifacts, file_errors, present_bytes, file_count = _check_files(bundle, record, entry, location, report)
        recomputed_files += file_count
        recomputed_present_bytes += present_bytes

        if not file_errors:
            _check_content_hashes(record, artifacts, location, report)
            available, unavailable = _check_evidence(record, artifacts, location, report)
            resolved_refs += available
            unavailable_refs += unavailable

        _check_routing(record, location, report)
        _check_lineage(record, location, report)
        _check_meaning(record, location, report)

    _check_inventory(manifest, recomputed_files, recomputed_present_bytes, report)
    _check_update_block(manifest, seen_documents, report)

    report.checks.update({
        "release_id": manifest["release"]["release_id"],
        "bundle_kind": manifest["release"]["bundle_kind"],
        "document_count": len(manifest["documents"]),
        "file_count_recomputed": recomputed_files,
        "present_byte_count_recomputed": recomputed_present_bytes,
        "inventory_sha256_recomputed": inventory_fingerprint(manifest["documents"]),
        "evidence_references_resolved": resolved_refs,
        "evidence_references_unavailable": unavailable_refs,
        "collections": sorted(declared_collections),
    })
    return report


def _check_schema_provenance(manifest, release_schema, document_schema, report: ValidationReport) -> None:
    on_disk = {
        "release_manifest": release_schema,
        "source_document": document_schema,
    }
    for entry in manifest["release"]["schemas"]:
        loaded = on_disk.get(entry["role"])
        if loaded is None:
            report.add("error", "SCHEMA_ROLE", "release.schemas", f"unknown schema role {entry['role']!r}")
            continue
        if entry["schema_id"] != loaded.schema_id:
            report.add(
                "error", "SCHEMA_ID_MISMATCH", "release.schemas",
                f"{entry['role']} declares {entry['schema_id']!r}, this checkout has {loaded.schema_id!r}",
            )
        if entry["sha256"] != loaded.sha256:
            # The bundle is still internally valid; it was produced against a
            # different revision of the contract. The consumer must be told.
            report.add(
                "warning", "SCHEMA_REVISION_DRIFT", "release.schemas",
                f"{entry['role']} was produced against schema sha256 {entry['sha256'][:16]}…, "
                f"this checkout has {loaded.sha256[:16]}…",
            )


def _check_bundle_kind(manifest, expect_kind: str | None, report: ValidationReport) -> None:
    kind = manifest["release"]["bundle_kind"]
    if expect_kind and kind != expect_kind:
        report.add(
            "error", "BUNDLE_KIND", "release.bundle_kind",
            f"bundle declares {kind!r} but {expect_kind!r} was required",
        )
    if manifest["release"]["producer"]["dirty_worktree"]:
        report.add(
            "warning", "DIRTY_PRODUCER", "release.producer",
            "produced from a dirty worktree; release.producer.commit does not reproduce this bundle",
        )
    if kind == "production" and manifest["release"]["producer"]["commit"] == "unknown":
        report.add(
            "error", "PRODUCER_COMMIT_UNKNOWN", "release.producer",
            "a production bundle must record the producing commit",
        )


def _check_identity(record, entry, location: str, report: ValidationReport) -> None:
    identity = record["identity"]
    if identity["source_document_id"] != entry["source_document_id"]:
        report.add(
            "error", "IDENTITY_MISMATCH", location,
            "record source_document_id disagrees with the manifest entry",
        )
    if identity["document_version_id"] != entry["document_version_id"]:
        report.add(
            "error", "VERSION_MISMATCH", location,
            "record document_version_id disagrees with the manifest entry",
        )
    if identity["collection_id"] != entry["collection_id"]:
        report.add(
            "error", "COLLECTION_MISMATCH", location,
            "record collection_id disagrees with the manifest entry",
        )
    if not identity["source_document_id"].startswith(identity["collection_id"] + ":"):
        report.add(
            "error", "IDENTITY_NOT_SCOPED", location,
            f"{identity['source_document_id']} is not scoped to its collection",
        )

    original_sha = record["source"]["retained_original"]["sha256"]
    expected_version = document_version_id(identity["source_document_id"], original_sha)
    if identity["document_version_id"] != expected_version:
        report.add(
            "error", "VERSION_NOT_DERIVED_FROM_ORIGINAL", location,
            f"document_version_id should be {expected_version} for retained original {original_sha[:16]}…",
        )

    if identity["prior_version_id"] is None and identity["version_ordinal"] != 1:
        report.add(
            "error", "VERSION_ORDINAL", location,
            "version_ordinal is not 1 but no prior_version_id is recorded",
        )
    if identity["prior_version_id"] == identity["document_version_id"]:
        report.add("error", "VERSION_SELF_PRIOR", location, "prior_version_id equals the current version")


def _check_files(bundle: Path, record, entry, location: str, report: ValidationReport):
    """Re-hash every delivered file. Returns (role -> bytes, had_error, bytes, count)."""
    artifacts: dict[str, bytes] = {}
    had_error = False
    present_bytes = 0
    for file_entry in entry["files"]:
        path = bundle / file_entry["path"]
        if not file_entry["present"]:
            if not file_entry.get("reference_uri"):
                report.add(
                    "error", "REFERENCE_URI_MISSING", file_entry["path"],
                    "file is not present in the bundle and carries no reference_uri to resolve it",
                )
                had_error = True
            continue
        if not path.exists():
            report.add(
                "error", "FILE_MISSING", file_entry["path"],
                "manifest marks this file present but it is absent from the bundle",
            )
            had_error = True
            continue
        payload = path.read_bytes()
        actual = sha256_bytes(payload)
        if actual != file_entry["sha256"]:
            report.add(
                "error", "FILE_HASH_MISMATCH", file_entry["path"],
                f"file hashes to {actual} but the manifest records {file_entry['sha256']}",
            )
            had_error = True
        if len(payload) != file_entry["byte_count"]:
            report.add(
                "error", "FILE_SIZE_MISMATCH", file_entry["path"],
                f"file is {len(payload)} bytes but the manifest records {file_entry['byte_count']}",
            )
            had_error = True
        present_bytes += len(payload)
        if file_entry["role"] != "record":
            artifacts[file_entry["role"]] = payload
    return artifacts, had_error, present_bytes, len(entry["files"])


def _check_content_hashes(record, artifacts: dict[str, bytes], location: str, report: ValidationReport) -> None:
    content = record["content"]
    for role, block, needs_text in (
        ("verbatim", content["verbatim"], False),
        ("normalized_text", content["normalized_text"], True),
        ("structured", content["structured"], False),
    ):
        payload = artifacts.get(role)
        if payload is None:
            report.add(
                "error", "CONTENT_ARTIFACT_MISSING", f"{location}:content.{role}",
                f"record declares a {role} artifact but the bundle delivers no file with that role",
            )
            continue
        actual = sha256_bytes(payload)
        if actual != block["sha256"]:
            report.add(
                "error", "CONTENT_HASH_MISMATCH", f"{location}:content.{role}",
                f"{role} hashes to {actual} but the record declares {block['sha256']}",
            )
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            report.add("error", "CONTENT_NOT_UTF8", f"{location}:content.{role}", f"{role} is not valid UTF-8")
            continue
        if "char_count" in block and len(text) != block["char_count"]:
            report.add(
                "error", "CONTENT_CHAR_COUNT", f"{location}:content.{role}",
                f"{role} has {len(text)} characters but the record declares {block['char_count']}",
            )
        if needs_text and not text.strip():
            report.add(
                "error", "EMPTY_EXTRACTION", f"{location}:content.{role}",
                "normalized text is empty; an empty extraction must not be released as extracted",
            )

    original = record["source"]["retained_original"]
    retained = artifacts.get("retained_original")
    if retained is not None:
        actual = sha256_bytes(retained)
        if actual != original["sha256"]:
            report.add(
                "error", "ORIGINAL_HASH_MISMATCH", f"{location}:source.retained_original",
                f"retained original hashes to {actual} but the record declares {original['sha256']}",
            )
        if len(retained) != original["byte_count"]:
            report.add(
                "error", "ORIGINAL_SIZE_MISMATCH", f"{location}:source.retained_original",
                f"retained original is {len(retained)} bytes, record declares {original['byte_count']}",
            )
    elif original["local_path"]:
        report.add(
            "error", "ORIGINAL_NOT_DELIVERED", f"{location}:source.retained_original",
            f"record points local_path at {original['local_path']} but no such file is delivered",
        )

    structured_payload = artifacts.get("structured")
    if structured_payload is not None:
        try:
            structured = json.loads(structured_payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            report.add("error", "STRUCTURED_UNREADABLE", f"{location}:content.structured", "structured artifact is not JSON")
            return
        components = structured.get("components") or []
        if not components:
            report.add(
                "error", "STRUCTURED_EMPTY", f"{location}:content.structured",
                "structured artifact carries no components",
            )
        declared = content["structured"]
        root_key = declared.get("root_source_component_key")
        keys = {component.get("source_component_key") for component in components}
        if root_key and root_key not in keys:
            report.add(
                "error", "STRUCTURED_ROOT_MISSING", f"{location}:content.structured",
                f"declared root component {root_key!r} is not in the component set",
            )
        for component in components:
            parent = component.get("parent_source_component_key")
            if parent and parent not in keys:
                report.add(
                    "error", "STRUCTURED_DANGLING_PARENT", f"{location}:content.structured",
                    f"component {component.get('source_component_key')!r} names absent parent {parent!r}",
                )


def _check_evidence(record, artifacts: dict[str, bytes], location: str, report: ValidationReport) -> tuple[int, int]:
    conventions = {c["name"] for c in record["evidence"]["coordinate_conventions"]}
    available = 0
    unavailable = 0

    source_revision = record["evidence"]["source_revision"]
    retained = artifacts.get("retained_original")
    if retained is not None and sha256_bytes(retained) != source_revision["artifact_sha256"]:
        report.add(
            "error", "SOURCE_REVISION_MISMATCH", f"{location}:evidence.source_revision",
            "source_revision.artifact_sha256 does not match the delivered retained original",
        )

    seen_ids: set[str] = set()
    for reference in record["evidence"]["references"]:
        ref_id = reference["ref_id"]
        where = f"{location}:evidence[{ref_id}]"
        if ref_id in seen_ids:
            report.add("error", "EVIDENCE_DUPLICATE_ID", where, "duplicate evidence ref_id")
        seen_ids.add(ref_id)

        if reference["availability"] == "unavailable":
            unavailable += 1
            if not reference.get("unavailable_reason"):
                report.add(
                    "error", "EVIDENCE_UNAVAILABLE_NO_REASON", where,
                    "an unavailable reference must record why the coordinate was not measured",
                )
            if reference.get("locator") and reference["locator"].get("start") is not None:
                report.add(
                    "error", "EVIDENCE_UNAVAILABLE_WITH_COORDINATE", where,
                    "reference is marked unavailable but still carries a coordinate",
                )
            if reference.get("quote"):
                report.add(
                    "error", "EVIDENCE_UNAVAILABLE_WITH_QUOTE", where,
                    "reference is marked unavailable but still carries a quote",
                )
            continue

        available += 1
        locator = reference.get("locator")
        if not locator:
            report.add("error", "EVIDENCE_NO_LOCATOR", where, "an available reference must carry a locator")
            continue
        if locator["convention"] not in conventions:
            report.add(
                "error", "EVIDENCE_UNDECLARED_CONVENTION", where,
                f"locator uses convention {locator['convention']!r}, which is not declared for this document",
            )
            continue

        artifact_role = reference["artifact"]
        if artifact_role == "source_revision":
            continue
        payload = artifacts.get(artifact_role)
        if payload is None:
            report.add(
                "error", "EVIDENCE_DANGLING_ARTIFACT", where,
                f"reference targets the {artifact_role} artifact, which is not delivered in this bundle",
            )
            continue
        if artifact_role not in TEXT_ARTIFACT_ROLES:
            report.add(
                "error", "EVIDENCE_NON_TEXT_COORDINATE", where,
                f"a character coordinate cannot be resolved against the {artifact_role} artifact",
            )
            continue

        text = payload.decode("utf-8", errors="replace")
        start, end = locator.get("start"), locator.get("end")
        if start is None or end is None:
            report.add("error", "EVIDENCE_INCOMPLETE_SPAN", where, "locator has no start/end span")
            continue
        if end < start:
            report.add("error", "EVIDENCE_INVERTED_SPAN", where, f"end {end} precedes start {start}")
            continue
        if end > len(text):
            report.add(
                "error", "EVIDENCE_OUT_OF_RANGE", where,
                f"span ends at {end} but the {artifact_role} artifact is {len(text)} characters",
            )
            continue
        quote = reference.get("quote")
        if quote is not None and text[start:end] != quote:
            report.add(
                "error", "EVIDENCE_QUOTE_MISMATCH", where,
                f"the span holds {text[start:end][:60]!r}, the reference quotes {quote[:60]!r}",
            )

    for block in (record["meaning"]["dates"], record["meaning"]["relationships"]):
        for item in block:
            ref = item.get("evidence_ref")
            if ref and ref not in seen_ids:
                report.add(
                    "error", "MEANING_DANGLING_EVIDENCE", f"{location}:meaning",
                    f"evidence_ref {ref!r} names no reference in evidence.references",
                )
    status_ref = record["meaning"]["status"]["evidence_ref"]
    if status_ref and status_ref not in seen_ids:
        report.add(
            "error", "STATUS_DANGLING_EVIDENCE", f"{location}:meaning.status",
            f"status evidence_ref {status_ref!r} names no reference in evidence.references",
        )
    return available, unavailable


def _check_routing(record, location: str, report: ValidationReport) -> None:
    """Re-route from the official URL alone.

    The exporter routes primarily by the publisher's listing category. Routing
    again from the URL is an independently derived answer, so agreement is real
    corroboration rather than the same computation twice.
    """
    url = record["source"]["official_url"]
    canonical = canonical_source_url(url)
    if canonical != url:
        report.add(
            "error", "URL_NOT_CANONICAL", f"{location}:source.official_url",
            f"{url!r} is not in canonical form; canonical is {canonical!r}",
        )
    try:
        spec = route_document(official_url=url)
    except RoutingError as error:
        report.add("error", "ROUTING_FAILED", f"{location}:source.official_url", str(error))
        return
    if spec.collection_id != record["identity"]["collection_id"]:
        report.add(
            "error", "ROUTING_DISAGREEMENT", f"{location}:source.official_url",
            f"the URL routes to {spec.collection_id} but the record claims {record['identity']['collection_id']}",
        )


def _check_lineage(record, location: str, report: ValidationReport) -> None:
    lineage = record["source"]["lineage"]
    known = {
        record["source"]["retained_original"]["sha256"],
        record["content"]["verbatim"]["sha256"],
        record["content"]["normalized_text"]["sha256"],
        record["content"]["structured"]["sha256"],
    }
    produced: set[str] = set()
    for index, step in enumerate(lineage):
        if step["input_sha256"] not in known | produced:
            report.add(
                "error", "LINEAGE_BROKEN", f"{location}:source.lineage[{index}]",
                f"step {step['step']!r} consumes {step['input_sha256'][:16]}…, which no earlier artifact produced",
            )
        produced.add(step["output_sha256"])
    for role in ("normalized_text", "structured"):
        digest = record["content"][role]["sha256"]
        if digest not in produced:
            report.add(
                "error", "LINEAGE_UNEXPLAINED_ARTIFACT", f"{location}:content.{role}",
                f"{role} hash {digest[:16]}… is not the output of any lineage step",
            )


def _check_meaning(record, location: str, report: ValidationReport) -> None:
    meaning = record["meaning"]
    quality = meaning["extraction_quality"]
    if quality["grade"] == "unusable" and quality["usable_text"]:
        report.add(
            "error", "QUALITY_CONTRADICTION", f"{location}:meaning.extraction_quality",
            "grade is 'unusable' but usable_text is true",
        )
    if meaning["review"]["status"] == "reviewed" and not meaning["review"].get("reviewer"):
        report.add(
            "error", "REVIEW_WITHOUT_REVIEWER", f"{location}:meaning.review",
            "a reviewed document must name its reviewer",
        )
    for relationship in meaning["relationships"]:
        if relationship["resolved"] and not relationship["evidence_ref"]:
            report.add(
                "error", "RESOLVED_WITHOUT_EVIDENCE", f"{location}:meaning.relationships",
                f"{relationship['predicate']!r} is marked resolved but cites no evidence",
            )
    if record["readiness"]["review"]["state"] == "complete" and meaning["review"]["status"] != "reviewed":
        report.add(
            "error", "READINESS_REVIEW_CONTRADICTION", f"{location}:readiness.review",
            "review readiness is complete but meaning.review.status is not 'reviewed'",
        )


def _check_inventory(manifest, file_count: int, present_bytes: int, report: ValidationReport) -> None:
    inventory = manifest["inventory"]
    if inventory["document_count"] != len(manifest["documents"]):
        report.add(
            "error", "INVENTORY_DOCUMENT_COUNT", "inventory.document_count",
            f"declares {inventory['document_count']}, the inventory holds {len(manifest['documents'])}",
        )
    declared_files = sum(len(entry["files"]) for entry in manifest["documents"])
    if inventory["file_count"] != declared_files:
        report.add(
            "error", "INVENTORY_FILE_COUNT", "inventory.file_count",
            f"declares {inventory['file_count']}, documents[] list {declared_files}",
        )
    if file_count != declared_files:
        report.add(
            "error", "INVENTORY_FILE_RECOUNT", "inventory.file_count",
            f"validator re-counted {file_count} file entries against {declared_files} declared",
        )
    if inventory["present_byte_count"] != present_bytes:
        report.add(
            "error", "INVENTORY_BYTE_COUNT", "inventory.present_byte_count",
            f"declares {inventory['present_byte_count']}, delivered files total {present_bytes}",
        )
    recomputed = inventory_fingerprint(manifest["documents"])
    if inventory["inventory_sha256"] != recomputed:
        report.add(
            "error", "INVENTORY_FINGERPRINT", "inventory.inventory_sha256",
            f"declares {inventory['inventory_sha256']}, recomputed {recomputed}",
        )
    by_collection = {row["collection_id"]: row["document_count"] for row in inventory.get("by_collection", [])}
    actual: dict[str, int] = {}
    for entry in manifest["documents"]:
        actual[entry["collection_id"]] = actual.get(entry["collection_id"], 0) + 1
    if by_collection and by_collection != actual:
        report.add(
            "error", "INVENTORY_BY_COLLECTION", "inventory.by_collection",
            f"declares {by_collection}, the inventory holds {actual}",
        )
    for collection in manifest["collections"]:
        released = collection["coverage"].get("released_count")
        if released is not None and released != actual.get(collection["collection_id"], 0):
            report.add(
                "error", "COVERAGE_COUNT", f"collections[{collection['collection_id']}]",
                f"coverage.released_count is {released}, the inventory holds "
                f"{actual.get(collection['collection_id'], 0)}",
            )
        if collection["coverage"]["state"] == "complete" and collection["coverage"].get("discovered_count") is None:
            report.add(
                "error", "COVERAGE_COMPLETE_UNPROVEN", f"collections[{collection['collection_id']}]",
                "coverage claims 'complete' without a discovered_count to compare against",
            )


def _check_update_block(manifest, seen: dict[str, str], report: ValidationReport) -> None:
    outcomes = manifest["update"]["outcomes"]
    classified = set(outcomes["unchanged"]) | set(outcomes["new"])
    classified |= {entry["source_document_id"] for entry in outcomes["changed"]}
    unclassified = sorted(set(seen) - classified)
    if unclassified:
        report.add(
            "error", "UPDATE_UNCLASSIFIED", "update.outcomes",
            f"{len(unclassified)} released document(s) have no unchanged/new/changed outcome: {unclassified[:5]}",
        )
    overlap = (set(outcomes["unchanged"]) & set(outcomes["new"])) | (
        set(outcomes["unchanged"]) & {entry["source_document_id"] for entry in outcomes["changed"]}
    )
    if overlap:
        report.add("error", "UPDATE_OVERLAP", "update.outcomes", f"documents in two outcome buckets: {sorted(overlap)}")
    for entry in outcomes["changed"]:
        if not entry.get("prior_retained"):
            report.add(
                "warning", "PRIOR_VERSION_NOT_RETAINED", "update.outcomes.changed",
                f"{entry['source_document_id']} changed and its prior version is not marked retained",
            )
    for entry in outcomes["unavailable"]:
        if re.search(r"\brepeal", entry["reason"], re.IGNORECASE):
            report.add(
                "error", "UNAVAILABLE_CLAIMS_REPEAL", "update.outcomes.unavailable",
                f"{entry['source_document_id']}: disappearance from a listing is not a repeal",
            )
    if manifest["update"]["previous_release_id"] is None and outcomes["changed"]:
        report.add(
            "error", "CHANGED_WITHOUT_BASELINE", "update.outcomes.changed",
            "changed documents are reported but no previous_release_id is recorded",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bundle", type=Path, required=True, help="directory holding release-manifest.json")
    parser.add_argument("--expect-kind", choices=["production", "starter", "fixture"], default=None)
    parser.add_argument("--output", type=Path, default=None, help="write the JSON validation report here")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    report = validate_bundle(args.bundle, expect_kind=args.expect_kind)
    payload = report.as_dict()

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if not args.quiet:
        print(f"bundle   {report.bundle}")
        for key, value in sorted(report.checks.items()):
            print(f"  {key:34s} {value}")
        for issue in report.issues:
            print(f"  {issue}")
        print(f"result   {'PASS' if report.passed else 'FAIL'} "
              f"({len(report.errors)} error(s), {len(report.warnings)} warning(s))")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
