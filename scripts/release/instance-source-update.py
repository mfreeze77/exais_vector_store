#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from instance_source_packages import (
    ROOT,
    build_update_plan,
    execute_update_command,
    validate_instance_source_packages,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan or execute an instance vector-store source update.")
    parser.add_argument("--instance", required=True)
    parser.add_argument("--vector-store", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--previous-manifest", type=Path)
    parser.add_argument("--current-manifest", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.dry_run == args.execute:
        raise SystemExit("choose exactly one of --dry-run or --execute")
    packages, issues = validate_instance_source_packages(
        args.instance,
        root=args.root,
        production=args.production,
        vector_store=args.vector_store,
        source=args.source,
    )
    if issues:
        print(json.dumps({"status": "validation_failed", "issues": [item.to_dict() for item in issues]}, indent=2, sort_keys=True))
        return 1
    if len(packages) != 1:
        print(json.dumps({"status": "not_found", "package_count": len(packages)}, indent=2, sort_keys=True))
        return 1
    package = packages[0]
    plan = build_update_plan(
        package,
        previous_manifest=args.previous_manifest,
        current_manifest=args.current_manifest,
    )
    if args.dry_run:
        plan = {
            **plan,
            "status": "dry_run",
            "mutation_performed": False,
        }
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0
    result = execute_update_command(package)
    print(json.dumps({
        **plan,
        "status": "executed",
        "mutation_performed": True,
        "returncode": result.returncode,
    }, indent=2, sort_keys=True))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
