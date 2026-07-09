from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


MANIFEST_SCHEMA_VERSION = 1
BACKUP_MANIFEST_FILENAME = "manifest.json"
BACKUP_ARTIFACT_AUTHORITY = "scripts/release/backup_common.py:REQUIRED_ARTIFACT_KINDS"
ROOT = Path(__file__).resolve().parents[2]
VERSION_FILE = ROOT / "VERSION"
SHA256_RE = re.compile(r"^[a-fA-F0-9]{64}$")

REQUIRED_ARTIFACT_KINDS = (
    "postgres_metadata",
    "qdrant_vectors",
    "opensearch_sparse",
    "object_store",
    "config_metadata",
    "audit_export",
    "checksum_metadata",
)

KNOWN_ARTIFACT_KINDS = frozenset(REQUIRED_ARTIFACT_KINDS)


@dataclass(frozen=True)
class BackupArtifact:
    kind: str
    relative_path: str
    required: bool
    source: str
    notes: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    sha256: str | None = None
    size_bytes: int | None = None

    def to_manifest(self, bundle_dir: Path) -> dict[str, Any]:
        artifact_path = resolve_artifact_path(bundle_dir, self.relative_path)
        size_bytes = self.size_bytes if self.size_bytes is not None else artifact_path.stat().st_size
        sha256 = self.sha256 or sha256_file(artifact_path)
        data: dict[str, Any] = {
            "kind": self.kind,
            "relative_path": normalize_relative_path(self.relative_path),
            "sha256": sha256,
            "size_bytes": size_bytes,
            "required": self.required,
            "source": self.source,
        }
        if self.notes:
            data["notes"] = self.notes
        if self.metadata:
            data["metadata"] = json_safe(self.metadata)
        return data

    @classmethod
    def from_manifest(cls, value: Mapping[str, Any]) -> "BackupArtifact":
        return cls(
            kind=str(value.get("kind", "")),
            relative_path=str(value.get("relative_path", "")),
            required=value.get("required") if isinstance(value.get("required"), bool) else False,
            source=str(value.get("source", "")),
            notes=str(value.get("notes", "")) if value.get("notes") is not None else "",
            metadata=value.get("metadata") if isinstance(value.get("metadata"), Mapping) else {},
            sha256=str(value.get("sha256", "")) if value.get("sha256") is not None else None,
            size_bytes=value.get("size_bytes") if isinstance(value.get("size_bytes"), int) and not isinstance(value.get("size_bytes"), bool) else None,
        )


@dataclass(frozen=True)
class BackupManifestIssue:
    code: str
    message: str
    kind: str | None = None
    relative_path: str | None = None


@dataclass(frozen=True)
class BackupManifestReport:
    manifest_path: Path
    artifacts: tuple[BackupArtifact, ...] = ()
    issues: tuple[BackupManifestIssue, ...] = ()
    schema_version: int | None = None
    product_version: str | None = None
    bundle_id: str | None = None
    generated_at: str | None = None

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def artifact_kinds(self) -> tuple[str, ...]:
        return tuple(artifact.kind for artifact in self.artifacts)


@dataclass(frozen=True)
class StandardArtifactSpec:
    kind: str
    candidates: tuple[str, ...]
    source: str
    marker_source: str
    notes: str


STANDARD_ARTIFACT_SPECS = (
    StandardArtifactSpec(
        "postgres_metadata",
        ("postgres/svs.dump", "postgres/metadata-unavailable.json"),
        "pg_dump",
        "metadata_marker",
        "Postgres metadata dump or explicit local preflight marker.",
    ),
    StandardArtifactSpec(
        "qdrant_vectors",
        ("qdrant/snapshot-create-response.json", "qdrant/vectors-unavailable.json"),
        "qdrant_snapshot_api",
        "metadata_marker",
        "Qdrant vector snapshot response or explicit local preflight marker.",
    ),
    StandardArtifactSpec(
        "opensearch_sparse",
        ("opensearch/indices.json", "opensearch/sparse-unavailable.json"),
        "opensearch_index_listing",
        "metadata_marker",
        "OpenSearch sparse index listing or explicit local preflight marker.",
    ),
    StandardArtifactSpec(
        "object_store",
        ("object-store/local-files.txt", "object-store/object-store-unavailable.json"),
        "local_object_store_listing",
        "metadata_marker",
        "Object-store artifact listing or explicit local preflight marker.",
    ),
    StandardArtifactSpec(
        "config_metadata",
        ("config/config-metadata.json", "config/instance.yaml", "instance.yaml"),
        "instance_manifest",
        "metadata_marker",
        "Instance config metadata captured without expanding secret reference values.",
    ),
    StandardArtifactSpec(
        "audit_export",
        ("audit/audit-export.json", "audit/audit-unavailable.json"),
        "audit_export",
        "metadata_marker",
        "Audit export artifact or explicit local preflight marker.",
    ),
    StandardArtifactSpec(
        "checksum_metadata",
        ("CHECKSUMS.sha256",),
        "sha256sum",
        "sha256sum",
        "Checksum metadata for bundle files.",
    ),
)


def write_backup_manifest(bundle_dir: Path, artifacts: Sequence[BackupArtifact]) -> Path:
    ordered_artifacts = sorted(
        artifacts,
        key=lambda artifact: (
            REQUIRED_ARTIFACT_KINDS.index(artifact.kind) if artifact.kind in REQUIRED_ARTIFACT_KINDS else len(REQUIRED_ARTIFACT_KINDS),
            artifact.relative_path,
        ),
    )
    payload = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "artifact_authority": BACKUP_ARTIFACT_AUTHORITY,
        "product_version": product_version(),
        "bundle_id": bundle_dir.name,
        "required_artifact_kinds": list(REQUIRED_ARTIFACT_KINDS),
        "artifacts": [artifact.to_manifest(bundle_dir) for artifact in ordered_artifacts],
    }
    destination = bundle_dir / BACKUP_MANIFEST_FILENAME
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination


def validate_backup_manifest(manifest_path: Path, *, require_external: bool = False) -> BackupManifestReport:
    issues: list[BackupManifestIssue] = []
    artifacts: list[BackupArtifact] = []
    schema_version: int | None = None
    product_version_value: str | None = None
    bundle_id: str | None = None
    generated_at: str | None = None

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return BackupManifestReport(
            manifest_path,
            issues=(BackupManifestIssue("MISSING_MANIFEST", f"backup manifest not found: {manifest_path}"),),
        )
    except json.JSONDecodeError as exc:
        return BackupManifestReport(
            manifest_path,
            issues=(BackupManifestIssue("BAD_JSON", f"backup manifest is not valid JSON: {exc}"),),
        )

    if not isinstance(data, dict):
        return BackupManifestReport(
            manifest_path,
            issues=(BackupManifestIssue("BAD_MANIFEST", "backup manifest must be a JSON object"),),
        )

    raw_schema_version = data.get("schema_version")
    if isinstance(raw_schema_version, int) and not isinstance(raw_schema_version, bool):
        schema_version = raw_schema_version
    else:
        issues.append(BackupManifestIssue("BAD_SCHEMA_VERSION", "schema_version must be an integer"))
    if schema_version != MANIFEST_SCHEMA_VERSION:
        issues.append(BackupManifestIssue("UNSUPPORTED_SCHEMA_VERSION", f"expected schema_version {MANIFEST_SCHEMA_VERSION}, got {raw_schema_version!r}"))

    if data.get("artifact_authority") != BACKUP_ARTIFACT_AUTHORITY:
        issues.append(BackupManifestIssue("BAD_ARTIFACT_AUTHORITY", f"artifact_authority must be {BACKUP_ARTIFACT_AUTHORITY}"))

    raw_product_version = data.get("product_version")
    if isinstance(raw_product_version, str) and raw_product_version:
        product_version_value = raw_product_version
    else:
        issues.append(BackupManifestIssue("MISSING_PRODUCT_VERSION", "manifest must include product_version"))

    raw_bundle_id = data.get("bundle_id")
    if isinstance(raw_bundle_id, str) and raw_bundle_id:
        bundle_id = raw_bundle_id
    else:
        issues.append(BackupManifestIssue("MISSING_BUNDLE_ID", "manifest must include bundle_id"))

    raw_generated_at = data.get("generated_at")
    if isinstance(raw_generated_at, str) and raw_generated_at:
        generated_at = raw_generated_at
    else:
        issues.append(BackupManifestIssue("MISSING_GENERATED_AT", "manifest must include generated_at"))

    if data.get("required_artifact_kinds") != list(REQUIRED_ARTIFACT_KINDS):
        issues.append(BackupManifestIssue("BAD_REQUIRED_KIND_SET", f"required_artifact_kinds must match {BACKUP_ARTIFACT_AUTHORITY}"))

    raw_artifacts = data.get("artifacts")
    if not isinstance(raw_artifacts, list):
        issues.append(BackupManifestIssue("BAD_ARTIFACTS", "artifacts must be a list"))
        raw_artifacts = []

    seen_kinds: set[str] = set()
    seen_paths: set[str] = set()
    for raw in raw_artifacts:
        if not isinstance(raw, Mapping):
            issues.append(BackupManifestIssue("BAD_ARTIFACT_ENTRY", "each artifact entry must be an object"))
            continue
        artifact = BackupArtifact.from_manifest(raw)
        artifacts.append(artifact)
        issues.extend(_validate_artifact_entry(manifest_path.parent, raw, artifact))
        if artifact.kind:
            if artifact.kind in seen_kinds:
                issues.append(BackupManifestIssue("DUPLICATE_KIND", f"manifest includes duplicate artifact kind {artifact.kind}", artifact.kind, artifact.relative_path))
            seen_kinds.add(artifact.kind)
        if artifact.relative_path:
            try:
                normalized = normalize_relative_path(artifact.relative_path)
            except ValueError:
                continue
            if normalized in seen_paths:
                issues.append(BackupManifestIssue("DUPLICATE_PATH", f"manifest includes duplicate artifact path {normalized}", artifact.kind, normalized))
            seen_paths.add(normalized)

    for kind in REQUIRED_ARTIFACT_KINDS:
        if kind not in seen_kinds:
            issues.append(BackupManifestIssue("MISSING_REQUIRED_KIND", f"manifest is missing required artifact kind {kind}", kind))

    if require_external:
        for artifact in artifacts:
            if artifact.kind in REQUIRED_ARTIFACT_KINDS and not has_external_marker(artifact):
                issues.append(
                    BackupManifestIssue(
                        "MISSING_EXTERNAL_MARKER",
                        f"{artifact.kind} must include an external/offsite marker when require_external=True",
                        artifact.kind,
                        artifact.relative_path,
                    )
                )

    return BackupManifestReport(
        manifest_path=manifest_path,
        artifacts=tuple(artifacts),
        issues=tuple(issues),
        schema_version=schema_version,
        product_version=product_version_value,
        bundle_id=bundle_id,
        generated_at=generated_at,
    )


def discover_backup_artifacts(bundle_dir: Path) -> list[BackupArtifact]:
    artifacts: list[BackupArtifact] = []
    for spec in STANDARD_ARTIFACT_SPECS:
        selected: str | None = None
        for candidate in spec.candidates:
            if (bundle_dir / candidate).is_file():
                selected = candidate
                break
        if selected is None:
            continue
        source = spec.marker_source if "unavailable" in selected else spec.source
        metadata = {"capture_status": "metadata_marker" if "unavailable" in selected else "captured"}
        artifacts.append(
            BackupArtifact(
                kind=spec.kind,
                relative_path=selected,
                required=True,
                source=source,
                notes=spec.notes,
                metadata=metadata,
            )
        )
    return artifacts


def format_backup_manifest_report(report: BackupManifestReport, *, include_artifacts: bool = False) -> str:
    if report.ok:
        lines = [f"Backup manifest verified: {report.manifest_path}"]
    else:
        lines = [f"Backup manifest verification failed: {report.manifest_path}"]
        for issue in report.issues:
            location = ""
            if issue.kind:
                location += f" [{issue.kind}]"
            if issue.relative_path:
                location += f" {issue.relative_path}"
            lines.append(f"- {issue.code}{location}: {issue.message}")
    if include_artifacts:
        lines.append("Artifacts:")
        for artifact in report.artifacts:
            sha = artifact.sha256[:12] if artifact.sha256 else "missing"
            size = artifact.size_bytes if artifact.size_bytes is not None else "unknown"
            lines.append(f"- {artifact.kind}: {artifact.relative_path} ({size} bytes, sha256={sha}...) source={artifact.source}")
    return "\n".join(lines)


def _validate_artifact_entry(bundle_dir: Path, raw: Mapping[str, Any], artifact: BackupArtifact) -> list[BackupManifestIssue]:
    issues: list[BackupManifestIssue] = []
    if artifact.kind not in KNOWN_ARTIFACT_KINDS:
        issues.append(BackupManifestIssue("UNKNOWN_KIND", f"unknown backup artifact kind {artifact.kind!r}", artifact.kind or None, artifact.relative_path or None))
    if not isinstance(raw.get("relative_path"), str) or not raw.get("relative_path"):
        issues.append(BackupManifestIssue("MISSING_RELATIVE_PATH", "artifact must include relative_path", artifact.kind or None))
        return issues
    try:
        artifact_path = resolve_artifact_path(bundle_dir, artifact.relative_path)
    except ValueError as exc:
        issues.append(BackupManifestIssue("BAD_RELATIVE_PATH", str(exc), artifact.kind or None, artifact.relative_path or None))
        return issues
    if not isinstance(raw.get("sha256"), str) or not SHA256_RE.match(str(raw.get("sha256"))):
        issues.append(BackupManifestIssue("BAD_SHA256", "artifact sha256 must be a 64-character hex digest", artifact.kind or None, artifact.relative_path or None))
    if not isinstance(raw.get("size_bytes"), int) or isinstance(raw.get("size_bytes"), bool) or int(raw.get("size_bytes", -1)) < 0:
        issues.append(BackupManifestIssue("BAD_SIZE", "artifact size_bytes must be a non-negative integer", artifact.kind or None, artifact.relative_path or None))
    if not isinstance(raw.get("required"), bool):
        issues.append(BackupManifestIssue("BAD_REQUIRED_FLAG", "artifact required flag must be a boolean", artifact.kind or None, artifact.relative_path or None))
    if not isinstance(raw.get("source"), str) or not raw.get("source"):
        issues.append(BackupManifestIssue("MISSING_SOURCE", "artifact must include source", artifact.kind or None, artifact.relative_path or None))
    if not artifact_path.is_file():
        issues.append(BackupManifestIssue("MISSING_ARTIFACT", f"artifact file not found: {artifact.relative_path}", artifact.kind or None, artifact.relative_path or None))
        return issues
    actual_size = artifact_path.stat().st_size
    if artifact.size_bytes is not None and actual_size != artifact.size_bytes:
        issues.append(
            BackupManifestIssue(
                "SIZE_MISMATCH",
                f"artifact size mismatch: expected {artifact.size_bytes}, got {actual_size}",
                artifact.kind,
                artifact.relative_path,
            )
        )
    if artifact.sha256 and SHA256_RE.match(artifact.sha256):
        actual_sha = sha256_file(artifact_path)
        if actual_sha.lower() != artifact.sha256.lower():
            issues.append(
                BackupManifestIssue(
                    "SHA256_MISMATCH",
                    f"artifact checksum mismatch: expected {artifact.sha256}, got {actual_sha}",
                    artifact.kind,
                    artifact.relative_path,
                )
            )
    return issues


def resolve_artifact_path(bundle_dir: Path, relative_path: str) -> Path:
    normalized = normalize_relative_path(relative_path)
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or ".." in pure.parts:
        raise ValueError(f"artifact relative_path must stay inside the bundle: {relative_path!r}")
    return bundle_dir / Path(*pure.parts)


def normalize_relative_path(relative_path: str) -> str:
    value = relative_path.replace("\\", "/").strip()
    while value.startswith("./"):
        value = value[2:]
    if not value:
        raise ValueError("artifact relative_path must not be empty")
    return str(PurePosixPath(value))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def product_version() -> str:
    try:
        version = VERSION_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return "unknown"
    return version or "unknown"


def has_external_marker(artifact: BackupArtifact) -> bool:
    metadata = artifact.metadata if isinstance(artifact.metadata, Mapping) else {}
    for key in ("external_uri", "offsite_uri", "object_key", "remote_uri", "external_target"):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            return True
    return False


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(k): json_safe(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    return str(value)


def main() -> None:
    parser = argparse.ArgumentParser(description="Write or validate an ExAIS backup artifact manifest.")
    sub = parser.add_subparsers(dest="cmd", required=True)
    write_parser = sub.add_parser("write", help="write manifest.json for a prepared backup bundle")
    write_parser.add_argument("bundle_dir", type=Path)
    validate_parser = sub.add_parser("validate", help="validate a backup manifest")
    validate_parser.add_argument("manifest", type=Path)
    validate_parser.add_argument("--require-external", action="store_true")
    validate_parser.add_argument("--print-artifacts", action="store_true")
    args = parser.parse_args()

    if args.cmd == "write":
        artifacts = discover_backup_artifacts(args.bundle_dir)
        manifest_path = write_backup_manifest(args.bundle_dir, artifacts)
        report = validate_backup_manifest(manifest_path)
        print(format_backup_manifest_report(report, include_artifacts=True))
        if not report.ok:
            raise SystemExit(1)
        return

    report = validate_backup_manifest(args.manifest, require_external=args.require_external)
    print(format_backup_manifest_report(report, include_artifacts=args.print_artifacts))
    if not report.ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
