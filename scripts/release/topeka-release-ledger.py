#!/usr/bin/env python3
"""Record what has been released, cumulatively, across every release.

A single previous manifest is not the released state. A document published in
release 1 and not re-published in release 2 is still published, but comparing
against release 2 alone makes it look new again — which re-releases unchanged
content and corrupts the changed/unchanged accounting.

This ledger is the cumulative answer: one row per ``source_document_id`` holding
the version last released and where. It is updated **after** a release
validates, never before, so a failed release does not mark anything as
published.

    python scripts/release/topeka-release-ledger.py --manifest <release-manifest.json> --ledger <path>

Offline: reads a manifest, writes the ledger. Nothing else.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jurisdiction_release_contract import ROOT  # noqa: E402

DEFAULT_LEDGER = (
    ROOT / "instances" / "ks-state-civics" / "vector-stores" / "topeka-municipal-code"
    / "releases" / "released-state.jsonl"
)


def load_ledger(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return {
            row["source_document_id"]: row
            for row in (json.loads(line) for line in handle if line.strip())
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--dry-run", action="store_true", help="report what would change; write nothing")
    args = parser.parse_args()

    if not args.manifest.exists():
        print(f"FAIL manifest {args.manifest} is absent")
        return 1
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    ledger = load_ledger(args.ledger)

    release_id = manifest["release"]["release_id"]
    released_at = manifest["release"]["released_at"]
    added = updated = unchanged = 0

    for entry in manifest["documents"]:
        doc_id = entry["source_document_id"]
        row = {
            "source_document_id": doc_id,
            "collection_id": entry["collection_id"],
            "document_version_id": entry["document_version_id"],
            "payload_sha256": entry["payload_sha256"],
            "release_id": release_id,
            "released_at": released_at,
        }
        previous = ledger.get(doc_id)
        if previous is None:
            added += 1
        elif previous["document_version_id"] != entry["document_version_id"]:
            updated += 1
            row["prior_version_id"] = previous["document_version_id"]
            row["prior_release_id"] = previous["release_id"]
        else:
            unchanged += 1
            row = previous  # keep the release that first published this version
        ledger[doc_id] = row

    if not args.dry_run:
        args.ledger.parent.mkdir(parents=True, exist_ok=True)
        args.ledger.write_text(
            "".join(json.dumps(ledger[key], sort_keys=True) + "\n" for key in sorted(ledger)),
            encoding="utf-8",
        )

    print(f"release            {release_id}")
    print(f"ledger             {args.ledger}")
    print(f"  newly released   {added}")
    print(f"  version updated  {updated}")
    print(f"  already recorded {unchanged}")
    print(f"  total tracked    {len(ledger)}")
    if args.dry_run:
        print("dry run — ledger not written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
