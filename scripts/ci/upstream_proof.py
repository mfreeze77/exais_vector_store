"""Derive the upstream checkout pin and execute the existing provenance proofs."""
from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
PIN_SOURCE = ROOT / 'packages/svs_common/svs_common/statecivics_contract_pin.py'
PIN_TEST = 'tests/test_statecivics_contract_pin.py'
HISTORY_TEST = 'tests/test_kansas_fiscal_entity_ingest_integration.py'


def checkout_pin():
    for node in ast.parse(PIN_SOURCE.read_text()).body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == 'PINNED_BRANCH_COMMIT':
            return ast.literal_eval(node.value)['entity']
    raise RuntimeError('PINNED_BRANCH_COMMIT declaration was not found')


def targets():
    history, upstream = [], []
    for filename in (HISTORY_TEST, PIN_TEST):
        for node in ast.parse((ROOT / filename).read_text()).body:
            if not isinstance(node, ast.FunctionDef) or not node.name.startswith('test_'):
                continue
            target = f'{filename}::{node.name}'
            if filename == HISTORY_TEST and 'pre_change' in [arg.arg for arg in node.args.args]:
                history.append(target)
            if filename == PIN_TEST and any(isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == 'statecivics_repo' for call in ast.walk(node)):
                upstream.append(target)
    if not history or not upstream:
        raise RuntimeError('history or upstream proof discovery was empty')
    return history, upstream


def run(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    history, upstream = targets()
    negative = f'{PIN_TEST}::test_the_fixture_is_the_upstream_contract_at_the_pinned_commit'
    assert negative in upstream
    results = {}
    for label, selected in [('set', history + upstream), ('unset', [negative])]:
        env = dict(os.environ)
        if label == 'unset':
            env.pop('SVS_STATECIVICS_REPO', None)
        xml = output / f'provenance-{label}.xml'
        command = [sys.executable, '-m', 'pytest', '-q', '-v', '-p', 'no:cacheprovider', f'--junitxml={xml}', *selected]
        result = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True)
        (output / f'provenance-{label}.log').write_text(result.stdout + result.stderr)
        cases = list(ET.parse(xml).iter('testcase'))
        failures = [c for c in cases if c.find('failure') is not None]
        errors = [c for c in cases if c.find('error') is not None]
        skips = [c for c in cases if c.find('skipped') is not None]
        assert len(cases) == len(selected) and not errors and not skips, (label, result.stdout)
        if label == 'set':
            assert result.returncode == 0 and not failures, result.stdout
        else:
            assert result.returncode == 1 and len(failures) == 1, result.stdout
            assert 'SVS_STATECIVICS_REPO is unset' in ET.tostring(failures[0], encoding='unicode')
        line = f"provenance {label.upper()}: {len(cases) - len(failures)} passed, {len(failures)} failed, {len(errors)} setup errors, {len(skips)} skipped"
        if label == 'unset':
            line += ' (required intentional refusal)'
        print(line, flush=True)
        results[label] = {'line': line, 'tests': selected, 'exit_code': result.returncode}
    (output / 'provenance.json').write_text(json.dumps(results, indent=2) + '\n')
    lines = [results[k]['line'] for k in ('set', 'unset')]
    lines += ['History tests:'] + history + ['Upstream tests:'] + upstream
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
            stream.write('## History and upstream provenance\n\n```text\n' + '\n'.join(lines) + '\n```\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pin', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('ci-results'))
    args = parser.parse_args()
    if args.pin:
        print(checkout_pin())
    else:
        run(args.output.resolve())
