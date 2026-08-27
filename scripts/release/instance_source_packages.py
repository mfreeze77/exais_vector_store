from __future__ import annotations

import csv
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable

import yaml


ROOT = Path(__file__).resolve().parents[2]
SOURCE_PACKAGE_SCHEMA = ROOT / "contracts" / "vector-store-source-package.schema.json"
LOCAL_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")
PORTABLE_URI_RE = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
FORBIDDEN_INGESTION_MODES = {"db", "database", "qdrant", "minio", "object-store-direct"}
SECRET_FRAGMENT_RE = re.compile(r"(?i)(bearer|token|api[_-]?key|password|secret)=([^&\s]+)")


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    code: str
    path: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "code": self.code,
            "path": self.path,
            "message": self.message,
        }


@dataclass(frozen=True)
class SourcePackage:
    root: Path
    source_path: Path
    store_path: Path
    vector_store_slug: str
    source_slug: str
    source: dict[str, Any]
    store: dict[str, Any]


@dataclass(frozen=True)
class ManifestRecord:
    identity: str
    checksum: str
    row: dict[str, str]


def load_yaml(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"YAML document must be an object: {path}")
    return loaded


def load_json(path: Path) -> dict[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"JSON document must be an object: {path}")
    return loaded


def instance_dir(instance: str, *, root: Path = ROOT) -> Path:
    return root / "instances" / instance


def vector_store_dirs(instance: str, *, root: Path = ROOT) -> list[Path]:
    base = instance_dir(instance, root=root) / "vector-stores"
    if not base.exists():
        return []
    return sorted(path for path in base.iterdir() if path.is_dir())


def discover_source_packages(
    instance: str,
    *,
    root: Path = ROOT,
    vector_store: str | None = None,
    source: str | None = None,
) -> tuple[list[SourcePackage], list[ValidationIssue]]:
    packages: list[SourcePackage] = []
    issues: list[ValidationIssue] = []
    selected_dirs = [
        path for path in vector_store_dirs(instance, root=root)
        if vector_store is None or path.name == vector_store
    ]
    if vector_store is not None and not selected_dirs:
        issues.append(issue("error", "VECTOR_STORE_DIR_MISSING", f"instances/{instance}/vector-stores/{vector_store}", "vector store package directory is missing"))
    for store_dir in selected_dirs:
        source_base = store_dir / "sources"
        source_paths = sorted(source_base.glob("*/source.yaml")) if source_base.exists() else []
        if source is not None:
            source_paths = [path for path in source_paths if path.parent.name == source]
        if not source_paths:
            issue_path = relative_to_root(source_base if source is None else source_base / source / "source.yaml", root)
            issues.append(issue("error", "SOURCE_PACKAGE_MISSING", issue_path, "vector store package has no source.yaml"))
            continue
        for source_path in source_paths:
            store_path = store_dir / "store.yaml"
            try:
                source_doc = load_yaml(source_path)
                store_doc = load_yaml(store_path) if store_path.exists() else {}
            except Exception as exc:
                issues.append(issue("error", "PACKAGE_PARSE_ERROR", relative_to_root(source_path, root), str(exc)))
                continue
            packages.append(SourcePackage(
                root=root,
                source_path=source_path,
                store_path=store_path,
                vector_store_slug=store_dir.name,
                source_slug=source_path.parent.name,
                source=source_doc,
                store=store_doc,
            ))
    return packages, issues


def validate_instance_source_packages(
    instance: str,
    *,
    root: Path = ROOT,
    production: bool = False,
    vector_store: str | None = None,
    source: str | None = None,
) -> tuple[list[SourcePackage], list[ValidationIssue]]:
    packages, issues = discover_source_packages(instance, root=root, vector_store=vector_store, source=source)
    for package in packages:
        issues.extend(validate_source_package(package, instance=instance, production=production))
    return packages, issues


def validate_source_package(package: SourcePackage, *, instance: str, production: bool) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    doc = package.source
    source_rel = relative_to_root(package.source_path, package.root)
    if not SOURCE_PACKAGE_SCHEMA.exists():
        issues.append(issue("error", "SCHEMA_MISSING", relative_to_root(SOURCE_PACKAGE_SCHEMA, package.root), "source-package schema is missing"))
    if not package.store_path.exists():
        issues.append(issue("error", "STORE_PACKAGE_MISSING", relative_to_root(package.store_path, package.root), "store.yaml is required for each vector store package"))
    issues.extend(_required(doc, source_rel, [
        "apiVersion",
        "kind",
        "metadata.instanceSlug",
        "metadata.vectorStoreSlug",
        "metadata.sourceSlug",
        "vectorStore.id",
        "vectorStore.name",
        "vectorStore.tenantId",
        "vectorStore.businessInstanceId",
        "vectorStore.knowledgeBaseId",
        "source.type",
        "source.connector.kind",
        "source.connector.entrypoint",
        "source.storage.rawCorpusUri",
        "source.storage.manifestUri",
        "source.manifest.format",
        "source.manifest.stableIdentityFields",
        "source.manifest.checksumField",
        "source.manifest.savedPathField",
        "source.manifest.lockFile",
        "ingestion.mode",
        "ingestion.runner",
        "ingestion.command",
        "ingestion.idempotency",
        "updatePolicy.diffMode",
        "updatePolicy.removedRecords",
        "updatePolicy.dryRunRequired",
        "graph.enabled",
        "eval.command",
        "eval.expectedProofArtifacts",
    ]))
    if doc.get("apiVersion") != "svs/v1":
        issues.append(issue("error", "BAD_API_VERSION", f"{source_rel}:apiVersion", "apiVersion must be svs/v1"))
    if doc.get("kind") != "VectorStoreSourcePackage":
        issues.append(issue("error", "BAD_KIND", f"{source_rel}:kind", "kind must be VectorStoreSourcePackage"))
    if get_path(doc, "metadata.instanceSlug") != instance:
        issues.append(issue("error", "INSTANCE_SLUG_MISMATCH", f"{source_rel}:metadata.instanceSlug", "metadata.instanceSlug must match the selected instance"))
    if get_path(doc, "metadata.vectorStoreSlug") != package.vector_store_slug:
        issues.append(issue("error", "VECTOR_STORE_SLUG_MISMATCH", f"{source_rel}:metadata.vectorStoreSlug", "metadata.vectorStoreSlug must match the vector-store directory name"))
    if get_path(doc, "metadata.sourceSlug") != package.source_slug:
        issues.append(issue("error", "SOURCE_SLUG_MISMATCH", f"{source_rel}:metadata.sourceSlug", "metadata.sourceSlug must match the source directory name"))

    mode = str(get_path(doc, "ingestion.mode") or "").strip().lower()
    if mode != "api" or mode in FORBIDDEN_INGESTION_MODES:
        issues.append(issue("error", "INGESTION_NOT_API_ONLY", f"{source_rel}:ingestion.mode", "production source packages must use API ingestion"))
    command = get_path(doc, "ingestion.command")
    if not isinstance(command, list) or not command:
        issues.append(issue("error", "INGESTION_COMMAND_INVALID", f"{source_rel}:ingestion.command", "ingestion.command must be a non-empty argv list"))
    elif _command_mentions_direct_storage(command):
        issues.append(issue("error", "DIRECT_STORAGE_COMMAND", f"{source_rel}:ingestion.command", "ingestion command must not call direct DB/Qdrant/MinIO write tools"))

    stable_fields = get_path(doc, "source.manifest.stableIdentityFields")
    if not isinstance(stable_fields, list) or not all(isinstance(field, str) and field for field in stable_fields):
        issues.append(issue("error", "BAD_STABLE_IDENTITY_FIELDS", f"{source_rel}:source.manifest.stableIdentityFields", "stable identity fields must be a non-empty string list"))

    issues.extend(_validate_path_policy(doc, source_rel, production=production))
    issues.extend(_validate_lock_file(package, source_rel))
    issues.extend(_validate_graph_policy(doc, source_rel))
    return issues


def _validate_path_policy(doc: dict[str, Any], source_rel: str, *, production: bool) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    storage = get_path(doc, "source.storage") or {}
    if not isinstance(storage, dict):
        return issues
    local_paths = {
        key: str(value)
        for key, value in storage.items()
        if _storage_key_can_hold_local_path(key) and isinstance(value, str) and is_local_absolute_path(value)
    }
    if not local_paths:
        return issues
    proof_only = storage.get("localProofOnly") is True or str(storage.get("localScope") or "").lower() in {"local_proof", "development", "dev"}
    portable_values = [
        str(storage.get(key) or "")
        for key in ("rawCorpusUri", "manifestUri", "backupUri")
    ]
    has_portable_pointer = any(is_portable_uri(value) and not is_local_absolute_path(value) for value in portable_values)
    for key, value in local_paths.items():
        if not proof_only:
            issues.append(issue("error", "LOCAL_PATH_NOT_MARKED_PROOF", f"{source_rel}:source.storage.{key}", f"local path must be marked localProofOnly/local proof: {value}"))
        if production and not has_portable_pointer:
            issues.append(issue("error", "LOCAL_PATH_ONLY_SOURCE", f"{source_rel}:source.storage.{key}", "production package cannot rely on a local path as the only source pointer"))
    return issues


def _validate_lock_file(package: SourcePackage, source_rel: str) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    lock_name = get_path(package.source, "source.manifest.lockFile")
    if not isinstance(lock_name, str) or not lock_name:
        return issues
    lock_path = package.source_path.parent / lock_name
    if not lock_path.exists():
        issues.append(issue("error", "LOCK_FILE_MISSING", relative_to_root(lock_path, package.root), "source manifest lock file is missing"))
        return issues
    try:
        lock_doc = load_json(lock_path)
    except Exception as exc:
        issues.append(issue("error", "LOCK_FILE_PARSE_ERROR", relative_to_root(lock_path, package.root), str(exc)))
        return issues
    manifest = get_path(package.source, "source.manifest") or {}
    for field, lock_key in (("sha256", "sha256"), ("rowCount", "rowCount"), ("byteCount", "byteCount")):
        expected = manifest.get(field) if isinstance(manifest, dict) else None
        actual = get_path(lock_doc, f"sourceManifest.{lock_key}")
        if expected is not None and actual is not None and expected != actual:
            issues.append(issue("error", "LOCK_MANIFEST_MISMATCH", f"{source_rel}:source.manifest.{field}", f"source.yaml and {lock_path.name} disagree on {field}"))
    return issues


def _validate_graph_policy(doc: dict[str, Any], source_rel: str) -> list[ValidationIssue]:
    graph = get_path(doc, "graph") or {}
    if not isinstance(graph, dict) or graph.get("enabled") is not True:
        return []
    issues: list[ValidationIssue] = []
    for field in ("extractCommand", "loadCommand", "evalCommand", "expectedProofArtifacts"):
        value = graph.get(field)
        if not isinstance(value, list) or not value:
            issues.append(issue("error", "GRAPH_POLICY_INCOMPLETE", f"{source_rel}:graph.{field}", "GraphRAG-enabled packages must declare graph commands and proof artifacts"))
    return issues


def _required(doc: dict[str, Any], source_rel: str, paths: Iterable[str]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for path in paths:
        value = get_path(doc, path)
        if value is None or value == "" or value == []:
            issues.append(issue("error", "REQUIRED_FIELD_MISSING", f"{source_rel}:{path}", "required source-package field is missing"))
    return issues


def _command_mentions_direct_storage(command: list[Any]) -> bool:
    haystack = " ".join(str(part).lower() for part in command)
    blocked = (" psql ", " qdrant ", " minio ", " mc ", "docker exec postgres")
    return any(token in f" {haystack} " for token in blocked)


def _storage_key_can_hold_local_path(key: str) -> bool:
    normalized = key.lower()
    return normalized.endswith("path") or normalized.endswith("root") or normalized.endswith("file")


def get_path(doc: dict[str, Any], dotted: str) -> Any:
    current: Any = doc
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def is_local_absolute_path(value: str) -> bool:
    return bool(LOCAL_PATH_RE.match(value))


def is_portable_uri(value: str) -> bool:
    return bool(PORTABLE_URI_RE.match(value)) and not is_local_absolute_path(value)


def issue(severity: str, code: str, path: str, message: str) -> ValidationIssue:
    return ValidationIssue(severity=severity, code=code, path=path, message=message)


def relative_to_root(path: Path, root: Path = ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def load_manifest_records(
    manifest_path: Path,
    *,
    manifest_format: str,
    identity_fields: list[str],
    checksum_field: str,
) -> dict[str, ManifestRecord]:
    if manifest_format == "csv":
        with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = [dict(row) for row in csv.DictReader(handle)]
    elif manifest_format == "jsonl":
        rows = [json.loads(line) for line in manifest_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        raise ValueError(f"unsupported manifest format: {manifest_format}")
    records: dict[str, ManifestRecord] = {}
    for raw in rows:
        row = {str(key): "" if value is None else str(value) for key, value in raw.items()}
        identity = manifest_identity(row, identity_fields)
        records[identity] = ManifestRecord(
            identity=identity,
            checksum=manifest_checksum(row, checksum_field),
            row=row,
        )
    return records


def manifest_identity(row: dict[str, str], identity_fields: list[str]) -> str:
    values = [row.get(field, "").strip() for field in identity_fields]
    if not any(values):
        values = [json.dumps(row, sort_keys=True, separators=(",", ":"))]
    return hashlib.sha256("|".join(values).encode("utf-8")).hexdigest()[:24]


def manifest_checksum(row: dict[str, str], checksum_field: str) -> str:
    value = row.get(checksum_field, "").strip()
    if value:
        return value
    return hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def diff_manifest_records(
    previous: dict[str, ManifestRecord],
    current: dict[str, ManifestRecord],
) -> dict[str, Any]:
    previous_ids = set(previous)
    current_ids = set(current)
    added = sorted(current_ids - previous_ids)
    removed = sorted(previous_ids - current_ids)
    shared = sorted(previous_ids & current_ids)
    changed = [identity for identity in shared if previous[identity].checksum != current[identity].checksum]
    unchanged = [identity for identity in shared if previous[identity].checksum == current[identity].checksum]
    return {
        "added": len(added),
        "changed": len(changed),
        "unchanged": len(unchanged),
        "removed": len(removed),
        "examples": {
            "added": added[:5],
            "changed": changed[:5],
            "removed": removed[:5],
        },
    }


def manifest_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_update_plan(
    package: SourcePackage,
    *,
    previous_manifest: Path | None = None,
    current_manifest: Path | None = None,
) -> dict[str, Any]:
    source = package.source
    manifest = get_path(source, "source.manifest") or {}
    storage = get_path(source, "source.storage") or {}
    lock_path = package.source_path.parent / str(manifest.get("lockFile") or "source.lock.json")
    lock_doc = load_json(lock_path) if lock_path.exists() else {}
    current_manifest = current_manifest or _local_proof_manifest(storage)
    diff: dict[str, Any]
    manifest_status = "not_loaded"
    if previous_manifest and current_manifest:
        previous_records = load_manifest_records(
            previous_manifest,
            manifest_format=str(manifest["format"]),
            identity_fields=list(manifest["stableIdentityFields"]),
            checksum_field=str(manifest["checksumField"]),
        )
        current_records = load_manifest_records(
            current_manifest,
            manifest_format=str(manifest["format"]),
            identity_fields=list(manifest["stableIdentityFields"]),
            checksum_field=str(manifest["checksumField"]),
        )
        diff = diff_manifest_records(previous_records, current_records)
        manifest_status = "diffed"
    elif current_manifest and current_manifest.exists():
        current_sha = manifest_file_sha256(current_manifest)
        locked_sha = get_path(lock_doc, "sourceManifest.sha256")
        row_count = int(get_path(lock_doc, "sourceManifest.rowCount") or 0)
        diff = {
            "added": 0,
            "changed": 0 if current_sha == locked_sha else row_count,
            "unchanged": row_count if current_sha == locked_sha else 0,
            "removed": 0,
            "examples": {"added": [], "changed": [], "removed": []},
        }
        manifest_status = "matches_lock" if current_sha == locked_sha else "diff_requires_previous_manifest"
    else:
        diff = {"added": 0, "changed": 0, "unchanged": 0, "removed": 0, "examples": {"added": [], "changed": [], "removed": []}}
    return {
        "instance": get_path(source, "metadata.instanceSlug"),
        "vector_store_slug": package.vector_store_slug,
        "source_slug": package.source_slug,
        "vector_store_id": get_path(source, "vectorStore.id"),
        "ingestion_mode": get_path(source, "ingestion.mode"),
        "api_only_update_path": get_path(source, "ingestion.mode") == "api",
        "direct_storage_writes": False,
        "manifest_status": manifest_status,
        "diff": diff,
        "removed_record_policy": get_path(source, "updatePolicy.removedRecords"),
        "graph_enabled": bool(get_path(source, "graph.enabled")),
        "dry_run_required": bool(get_path(source, "updatePolicy.dryRunRequired")),
        "command": redact_command(list(get_path(source, "ingestion.command") or [])),
    }


def _local_proof_manifest(storage: dict[str, Any]) -> Path | None:
    value = storage.get("localProofPath") if isinstance(storage, dict) else None
    if isinstance(value, str) and value and Path(value).exists():
        return Path(value)
    return None


def redact_command(command: list[str]) -> list[str]:
    redacted: list[str] = []
    skip_next = False
    for part in command:
        if skip_next:
            redacted.append("<redacted>")
            skip_next = False
            continue
        lowered = part.lower()
        if lowered in {"--api-token", "--admin-key", "--ingest-key", "--search-key", "--password"}:
            redacted.append(part)
            skip_next = True
            continue
        redacted.append(SECRET_FRAGMENT_RE.sub(r"\1=<redacted>", part))
    return redacted


def expand_command(command: list[str]) -> list[str]:
    return [os.path.expandvars(part) for part in command]


def execute_update_command(package: SourcePackage) -> subprocess.CompletedProcess[str]:
    command = expand_command(list(get_path(package.source, "ingestion.command") or []))
    if not command:
        raise ValueError("source package has no ingestion command")
    return subprocess.run(command, cwd=package.root, check=True, text=True)
