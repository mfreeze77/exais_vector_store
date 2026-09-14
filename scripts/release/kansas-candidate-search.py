#!/usr/bin/env python3
"""Retrieve candidate records and their source citations through the ExAIS API."""
import argparse
import json

from topeka_pipeline_common import api_json, default_headers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('query')
    parser.add_argument('--api', required=True)
    parser.add_argument('--cell', default='ks-fiscal-local')
    parser.add_argument('--limit', type=int, default=5)
    args = parser.parse_args()
    result = api_json('POST', args.api, '/api/v1/statecivics/entities/candidate/search',
                      {'query': args.query, 'limit': args.limit},
                      headers=default_headers(cell=args.cell), timeout=180,
                      cell=args.cell, transport='auto')
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
