#!/usr/bin/env python3
"""The wired refresh entrypoint for the Topeka collections.

One command that runs the whole loop in order, rather than a runbook asking an
operator to paste four commands with placeholders in them:

    discover -> acquire -> destination manifests (routing proof) -> validate

    python scripts/release/topeka-collection-refresh.py --dry-run
    python scripts/release/topeka-collection-refresh.py --execute

Like ``instance-source-update.py``, exactly one of ``--dry-run`` or
``--execute`` is required, so a refresh is never started by accident.

``--offline`` skips the two stages that contact the publisher and runs the rest,
which is what makes the routing and validation proofs runnable with external
calls disabled. No stage in this script ingests, embeds, creates a vector store
or touches a database; activation remains a separate, authorized step.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jurisdiction_release_contract import CODE_ROOT, ROOT  # noqa: E402

INSTANCE = ROOT / "instances" / "ks-state-civics" / "vector-stores" / "topeka-municipal-code"
DISCOVERY = INSTANCE / "discovery"
ACQUISITION = INSTANCE / "acquisition"
DESTINATIONS = INSTANCE / "destinations"
EXTRACTION = INSTANCE / "extraction"
RELEASES = INSTANCE / "releases"
LEDGER = RELEASES / "released-state.jsonl"
POINTER = RELEASES / "proofs" / "last-release-pointer.json"

RELEASE = CODE_ROOT / "scripts" / "release"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_pointer() -> dict[str, Any] | None:
    """Where the export stage said it actually wrote, if it wrote at all."""
    if not POINTER.exists():
        return None
    try:
        return json.loads(POINTER.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def stages(*, offline: bool, release_bundle: Path, previous_manifest: Path | None,
           delay: float, trust_checkpoint: bool,
           reference_originals: bool = False) -> list[dict[str, Any]]:
    """The ordered pipeline. Every command here is fully formed and runnable."""
    discover = [
        sys.executable, str(RELEASE / "topeka-collection-discover.py"),
        "--listing", "all", "--output-dir", str(DISCOVERY), "--save-listing-html",
    ]
    acquire = [
        sys.executable, str(RELEASE / "topeka-collection-acquire.py"),
        "--worklist", str(DISCOVERY / "worklist.jsonl"),
        "--output-dir", str(ACQUISITION),
        "--delay", str(delay),
    ]
    if trust_checkpoint:
        acquire.append("--trust-checkpoint")

    manifests = [
        sys.executable, str(RELEASE / "topeka-destination-manifests.py"),
        "--checkpoint", str(ACQUISITION / "acquisition-checkpoint.jsonl"),
        "--worklist", str(DISCOVERY / "worklist.jsonl"),
        "--output-dir", str(DESTINATIONS),
    ]

    extract = [
        sys.executable, str(RELEASE / "topeka-docx-extract.py"),
        "--acquisition-dir", str(ACQUISITION),
        "--output-dir", str(EXTRACTION),
    ]

    selection_path = DESTINATIONS / "release-selection.jsonl"
    select = [
        sys.executable, str(RELEASE / "topeka-release-selection.py"),
        "--destinations-dir", str(DESTINATIONS),
        "--extraction-dir", str(EXTRACTION),
        "--checkpoint", str(ACQUISITION / "acquisition-checkpoint.jsonl"),
        "--output", str(selection_path),
    ]
    select += ["--released-state", str(LEDGER)]
    if previous_manifest:
        select += ["--previous-manifest", str(previous_manifest)]

    # The release is exactly what the selection says is eligible. There is no
    # hardcoded set alongside it: a run with nothing eligible must publish
    # nothing, and any hardcoded selector would publish regardless.
    export = [
        sys.executable, str(RELEASE / "topeka-source-release-export.py"),
        "--selection", str(selection_path),
        "--output-dir", str(release_bundle),
        "--release-id", release_bundle.name,
        "--bundle-kind", "starter",
        "--released-state", str(LEDGER),
        # A refresh runs on a schedule against an id that may already be
        # published. Allocating a new id keeps every published one immutable
        # rather than failing the run or rewriting history.
        "--on-conflict", "allocate",
        "--release-pointer", str(POINTER),
        "--allow-empty",
    ]
    if reference_originals:
        # Larger releases reference the publisher bytes by URI and hash instead of
        # carrying them; the validator still requires a resolvable reference.
        export.append("--reference-originals")
    if previous_manifest:
        export += ["--previous-manifest", str(previous_manifest)]

    # Validation and the ledger must target the release that was actually
    # written. --on-conflict allocate can move it to a suffixed id, and a stage
    # that re-derives the path from the REQUESTED id validates and records the
    # wrong bundle while still exiting 0.
    validate = [
        sys.executable, str(RELEASE / "jurisdiction-release-validate.py"),
        "--bundle", "@release_dir",
        "--output", "@validation_proof",
    ]

    ledger = [
        sys.executable, str(RELEASE / "topeka-release-ledger.py"),
        "--manifest", "@release_manifest",
        "--ledger", str(LEDGER),
    ]

    return [
        {"name": "discover", "command": discover, "contacts_publisher": True},
        {"name": "acquire", "command": acquire, "contacts_publisher": True},
        {"name": "extract", "command": extract, "contacts_publisher": False},
        {"name": "destination-manifests", "command": manifests, "contacts_publisher": False},
        {"name": "release-selection", "command": select, "contacts_publisher": False},
        {"name": "export-release", "command": export, "contacts_publisher": False},
        {"name": "validate-release", "command": validate, "contacts_publisher": False},
        # Last, and only after validation: a failed release must not mark
        # anything as published.
        {"name": "record-released-state", "command": ledger, "contacts_publisher": False},
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="print the exact commands; run nothing")
    mode.add_argument("--execute", action="store_true", help="run every stage in order, stopping on failure")
    parser.add_argument("--offline", action="store_true",
                        help="skip the stages that contact the publisher; the rest still run")
    parser.add_argument("--release-id", default=None)
    parser.add_argument("--previous-manifest", type=Path, default=None)
    parser.add_argument("--delay", type=float, default=0.35)
    parser.add_argument("--trust-checkpoint", action="store_true")
    parser.add_argument("--reference-originals", action="store_true",
                        help="reference retained originals by URI and hash instead of copying them "
                             "into the bundle")
    parser.add_argument("--output", type=Path, default=None, help="write the run receipt here")
    args = parser.parse_args()

    release_id = args.release_id or f"topeka-source-{datetime.now(timezone.utc):%Y-%m-%d}-refresh"
    bundle = RELEASES / release_id
    release_bundle_path = bundle
    planned = stages(
        offline=args.offline,
        release_bundle=bundle,
        previous_manifest=args.previous_manifest,
        delay=args.delay,
        trust_checkpoint=args.trust_checkpoint,
        reference_originals=args.reference_originals,
    )

    if not args.dry_run and POINTER.exists():
        POINTER.unlink()

    results: list[dict[str, Any]] = []
    failed = False
    for stage in planned:
        skipped = args.offline and stage["contacts_publisher"]
        printable = " ".join(stage["command"])
        if skipped:
            results.append({"stage": stage["name"], "status": "skipped_offline", "command": printable})
            print(f"  SKIP     {stage['name']} (offline; this stage contacts the publisher)")
            continue
        if args.dry_run:
            results.append({"stage": stage["name"], "status": "dry_run", "command": printable})
            print(f"  WOULD RUN {stage['name']}\n            {printable}")
            continue
        if failed:
            results.append({"stage": stage["name"], "status": "not_reached", "command": printable})
            print(f"  SKIP     {stage['name']} (an earlier stage failed)")
            continue

        command = list(stage["command"])
        if any(str(token).startswith("@") for token in command):
            pointer = read_pointer()
            if pointer is None or not pointer.get("manifest_path"):
                results.append({"stage": stage["name"], "status": "skipped_nothing_released",
                                "command": printable})
                print(f"  SKIP     {stage['name']} (nothing was eligible; no release was written)")
                continue
            release_dir = Path(pointer["output_dir"])
            substitutions = {
                "@release_dir": str(release_dir),
                "@release_manifest": pointer["manifest_path"],
                "@validation_proof": str(RELEASES / "proofs" / f"{pointer['release_id']}-validation.json"),
            }
            command = [substitutions.get(str(token), token) for token in command]
            printable = " ".join(map(str, command))

        print(f"  RUN      {stage['name']}")
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        status = "passed" if completed.returncode == 0 else "failed"
        failed = failed or completed.returncode != 0
        results.append({
            "stage": stage["name"],
            "status": status,
            "command": printable,
            "exit_code": completed.returncode,
            "tail": (completed.stdout or completed.stderr).strip().splitlines()[-12:],
        })
        for line in results[-1]["tail"]:
            print(f"             {line}")

    pointer = read_pointer()
    receipt = {
        "artifact": "topeka_collection_refresh",
        "release_written": pointer,
        "schema_version": "1.0",
        "observed_at": utc_now(),
        "mode": "dry_run" if args.dry_run else "execute",
        "offline": args.offline,
        "release_id": release_id,
        "stages": results,
        "passed": not failed,
    }
    destination = args.output or (RELEASES / "proofs" / f"refresh-{'dryrun' if args.dry_run else 'run'}.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"receipt   {destination}")
    print(f"result    {'PASS' if not failed else 'FAIL'}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
