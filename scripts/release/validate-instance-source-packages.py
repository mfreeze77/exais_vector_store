#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from instance_source_packages import ROOT, validate_instance_source_packages


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate instance-owned vector-store source packages.")
    parser.add_argument("--instance", required=True)
    parser.add_argument("--vector-store")
    parser.add_argument("--source")
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--json", action="store_true", help="print JSON report only")
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
    report = {
        "instance": args.instance,
        "production": bool(args.production),
        "package_count": len(packages),
        "issue_count": len(issues),
        "issues": [item.to_dict() for item in issues],
        "packages": [
            {
                "vector_store_slug": package.vector_store_slug,
                "source_slug": package.source_slug,
                "source_path": package.source_path.relative_to(args.root).as_posix()
                if package.source_path.is_relative_to(args.root)
                else package.source_path.as_posix(),
            }
            for package in packages
        ],
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        status = "PASS" if not issues else "FAIL"
        print(f"{status} instance={args.instance} packages={len(packages)} issues={len(issues)}")
        for item in issues:
            print(f"{item.severity.upper()} {item.code} {item.path}: {item.message}")
    return 1 if issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
