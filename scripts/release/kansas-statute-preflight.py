#!/usr/bin/env python3
"""Verify retained K.S.A. Markdown locally; never export, publish or call an API."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from svs_common.statecivics_statutes import preflight_statute_harvest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--corpus-root', type=Path, required=True)
    parser.add_argument('--expected-manifest-sha256', required=True)
    parser.add_argument('--proof', type=Path)
    args = parser.parse_args()
    try:
        harvest = preflight_statute_harvest(args.manifest, args.corpus_root,
                                          expected_manifest_sha256=args.expected_manifest_sha256)
        payload = json.dumps(harvest.proof, indent=2, sort_keys=True) + '\n'
        if args.proof:
            # Do not permit an output path to overwrite its retained inputs.
            if args.proof.resolve().is_relative_to(args.corpus_root.resolve()) or args.proof.resolve() == args.manifest.resolve():
                raise ValueError('preparation proof must be outside the retained corpus and manifest')
            args.proof.parent.mkdir(parents=True, exist_ok=True)
            args.proof.write_text(payload, encoding='utf-8')
        print(payload, end='')
    except (OSError, ValueError, UnicodeError) as exc:
        print(f'statute preflight failed: {exc}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
