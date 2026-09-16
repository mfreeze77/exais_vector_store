#!/usr/bin/env python3
"""Write a committable lock for a release bundle that is too large for Git.

WAVE-117's rule is that large corpora live in the cell object store and Git
carries a checksummed pointer. A full Topeka release is 124 MB across 12,353
files, so the bundle itself is not committed; this lock is, and it records
everything needed to identify and verify the bundle wherever it ends up.

    python scripts/release/topeka-release-lock.py --bundle <dir> --output <lock.json>

The lock deliberately records whether a durable URI exists. An unpublished
bundle says so, rather than implying it is retrievable somewhere it is not.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jurisdiction_release_contract import sha256_bytes, sha256_file  # noqa: E402


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--durable-uri", default=None,
                        help="object-store URI the bundle has actually been published to")
    parser.add_argument("--backup-uri", default=None)
    parser.add_argument("--validation-proof", type=Path, default=None)
    parser.add_argument("--verify", action="store_true",
                        help="check an existing lock against the bundle instead of writing one; "
                             "run this before durable publication")
    args = parser.parse_args()

    manifest_path = args.bundle / "release-manifest.json"
    if not manifest_path.exists():
        print(f"FAIL {manifest_path} is absent")
        return 1
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes.decode("utf-8"))

    files = [path for path in args.bundle.rglob("*") if path.is_file()]
    byte_count = sum(path.stat().st_size for path in files)

    validation: dict[str, Any] | None = None
    if args.validation_proof and args.validation_proof.exists():
        validation = json.loads(args.validation_proof.read_text(encoding="utf-8"))

    lock = {
        "artifact": "topeka_release_lock",
        "schema_version": "1.0",
        "locked_at": utc_now(),
        "release_id": manifest["release"]["release_id"],
        "released_at": manifest["release"]["released_at"],
        "bundle_kind": manifest["release"]["bundle_kind"],
        "producer": manifest["release"]["producer"],
        "schemas": manifest["release"]["schemas"],
        "manifest_sha256": sha256_bytes(manifest_bytes),
        "manifest_byte_count": len(manifest_bytes),
        "inventory_sha256": manifest["inventory"]["inventory_sha256"],
        "document_count": manifest["inventory"]["document_count"],
        "file_count_in_manifest": manifest["inventory"]["file_count"],
        "bundle_file_count": len(files),
        "bundle_byte_count": byte_count,
        "by_collection": manifest["inventory"].get("by_collection", []),
        "collections": [
            {
                "collection_id": entry["collection_id"],
                "document_count": entry["document_count"],
                "coverage": entry["coverage"]["state"],
                "vector_store_id": entry["vector_store_id"],
            }
            for entry in manifest["collections"]
        ],
        "local_path": str(args.bundle),
        "durable_uri": args.durable_uri,
        "backup_uri": args.backup_uri,
        "durable_publication": (
            "published" if args.durable_uri else
            "NOT PUBLISHED — the bundle exists only at local_path on the producing host. "
            "No object store is configured for this instance, so it is not retrievable elsewhere "
            "and must not be cited as a durable release"
        ),
        "validation": (
            {
                "passed": validation["passed"],
                "error_count": validation["error_count"],
                "warning_count": validation["warning_count"],
                "evidence_references_resolved": validation["checks"].get("evidence_references_resolved"),
                "evidence_references_unavailable": validation["checks"].get("evidence_references_unavailable"),
                "proof": str(args.validation_proof),
            }
            if validation else None
        ),
        "verify_command": [
            "python", "scripts/release/jurisdiction-release-validate.py",
            "--bundle", str(args.bundle),
        ],
    }

    if args.verify:
        if not args.output.exists():
            print(f"FAIL lock {args.output} is absent")
            return 1
        recorded = json.loads(args.output.read_text(encoding="utf-8"))
        mismatches = [
            (field, recorded.get(field), lock[field])
            for field in (
                "release_id", "manifest_sha256", "inventory_sha256",
                "document_count", "bundle_file_count", "bundle_byte_count",
            )
            if recorded.get(field) != lock[field]
        ]
        for field, was, now in mismatches:
            print(f"  MISMATCH {field}: lock records {was}, bundle has {now}")
        print(f"result             {'PASS' if not mismatches else 'FAIL'}")
        return 0 if not mismatches else 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"release_id         {lock['release_id']}")
    print(f"documents          {lock['document_count']:,}")
    print(f"bundle files       {lock['bundle_file_count']:,}")
    print(f"bundle bytes       {lock['bundle_byte_count']:,}")
    print(f"manifest sha256    {lock['manifest_sha256']}")
    print(f"inventory sha256   {lock['inventory_sha256']}")
    print(f"durable            {lock['durable_publication'][:70]}")
    print(f"lock               {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
