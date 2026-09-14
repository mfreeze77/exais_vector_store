#!/usr/bin/env python3
"""Start the local candidate API beside ks-fiscal-local using its runtime config.

No source service is stopped or recreated. Secret environment values pass
through an owner-only temporary file removed immediately after Docker reads it.
The command line contains no secret values.
"""
import argparse
import json
import os
import re
import subprocess
import tempfile

SOURCE = 'exais-vector-store-ks-fiscal-local-api-1'
TARGET = 'exais-ks-fiscal-candidate-api'
NETWORK = 'exais-vector-store-ks-fiscal-local_default'


def run(args, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True, **kwargs)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image', required=True, help='immutable local sha256 image ID')
    p.add_argument('--source-commit', required=True)
    p.add_argument('--apply', action='store_true')
    args = p.parse_args()
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', args.image) or not re.fullmatch(r'[0-9a-f]{40}', args.source_commit):
        p.error('image and source commit must be complete immutable identifiers')
    source = json.loads(run(['docker', 'inspect', SOURCE]).stdout)[0]
    assert source['State']['Running'] and NETWORK in source['NetworkSettings']['Networks']
    environment = dict(v.split('=', 1) for v in source['Config']['Env'])
    assert environment.get('SVS_ENV') == 'local', 'this helper is for the local cell only'
    environment['SVS_ENTITY_CANDIDATE_ENABLED'] = 'true'
    inspected = json.loads(run(['docker', 'image', 'inspect', args.image]).stdout)[0]
    plan = {'source_container': SOURCE, 'source_image': source['Image'],
            'candidate_container': TARGET, 'candidate_image': inspected['Id'],
            'source_commit': args.source_commit, 'network': NETWORK,
            'url': 'http://127.0.0.1:28086', 'applied': False}
    command = ['docker', 'run', '-d', '--name', TARGET, '--restart', 'unless-stopped',
               '--network', NETWORK, '--network-alias', 'candidate-api',
               '-p', '127.0.0.1:28086:8080', '--memory', '2g',
               '--health-cmd', 'curl -fsS http://127.0.0.1:8080/readyz',
               '--health-interval', '5s', '--health-timeout', '5s', '--health-retries', '12',
               '--label', f'org.opencontainers.image.revision={args.source_commit}',
               '--label', 'exais.role=statecivics-candidate-api']
    for mount in source['Mounts']:
        if mount['Type'] == 'volume' and mount['Destination'] == '/data/object-store':
            command.extend(['-v', f"{mount['Name']}:{mount['Destination']}"])
    if args.apply:
        existing = subprocess.run(['docker', 'inspect', TARGET], capture_output=True, text=True)
        if existing.returncode == 0:
            old = json.loads(existing.stdout)[0]
            assert old['Image'] == inspected['Id'] and old['State']['Running'], 'existing candidate service differs; refusing to replace it'
            plan['container_id'] = old['Id']
        else:
            # A container's PATH/HOME are not the host's. Passing its entire
            # environment to the docker subprocess would replace the host PATH.
            # Docker reads this owner-only file once; it is removed immediately.
            assert all('\n' not in v and '\r' not in v for v in environment.values())
            fd, filename = tempfile.mkstemp(prefix='ks-candidate-', suffix='.env')
            try:
                with os.fdopen(fd, 'w') as stream:
                    stream.write(''.join(f'{k}={v}\n' for k, v in sorted(environment.items())))
                plan['container_id'] = run(command + ['--env-file', filename, args.image, *source['Config']['Cmd']]).stdout.strip()
            finally:
                os.unlink(filename)
        plan['applied'] = True
    print(json.dumps(plan, indent=2))


if __name__ == '__main__':
    main()
