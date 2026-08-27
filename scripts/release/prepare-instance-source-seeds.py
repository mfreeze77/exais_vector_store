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
    prepare_seed_layout,
    validate_instance_source_packages,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare local seed-folder skeletons for instance source packages.")
    parser.add_argument("--instance", required=True)
    parser.add_argument("--vector-store")
    parser.add_argument("--source")
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--execute", action="store_true", help="create the local seed directories and citation map file")
    parser.add_argument("--root", type=Path, default=ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
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
    plans = [prepare_seed_layout(package, create=args.execute) for package in packages]
    print(json.dumps({
        "instance": args.instance,
        "status": "prepared" if args.execute else "dry_run",
        "mutation_performed": bool(args.execute),
        "package_count": len(packages),
        "sources": plans,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
