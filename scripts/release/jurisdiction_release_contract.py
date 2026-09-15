#!/usr/bin/env python3
"""Shared contract code for jurisdiction document releases.

Stdlib only. Nothing here imports an embedding provider, a vector store client,
a database driver or a consumer application, so the exporter and the validator
both run on a bare checkout.

Three things live here:

* a small draft 2020-12 evaluator, so the published JSON Schemas are executable
  rather than decorative (the repository does not vendor ``jsonschema``);
* the registered master-collection registry and the routing function derived
  from it, so no caller hand-lists which URLs belong to which store;
* the identity, hashing and canonical-JSON helpers the exporter and validator
  must agree on byte-for-byte.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"
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
# minimal draft 2020-12 evaluator
# --------------------------------------------------------------------------

@dataclass
class SchemaError:
    path: str
    keyword: str
    message: str

    def __str__(self) -> str:
        return f"{self.path or '<root>'}: {self.message} [{self.keyword}]"


_TYPES: dict[str, type | tuple[type, ...]] = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "number": (int, float),
    "integer": int,
    "null": type(None),
}


def _is_type(value: Any, name: str) -> bool:
    expected = _TYPES.get(name)
    if expected is None:
        return True
    if name in {"integer", "number"} and isinstance(value, bool):
        return False
    if name == "integer" and isinstance(value, float):
        return value.is_integer()
    return isinstance(value, expected)


class SchemaValidator:
    """Evaluates the subset of draft 2020-12 used by the contract schemas.

    Supported: ``type``, ``const``, ``enum``, ``required``, ``properties``,
    ``additionalProperties``, ``items``, ``minItems``, ``maxItems``,
    ``uniqueItems``, ``minLength``, ``maxLength``, ``minimum``, ``maximum``,
    ``pattern``, ``anyOf``, ``allOf``, ``oneOf``, ``not`` and local ``$ref``.
    Unsupported keywords raise at construction time rather than passing silently,
    so a schema can never claim a constraint the validator does not enforce.
    """

    KNOWN = {
        "$schema", "$id", "$defs", "$ref", "title", "description", "examples", "default",
        "type", "const", "enum", "required", "properties", "additionalProperties",
        "items", "prefixItems", "minItems", "maxItems", "uniqueItems",
        "minLength", "maxLength", "pattern", "format",
        "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
        "anyOf", "allOf", "oneOf", "not",
    }

    def __init__(self, schema: Mapping[str, Any]) -> None:
        self.schema = schema
        self._assert_supported(schema, "#")

    def _assert_supported(self, node: Mapping[str, Any], path: str) -> None:
        """Fail loudly on a keyword this evaluator would otherwise ignore.

        A schema that silently drops an unenforced constraint is worse than no
        schema, so an unknown keyword is a construction-time error.
        """
        unknown = sorted(set(node) - self.KNOWN)
        if unknown:
            raise ValueError(f"unsupported schema keyword(s) {unknown} at {path}")
        for key in ("properties", "$defs"):
            for name, sub in (node.get(key) or {}).items():
                self._assert_supported(sub, f"{path}/{key}/{name}")
        for key in ("items", "not", "additionalProperties"):
            sub = node.get(key)
            if isinstance(sub, dict):
                self._assert_supported(sub, f"{path}/{key}")
        for key in ("anyOf", "allOf", "oneOf", "prefixItems"):
            for index, sub in enumerate(node.get(key) or []):
                self._assert_supported(sub, f"{path}/{key}/{index}")

    def validate(self, instance: Any) -> list[SchemaError]:
        errors: list[SchemaError] = []
        self._validate(instance, self.schema, "", errors)
        return errors

    def _resolve(self, ref: str) -> Mapping[str, Any]:
        if not ref.startswith("#/"):
            raise ValueError(f"only local $ref is supported, got {ref!r}")
        node: Any = self.schema
        for part in ref[2:].split("/"):
            part = part.replace("~1", "/").replace("~0", "~")
            node = node[part]
        return node

    def _validate(self, instance: Any, schema: Mapping[str, Any], path: str, errors: list[SchemaError]) -> None:
        if "$ref" in schema:
            self._validate(instance, self._resolve(schema["$ref"]), path, errors)
            # siblings of $ref are still applied (2020-12 behaviour)
            schema = {k: v for k, v in schema.items() if k != "$ref"}
            if not schema:
                return

        if "const" in schema and instance != schema["const"]:
            errors.append(SchemaError(path, "const", f"expected {schema['const']!r}, got {instance!r}"))

        if "enum" in schema and instance not in schema["enum"]:
            errors.append(SchemaError(path, "enum", f"{instance!r} is not one of {schema['enum']!r}"))

        if "type" in schema:
            names = schema["type"]
            names = [names] if isinstance(names, str) else list(names)
            if not any(_is_type(instance, name) for name in names):
                errors.append(
                    SchemaError(path, "type", f"expected type {'|'.join(names)}, got {type(instance).__name__}")
                )
                return

        for keyword in ("allOf",):
            for index, sub in enumerate(schema.get(keyword, [])):
                self._validate(instance, sub, path, errors)

        if "anyOf" in schema:
            if not any(not self._collect(instance, sub, path) for sub in schema["anyOf"]):
                errors.append(SchemaError(path, "anyOf", "value matches none of the allowed shapes"))

        if "oneOf" in schema:
            matched = sum(1 for sub in schema["oneOf"] if not self._collect(instance, sub, path))
            if matched != 1:
                errors.append(SchemaError(path, "oneOf", f"expected exactly one match, got {matched}"))

        if "not" in schema and not self._collect(instance, schema["not"], path):
            errors.append(SchemaError(path, "not", "value matches a forbidden shape"))

        if isinstance(instance, str):
            self._validate_string(instance, schema, path, errors)
        elif isinstance(instance, (int, float)) and not isinstance(instance, bool):
            self._validate_number(instance, schema, path, errors)
        elif isinstance(instance, list):
            self._validate_array(instance, schema, path, errors)
        elif isinstance(instance, dict):
            self._validate_object(instance, schema, path, errors)

    def _collect(self, instance: Any, schema: Mapping[str, Any], path: str) -> list[SchemaError]:
        errors: list[SchemaError] = []
        self._validate(instance, schema, path, errors)
        return errors

    def _validate_string(self, instance: str, schema: Mapping[str, Any], path: str, errors: list[SchemaError]) -> None:
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(SchemaError(path, "minLength", f"shorter than {schema['minLength']}"))
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errors.append(SchemaError(path, "maxLength", f"longer than {schema['maxLength']}"))
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            errors.append(SchemaError(path, "pattern", f"{instance!r} does not match {schema['pattern']!r}"))

    def _validate_number(self, instance: Any, schema: Mapping[str, Any], path: str, errors: list[SchemaError]) -> None:
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(SchemaError(path, "minimum", f"{instance} < {schema['minimum']}"))
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(SchemaError(path, "maximum", f"{instance} > {schema['maximum']}"))
        if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
            errors.append(SchemaError(path, "exclusiveMinimum", f"{instance} <= {schema['exclusiveMinimum']}"))
        if "exclusiveMaximum" in schema and instance >= schema["exclusiveMaximum"]:
            errors.append(SchemaError(path, "exclusiveMaximum", f"{instance} >= {schema['exclusiveMaximum']}"))

    def _validate_array(self, instance: list, schema: Mapping[str, Any], path: str, errors: list[SchemaError]) -> None:
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(SchemaError(path, "minItems", f"{len(instance)} items, minimum {schema['minItems']}"))
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(SchemaError(path, "maxItems", f"{len(instance)} items, maximum {schema['maxItems']}"))
        if schema.get("uniqueItems"):
            seen = [canonical_json_bytes(item) for item in instance]
            if len(set(seen)) != len(seen):
                errors.append(SchemaError(path, "uniqueItems", "array contains duplicates"))
        prefix = schema.get("prefixItems") or []
        for index, sub in enumerate(prefix):
            if index < len(instance):
                self._validate(instance[index], sub, f"{path}[{index}]", errors)
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index in range(len(prefix), len(instance)):
                self._validate(instance[index], item_schema, f"{path}[{index}]", errors)

    def _validate_object(self, instance: dict, schema: Mapping[str, Any], path: str, errors: list[SchemaError]) -> None:
        for name in schema.get("required", []):
            if name not in instance:
                errors.append(SchemaError(path, "required", f"missing required property {name!r}"))
        properties = schema.get("properties") or {}
        for name, value in instance.items():
            child = f"{path}.{name}" if path else name
            if name in properties:
                self._validate(value, properties[name], child, errors)
                continue
            extra = schema.get("additionalProperties", True)
            if extra is False:
                errors.append(SchemaError(child, "additionalProperties", f"property {name!r} is not allowed"))
            elif isinstance(extra, dict):
                self._validate(value, extra, child, errors)


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
