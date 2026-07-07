#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, os, subprocess, sys
from pathlib import Path
import urllib.request


def http_json(method: str, url: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode())


def run(cmd: list[str]):
    print('+', ' '.join(cmd))
    subprocess.run(cmd, check=True)


def main():
    p = argparse.ArgumentParser('svsctl')
    sub = p.add_subparsers(dest='cmd', required=True)
    d = sub.add_parser('deploy'); d.add_argument('manifest'); d.add_argument('--agent', default=os.getenv('SVS_AGENT_URL','http://localhost:8090')); d.add_argument('--version'); d.add_argument('--dry-run', action='store_true')
    b = sub.add_parser('backup'); b.add_argument('manifest')
    r = sub.add_parser('restore'); r.add_argument('bundle')
    u = sub.add_parser('fleet-upgrade'); u.add_argument('version'); u.add_argument('--max-concurrent', type=int, default=3)
    args = p.parse_args()
    if args.cmd == 'deploy':
        print(json.dumps(http_json('POST', f'{args.agent}/agent/v1/instances/deploy', {'manifest_path': args.manifest, 'version': args.version, 'dry_run': args.dry_run}), indent=2))
    elif args.cmd == 'backup':
        run(['bash', 'scripts/backup-instance.sh', args.manifest])
    elif args.cmd == 'restore':
        run(['bash', 'scripts/restore-instance.sh', args.bundle])
    elif args.cmd == 'fleet-upgrade':
        manifests = [str(x) for x in Path('instances').glob('**/instance.yaml') if '_templates' not in str(x)]
        for manifest in manifests:
            run(['python', 'scripts/svsctl.py', 'deploy', manifest, '--version', args.version])

if __name__ == '__main__':
    main()
