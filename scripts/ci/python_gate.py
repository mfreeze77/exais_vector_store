"""Run the Python gate with a reviewed, counted workstation-corpus boundary."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
MARKER = 'workstation_corpus'
REVIEWED = ROOT / 'scripts/ci/workstation-corpus-nodeids.json'


def expected():
    values = json.loads(REVIEWED.read_text())
    assert values and len(values) == len(set(values)), 'reviewed corpus inventory is empty or duplicated'
    return set(values)


def emit_summary(text):
    print(text, flush=True)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
            stream.write(text + '\n')


def run(mode, output):
    output.mkdir(parents=True, exist_ok=True)
    report = output / f'{mode}-inventory.json'
    env = dict(os.environ)
    env['PYTHONPATH'] = str(ROOT / 'scripts/ci') + os.pathsep + env.get('PYTHONPATH', '')
    command = [sys.executable, '-m', 'pytest', '-q', '--strict-markers', '-p', 'no:cacheprovider',
               '-p', 'pytest_inventory', f'--inventory-json={report}',
               '-m', f'not {MARKER}' if mode == 'run' else MARKER]
    if mode == 'collect':
        command.append('--collect-only')
    else:
        command.append(f'--junitxml={output / (mode + ".xml")}')
    result = subprocess.run(command, cwd=ROOT, env=env)
    data = json.loads(report.read_text())
    approved = expected()
    selected, deselected = set(data['selected']), set(data['deselected'])
    assert len(selected) == len(data['selected']) and len(deselected) == len(data['deselected'])
    assert not selected & deselected
    if mode == 'collect':
        assert result.returncode == 0 and selected == approved, 'marked corpus node IDs differ from the reviewed inventory'
        emit_summary(f'workstation corpus inventory: derived={len(selected)}, reviewed={len(approved)}; exact node-ID equality PASS')
        return
    inventory = json.loads((output / 'collect-inventory.json').read_text())
    assert set(inventory['selected']) == approved
    assert selected | deselected == set(inventory['selected']) | set(inventory['deselected']), 'test collection changed after inventory'
    if mode == 'run':
        assert deselected == approved, 'actual CI deselections differ from the reviewed corpus inventory'
        emit_summary(f'workstation corpus deselected: derived={len(approved)}, collected={len(inventory["selected"])}, actual={len(deselected)}; exact node-ID equality PASS')
    else:
        assert selected == approved and set(data['passed']) == approved and not data['skipped'], 'local corpus run did not execute every reviewed test'
        fixtures = data['retained_fixtures']
        modules = {node.split('::')[0] for node in approved}
        assert set(fixtures) == modules and all(fixtures.values()), 'the real retained fixture preflights did not both pass'
        emit_summary(f'corpus preflight: {len(fixtures)} retained fixtures PASS, {len(data["setup_errors"])} setup errors; {len(data["passed"])} passed, {len(data["skipped"])} skipped')
    counts = ', '.join(f'{len(data[key])} {key}' for key in ('passed', 'failed', 'setup_errors', 'skipped', 'collection_errors'))
    emit_summary(f'Python {mode}: {counts}')
    names = '\n'.join(sorted(approved))
    skips = '\n'.join(f'{row["nodeid"]}: {row["reason"]}' for row in data['skipped']) or '(none)'
    emit_summary(f'<details><summary>Named workstation corpus coverage ({len(approved)})</summary>\n\n```text\n{names}\n```\n</details>')
    emit_summary(f'<details><summary>Existing runtime skips ({len(data["skipped"])}) and reasons</summary>\n\n```text\n{skips}\n```\n</details>')
    assert result.returncode == 0 and not data['failed'] and not data['setup_errors'] and not data['collection_errors'], 'Python tests failed; see pytest output and inventory'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('collect', 'run', 'corpus'))
    parser.add_argument('--output', type=Path, default=Path('ci-results'))
    args = parser.parse_args()
    run(args.mode, args.output.resolve())
