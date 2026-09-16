#!/usr/bin/env python3
"""Shared contract code for jurisdiction document releases.

Nothing here imports an embedding provider, a vector store client, a database
driver or a consumer application, so the exporter and the validator both run on
a bare checkout. The only third-party import is ``jsonschema``, already a
declared dependency of every app in this repository.

Three things live here:

* schema validation, delegated to ``jsonschema`` rather than hand-rolled;
* the registered master-collection registry and the routing function derived
  from it, so no caller hand-lists which URLs belong to which store;
* the identity, hashing and canonical-JSON helpers the exporter and validator
  must agree on byte-for-byte.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import uuid

import jsonschema
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

# Two roots, deliberately. CODE_ROOT is where the scripts and schemas live and
# never moves; ROOT is the instance data tree, which tests and operators can
# point elsewhere. Conflating them sends the pipeline looking for its own
# schemas inside a disposable working copy.
CODE_ROOT = Path(__file__).resolve().parents[2]
ROOT = Path(os.environ.get("EXAIS_ROOT_OVERRIDE") or CODE_ROOT)
CONTRACTS = CODE_ROOT / "contracts"
RELEASE_MANIFEST_SCHEMA_PATH = CONTRACTS / "jurisdiction-document-release.schema.json"
SOURCE_DOCUMENT_SCHEMA_PATH = CONTRACTS / "jurisdiction-source-document.schema.json"

RELEASE_MANIFEST_SCHEMA_ID = "exais.jurisdiction.document_release.v1"
SOURCE_DOCUMENT_SCHEMA_ID = "exais.jurisdiction.source_document.v1"
CONTRACT_VERSION = "1.0.0"

# Reused verbatim from scripts/release/topeka-code-workbench-project.py (WAVE-119)
# so a component ID minted here is the same UUID the workbench projection mints.
WORKBENCH_COMPONENT_NAMESPACE = uuid.uuid5(
    uuid.NAMESPACE_URL,
    "https://schemas.exais.ai/exai-vector-store/topeka-municipal-code/workbench-component/v1",
)
WORKBENCH_COMPONENT_SCHEMA = "exais.workbench_component.v1"

JURISDICTION_KEY = "ks:city:topeka"
JURISDICTION_NAME = "City of Topeka, Kansas"
# The source artifacts were captured under the legacy key. It is mapped, not replaced.
JURISDICTION_ALIASES = ("ks-topeka",)


# --------------------------------------------------------------------------
# canonical bytes and hashing
# --------------------------------------------------------------------------

def canonical_json_bytes(value: Any) -> bytes:
    """Byte form both producer and consumer hash. Sorted keys, no whitespace."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def capture_index(raw_dir: Path) -> dict[str, list[Path]]:
    """Index retained captures by the hash embedded in their filename.

    Capture filenames are ``<sanitised citation>.<sha256[:12]>.html``, and the
    sanitiser mangles citations like ``AxB Art. III § 1`` beyond reconstruction.
    Indexing on the hash instead of rebuilding the filename means the lookup
    works for every naming scheme the crawler has ever used, and the full hash is
    still verified afterwards.
    """
    index: dict[str, list[Path]] = {}
    if not raw_dir.is_dir():
        return index
    for path in raw_dir.iterdir():
        if not path.is_file():
            continue
        parts = path.name.split(".")
        if len(parts) < 3:
            continue
        marker = parts[-2]
        if re.fullmatch(r"[0-9a-f]{12}", marker):
            index.setdefault(marker, []).append(path)
    return index


def resolve_capture(raw_dir: Path, content_sha256: str) -> Path | None:
    """The retained capture whose bytes hash to ``content_sha256``, if present."""
    for candidate in capture_index(raw_dir).get(content_sha256[:12], []):
        if sha256_file(candidate) == content_sha256:
            return candidate
    return None


# Fields that legitimately differ between two exports of identical source content.
# They are excluded from payload_sha256 so "unchanged" is decidable without
# re-extracting, and included in record_sha256 so the delivered file still pins.
VOLATILE_RECORD_PATHS: tuple[tuple[str, ...], ...] = (
    ("readiness",),
    ("meaning", "review", "reviewed_at"),
)


def payload_fingerprint(record: Mapping[str, Any]) -> str:
    """Content identity of a document record, stable across re-exports."""
    pruned = json.loads(json.dumps(record))
    for path in VOLATILE_RECORD_PATHS:
        cursor: Any = pruned
        for key in path[:-1]:
            if not isinstance(cursor, dict):
                cursor = None
                break
            cursor = cursor.get(key)
        if isinstance(cursor, dict):
            cursor.pop(path[-1], None)
    return canonical_sha256(pruned)


def inventory_fingerprint(documents: Iterable[Mapping[str, Any]]) -> str:
    triples = sorted(
        [doc["source_document_id"], doc["document_version_id"], doc["payload_sha256"]]
        for doc in documents
    )
    return canonical_sha256(triples)


# --------------------------------------------------------------------------
# registered master collections
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class CollectionSpec:
    """One registered master collection: one publisher master list or category.

    ``path_prefixes`` are the publisher's own directory prefixes for member
    documents. They exist so a bare URL can be routed; they are never a licence
    to mint a collection per prefix.
    """

    slug: str
    name: str
    master_source_url: str
    listing_category: str | None
    document_type: str
    id_prefix: str
    hosts: tuple[str, ...]
    path_prefixes: tuple[str, ...]
    # Prefixes that belong to a sibling collection and must lose the tie-break
    # even though they sit under this collection's prefix.
    excluded_path_prefixes: tuple[str, ...] = ()
    # (host, path prefix) pairs where the publisher still links documents of this
    # collection from a superseded location. They route here so the document
    # keeps one identity instead of gaining a second one; they are reported as
    # legacy so the stale link is visible rather than silently equivalent.
    legacy_locations: tuple[tuple[str, str], ...] = ()
    vector_store_id: str | None = None

    @property
    def collection_id(self) -> str:
        return f"{JURISDICTION_KEY}:{self.slug}"


TOPEKA_COLLECTIONS: tuple[CollectionSpec, ...] = (
    CollectionSpec(
        slug="municipal-code",
        name="Topeka Municipal Code",
        master_source_url="https://topeka.municipal.codes/TMC",
        listing_category=None,
        document_type="code_section",
        id_prefix="tmc",
        hosts=("topeka.municipal.codes",),
        path_prefixes=("/TMC",),
    ),
    CollectionSpec(
        slug="ordinances",
        name="Topeka Ordinances",
        master_source_url="https://topeka.gov/community/ordinances/index.php",
        listing_category="ordinance",
        document_type="ordinance",
        id_prefix="ordinance",
        hosts=("files.topeka.gov", "topeka.gov"),
        path_prefixes=("/community/ordinances/",),
        excluded_path_prefixes=("/community/ordinances/charter/",),
        # The ordinances listing still carries a stale link to the Standard
        # Traffic Ordinance on the retired WordPress bucket, alongside the live
        # files.topeka.gov one. Same document, two URLs, one identity.
        legacy_locations=(("cot-wp-uploads.s3.amazonaws.com", "/wp-content/uploads/legal/"),),
    ),
    CollectionSpec(
        slug="charter-ordinances",
        name="Topeka Charter Ordinances",
        master_source_url="https://topeka.gov/community/ordinances/index.php",
        listing_category="charter_ordinance",
        document_type="charter_ordinance",
        id_prefix="charter-ordinance",
        hosts=("files.topeka.gov", "topeka.gov"),
        path_prefixes=("/community/ordinances/charter/",),
    ),
    CollectionSpec(
        slug="resolutions",
        name="Topeka Resolutions",
        master_source_url="https://topeka.gov/community/resolutions/index.php",
        listing_category="resolution",
        document_type="resolution",
        id_prefix="resolution",
        hosts=("files.topeka.gov", "topeka.gov"),
        path_prefixes=("/community/resolutions/",),
    ),
)

COLLECTIONS_BY_SLUG: dict[str, CollectionSpec] = {c.slug: c for c in TOPEKA_COLLECTIONS}
COLLECTIONS_BY_ID: dict[str, CollectionSpec] = {c.collection_id: c for c in TOPEKA_COLLECTIONS}
COLLECTIONS_BY_CATEGORY: dict[str, CollectionSpec] = {
    c.listing_category: c for c in TOPEKA_COLLECTIONS if c.listing_category
}

# Publisher host aliases. The same bytes served through a CDN/bucket alias are
# the same document, not a second one.
HOST_ALIASES: dict[str, tuple[str, str]] = {
    # (canonical host, path prefix to strip)
    "s3.us-east-1.amazonaws.com": ("files.topeka.gov", "/files.topeka.gov"),
    "s3.amazonaws.com": ("files.topeka.gov", "/files.topeka.gov"),
}


def canonical_source_url(value: str) -> str:
    """Collapse alias hosts, drop fragments and queries, normalise the path.

    ``#undefined`` is a UI fragment, not source identity, so it cannot produce a
    second document or a second store.
    """
    parts = urlsplit((value or "").strip())
    if parts.scheme not in {"http", "https"}:
        return ""
    host = parts.netloc.lower()
    path = parts.path
    alias = HOST_ALIASES.get(host)
    if alias:
        canonical_host, strip_prefix = alias
        if path.startswith(strip_prefix + "/") or path == strip_prefix:
            host = canonical_host
            path = path[len(strip_prefix):] or "/"
    if host.startswith("www."):
        host = host[4:]
    if len(path) > 1:
        path = path.rstrip("/")
    return urlunsplit(("https", host, path or "/", "", ""))


class RoutingError(ValueError):
    """Raised when a document cannot be assigned to a registered collection."""


def route_document(
    *,
    official_url: str,
    listing_category: str | None = None,
    listing_url: str | None = None,
    collections: Sequence[CollectionSpec] = TOPEKA_COLLECTIONS,
) -> CollectionSpec:
    """Assign one document to exactly one registered master collection.

    Listing category is authoritative when the discovery pass recorded one,
    because membership is defined by the publisher's category. A bare URL falls
    back to the registry's host/path rules. Text inside a document never
    participates: a charter ordinance quoted inside an ordinary ordinance does
    not move that ordinance.
    """
    if listing_category:
        spec = COLLECTIONS_BY_CATEGORY.get(listing_category)
        if spec is None:
            raise RoutingError(f"listing category {listing_category!r} is not a registered collection")
        return spec

    canonical = canonical_source_url(official_url)
    if not canonical:
        raise RoutingError(f"{official_url!r} is not a resolvable http(s) source URL")
    parts = urlsplit(canonical)
    matches: list[tuple[int, CollectionSpec]] = []
    for spec in collections:
        for host, prefix in spec.legacy_locations:
            if parts.netloc == host and parts.path.startswith(prefix):
                return spec
        if parts.netloc not in spec.hosts:
            continue
        if any(parts.path.startswith(excluded) for excluded in spec.excluded_path_prefixes):
            continue
        for prefix in spec.path_prefixes:
            if parts.path == prefix.rstrip("/") or parts.path.startswith(prefix):
                matches.append((len(prefix), spec))
                break
    if not matches:
        raise RoutingError(
            f"{canonical!r} matches no registered master collection"
            f" (listing_url={listing_url!r}); register the master list before releasing it"
        )
    matches.sort(key=lambda item: item[0], reverse=True)
    if len(matches) > 1 and matches[0][0] == matches[1][0]:
        raise RoutingError(f"{canonical!r} is ambiguous between {matches[0][1].slug} and {matches[1][1].slug}")
    return matches[0][1]


# --------------------------------------------------------------------------
# identity
# --------------------------------------------------------------------------

_KEY_SAFE = re.compile(r"[^a-z0-9.]+")


def publisher_key(value: str) -> str:
    """Normalise a publisher document key (ordinance number, citation, stem)."""
    return _KEY_SAFE.sub("-", (value or "").strip().lower()).strip("-")


def source_document_id(spec: CollectionSpec, key: str) -> str:
    """Stable identity: collection plus the publisher's own document key.

    Never derived from checkout commit, normalized text, chunk order or row
    position, so re-exporting or re-chunking cannot re-key a document.
    """
    normalised = publisher_key(key)
    if not normalised:
        raise ValueError("publisher document key is empty; identity would not be stable")
    return f"{spec.collection_id}:{spec.id_prefix}:{normalised}"


def document_version_id(document_id: str, original_sha256: str) -> str:
    """Version identity: the publisher's retained bytes for this document.

    Distinct from ``source_document_id``: new publisher bytes make a new version
    of the same document rather than a new document.
    """
    if not re.fullmatch(r"[0-9a-f]{64}", original_sha256 or ""):
        raise ValueError("document_version_id needs the retained original sha256")
    return f"{document_id}@{original_sha256[:16]}"


def component_id(source_component_key: str) -> str:
    return str(uuid.uuid5(WORKBENCH_COMPONENT_NAMESPACE, source_component_key))


# --------------------------------------------------------------------------
# schema validation
# --------------------------------------------------------------------------

@dataclass
class SchemaError:
    path: str
    keyword: str
    message: str

    def __str__(self) -> str:
        return f"{self.path or '<root>'}: {self.message} [{self.keyword}]"


def _pointer(error: "jsonschema.ValidationError") -> str:
    """Render a jsonschema error path the way the rest of this module reports paths."""
    parts: list[str] = []
    for token in error.absolute_path:
        if isinstance(token, int):
            parts.append(f"[{token}]")
        else:
            parts.append(f".{token}" if parts else str(token))
    return "".join(parts)


class SchemaValidator:
    """Draft 2020-12 validation, delegated to the ``jsonschema`` library.

    This deliberately does NOT hand-roll an evaluator. An earlier version did,
    and it silently accepted `true` against `const: 1` and `enum: [1]` (Python
    makes `True == 1`), ignored `multipleOf` entirely, and treated `[1, 1.0]` as
    unique. The keyword-coverage guard that was supposed to make hand-rolling
    safe had itself listed `multipleOf` as supported while never implementing
    it -- which is exactly the failure mode a guard like that cannot catch.

    ``jsonschema`` is already a declared dependency of every app in this repo
    (``apps/*/requirements.txt``), so using it costs nothing new.
    """

    def __init__(self, schema: Mapping[str, Any]) -> None:
        self.schema = schema
        # Reject a malformed schema at construction, rather than silently
        # under-constraining every document validated against it.
        jsonschema.Draft202012Validator.check_schema(schema)
        self._validator = jsonschema.Draft202012Validator(schema)

    def validate(self, instance: Any) -> list[SchemaError]:
        return [
            SchemaError(_pointer(error), error.validator or "schema", error.message)
            for error in sorted(self._validator.iter_errors(instance), key=lambda e: list(e.absolute_path))
        ]


@dataclass
class LoadedSchema:
    path: Path
    document: dict[str, Any]
    validator: SchemaValidator
    sha256: str
    schema_id: str
    version: str = CONTRACT_VERSION

    def validate(self, instance: Any) -> list[SchemaError]:
        return self.validator.validate(instance)


def load_schema(path: Path, schema_id: str) -> LoadedSchema:
    raw = path.read_bytes()
    document = json.loads(raw.decode("utf-8"))
    return LoadedSchema(
        path=path,
        document=document,
        validator=SchemaValidator(document),
        sha256=sha256_bytes(raw),
        schema_id=schema_id,
    )


def load_release_schemas() -> tuple[LoadedSchema, LoadedSchema]:
    """(release manifest schema, source document schema)."""
    return (
        load_schema(RELEASE_MANIFEST_SCHEMA_PATH, RELEASE_MANIFEST_SCHEMA_ID),
        load_schema(SOURCE_DOCUMENT_SCHEMA_PATH, SOURCE_DOCUMENT_SCHEMA_ID),
    )


# --------------------------------------------------------------------------
# small shared shapes
# --------------------------------------------------------------------------

def stage(state: str, *, detail: str = "", observed_at: str | None = None, proof_ref: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"state": state}
    if detail:
        payload["detail"] = detail
    if observed_at is not None:
        payload["observed_at"] = observed_at
    if proof_ref is not None:
        payload["proof_ref"] = proof_ref
    return payload


@dataclass
class ValidationIssue:
    severity: str
    code: str
    location: str
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {"severity": self.severity, "code": self.code, "location": self.location, "message": self.message}

    def __str__(self) -> str:
        return f"{self.severity.upper()} {self.code} {self.location}: {self.message}"


@dataclass
class ValidationReport:
    bundle: str
    issues: list[ValidationIssue] = field(default_factory=list)
    checks: dict[str, Any] = field(default_factory=dict)

    def add(self, severity: str, code: str, location: str, message: str) -> None:
        self.issues.append(ValidationIssue(severity, code, location, message))

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def passed(self) -> bool:
        return not self.errors

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifact": "jurisdiction_document_release_validation",
            "bundle": self.bundle,
            "passed": self.passed,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "checks": self.checks,
            "issues": [issue.as_dict() for issue in self.issues],
        }
