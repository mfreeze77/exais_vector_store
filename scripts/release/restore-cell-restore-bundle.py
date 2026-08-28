from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from collections.abc import Mapping
from pathlib import Path

from backup_common import format_backup_manifest_report, validate_backup_manifest


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_extract(archive_path: Path, restore_root: Path) -> Path:
    restore_root.mkdir(parents=True, exist_ok=True)
    root = restore_root.resolve()
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        if not members:
            raise RuntimeError(f"Archive is empty: {archive_path}")
        top = Path(members[0].name).parts[0]
        for member in members:
            if member.issym() or member.islnk():
                raise RuntimeError(f"Archive member is a link and is not allowed: {member.name}")
            if not (member.isdir() or member.isfile()):
                raise RuntimeError(f"Archive member type is not allowed: {member.name}")
            target = (root / member.name).resolve()
            if root not in (target, *target.parents):
                raise RuntimeError(f"Archive member escapes restore root: {member.name}")
        archive.extractall(root)
    return root / top


def validate_checksums(bundle_dir: Path) -> list[str]:
    checksum_path = bundle_dir / "CHECKSUMS.sha256"
    if not checksum_path.is_file():
        return [f"Missing checksum file: {checksum_path}"]
    issues: list[str] = []
    for line_number, line in enumerate(checksum_path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            issues.append(f"Malformed checksum line {line_number}")
            continue
        expected, relative = parts
        relative = relative.strip()
        if relative.startswith("*"):
            relative = relative[1:]
        if relative.startswith("./"):
            relative = relative[2:]
        target = (bundle_dir / relative).resolve()
        try:
            target.relative_to(bundle_dir.resolve())
        except ValueError:
            issues.append(f"Checksum path escapes bundle on line {line_number}: {relative}")
            continue
        if not target.is_file():
            issues.append(f"Checksum target missing on line {line_number}: {relative}")
            continue
        actual = sha256_file(target)
        if actual.lower() != expected.lower():
            issues.append(f"Checksum mismatch for {relative}: expected {expected}, got {actual}")
    return issues


def load_json(path: Path) -> Mapping[str, object]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise RuntimeError(f"Expected JSON object: {path}")
    return data


def validate_indexed_file(bundle_dir: Path, row: Mapping[str, object], *, label: str) -> list[str]:
    issues: list[str] = []
    relative = row.get("relative_path")
    expected_sha = row.get("sha256")
    expected_size = row.get("size_bytes")
    if not isinstance(relative, str) or not relative:
        return [f"{label} row is missing relative_path"]
    if not isinstance(expected_sha, str) or len(expected_sha) != 64:
        issues.append(f"{label} {relative} has invalid sha256")
    if not isinstance(expected_size, int) or isinstance(expected_size, bool) or expected_size < 0:
        issues.append(f"{label} {relative} has invalid size_bytes")
    path = (bundle_dir / relative).resolve()
    try:
        path.relative_to(bundle_dir.resolve())
    except ValueError:
        issues.append(f"{label} {relative} escapes bundle")
        return issues
    if not path.is_file():
        issues.append(f"{label} file missing: {relative}")
        return issues
    if isinstance(expected_size, int) and path.stat().st_size != expected_size:
        issues.append(f"{label} {relative} size mismatch: expected {expected_size}, got {path.stat().st_size}")
    if isinstance(expected_sha, str) and len(expected_sha) == 64:
        actual = sha256_file(path)
        if actual.lower() != expected_sha.lower():
            issues.append(f"{label} {relative} checksum mismatch: expected {expected_sha}, got {actual}")
    return issues


def validate_qdrant_snapshot_index(bundle_dir: Path) -> list[str]:
    index_path = bundle_dir / "qdrant" / "snapshots.json"
    if not index_path.is_file():
        return [f"Missing Qdrant snapshot index: {index_path}"]
    index = load_json(index_path)
    rows = index.get("collections")
    if not isinstance(rows, list):
        return ["Qdrant snapshot index must include a collections list"]
    issues: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            issues.append("Qdrant snapshot row must be an object")
            continue
        collection = row.get("collection")
        snapshot_name = row.get("snapshot_name")
        if not isinstance(collection, str) or not collection:
            issues.append("Qdrant snapshot row is missing collection")
        if not isinstance(snapshot_name, str) or not snapshot_name:
            issues.append(f"Qdrant snapshot row for {collection!r} is missing snapshot_name")
        issues.extend(validate_indexed_file(bundle_dir, row, label="Qdrant snapshot"))
    return issues


def validate_object_volume_index(bundle_dir: Path) -> list[str]:
    index_path = bundle_dir / "object-store" / "volumes.json"
    if not index_path.is_file():
        return [f"Missing object-store volume index: {index_path}"]
    index = load_json(index_path)
    rows = index.get("volumes")
    if not isinstance(rows, list):
        return ["Object-store volume index must include a volumes list"]
    issues: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping):
            issues.append("Object-store volume row must be an object")
            continue
        if not isinstance(row.get("compose_volume"), str) or not row.get("compose_volume"):
            issues.append("Object-store volume row is missing compose_volume")
        if not isinstance(row.get("source_volume"), str) or not row.get("source_volume"):
            issues.append("Object-store volume row is missing source_volume")
        issues.extend(validate_indexed_file(bundle_dir, row, label="Object-store volume"))
    return issues


def validate_bundle(bundle_dir: Path) -> list[str]:
    issues: list[str] = []
    report = validate_backup_manifest(bundle_dir / "manifest.json")
    print(format_backup_manifest_report(report, include_artifacts=True))
    issues.extend(issue.message for issue in report.issues)
    issues.extend(validate_checksums(bundle_dir))
    issues.extend(validate_qdrant_snapshot_index(bundle_dir))
    issues.extend(validate_object_volume_index(bundle_dir))
    return issues


def main() -> None:
    parser = argparse.ArgumentParser(description="Preflight a customer-cell VPS restore bundle.")
    parser.add_argument("bundle", type=Path, help="Bundle directory or .tar.gz archive.")
    parser.add_argument("restore_root", type=Path, nargs="?", default=Path("restore-work"))
    parser.add_argument("--preflight-only", action="store_true", help="Validate only. This script does not mutate a running cell.")
    args = parser.parse_args()

    bundle_path = args.bundle
    if bundle_path.is_dir():
        bundle_dir = bundle_path
    else:
        bundle_dir = safe_extract(bundle_path, args.restore_root)
    issues = validate_bundle(bundle_dir)
    if issues:
        print(f"Restore bundle preflight failed: {len(issues)} issue(s)")
        for issue in issues:
            print(f"- {issue}")
        raise SystemExit(1)
    print(f"Restore bundle preflight passed: {bundle_dir}")
    print("No restore commands were run.")


if __name__ == "__main__":
    main()
