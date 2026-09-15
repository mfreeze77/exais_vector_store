"""Machine-readable pytest collection, exclusion, skip and fixture evidence."""
import json
from pathlib import Path

import pytest

evidence = {'selected': [], 'deselected': [], 'passed': [], 'failed': [],
            'setup_errors': [], 'skipped': [], 'collection_errors': [], 'retained_fixtures': {}}


def pytest_addoption(parser):
    parser.addoption('--inventory-json', required=True)


def pytest_deselected(items):
    evidence['deselected'].extend(item.nodeid for item in items)


def pytest_collection_finish(session):
    evidence['selected'] = [item.nodeid for item in session.items]


@pytest.hookimpl(hookwrapper=True)
def pytest_fixture_setup(fixturedef, request):
    outcome = yield
    if fixturedef.argname == 'retained' and fixturedef.baseid in {
        'tests/test_kansas_statute_rollout.py', 'tests/test_kansas_statute_tranches.py',
    }:
        evidence['retained_fixtures'][fixturedef.baseid] = outcome.excinfo is None


def pytest_collectreport(report):
    if report.failed:
        evidence['collection_errors'].append(report.nodeid)


def pytest_runtest_logreport(report):
    if report.skipped:
        evidence['skipped'].append({'nodeid': report.nodeid, 'reason': str(report.longrepr)})
    elif report.failed:
        evidence['failed' if report.when == 'call' else 'setup_errors'].append(report.nodeid)
    elif report.when == 'call' and report.passed:
        evidence['passed'].append(report.nodeid)


def pytest_sessionfinish(session, exitstatus):
    evidence['exit_code'] = int(exitstatus)
    output = Path(session.config.getoption('--inventory-json'))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + '\n')
