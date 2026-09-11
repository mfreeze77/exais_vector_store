"""Real handoff preparation; mutation/recovery cases use isolated HTTP doubles only."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace

import pytest


def module():
    path = Path(__file__).parents[1] / 'scripts/release/kansas-statute-rollout.py'
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location('statute_rollout_test', path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = result
    spec.loader.exec_module(result)
    return result


def required(variable):
    value = os.environ.get(variable)
    assert value, f'{variable} is required; retained-input proof must not skip'
    path = Path(value)
    assert path.exists(), f'missing retained path: {variable}'
    return path


@pytest.fixture(scope='module')
def retained(tmp_path_factory):
    rollout = module()
    exports = required('SVS_STATUTE_EXPORT_ROOT')
    root = required('SVS_STATUTE_CORPUS_ROOT')
    args = SimpleNamespace(index=exports/'chapters/INDEX.json', index_sha256=rollout.INDEX_SHA256,
        harvest_manifest=root/'manifests/statute_scrape_20260911_030653.json', harvest_root=root,
        harvest_manifest_sha256=rollout.HARVEST_SHA256, custody_root=required('SVS_STATUTE_CUSTODY_ROOT'),
        seed_state=required('SVS_STATUTE_ROLLOUT_SEED'), seed_state_sha256=rollout.SEED_SHA256,
        operator_root=tmp_path_factory.mktemp('full-plan'), api='http://api:8080', api_timeout_seconds=1)
    prepared = rollout.prepare(args)
    return rollout, args, prepared


def test_full_real_handoff_plan_and_seed_partition_are_read_only(retained):
    rollout, args, prepared = retained
    assert len(prepared.manifests) == 85
    assert sum(len(m.records) for _, m in prepared.manifests) == 31079
    assert prepared.plan['planned'] == {'upsert': 28801, 'noop': 2278, 'remove': 0}
    assert sum(c['chunks'] for c in prepared.plan['chapters']) == 83258
    assert sum(c['indexable_documents'] for c in prepared.plan['chapters']) == 28812
    seed = json.loads(args.seed_state.read_text())
    flattened = {k: v for s in prepared.seeds.values() for k, v in s['records'].items()}
    assert flattened == seed['records'] and len(flattened) == 20
    assert not list(args.operator_root.iterdir())
    assert prepared.plan['api_calls'] == 0 and prepared.plan['bulk_applied'] is False
    assert {'016a', '022a', '056a', '058a', '070a', '082a'} <= prepared.seeds.keys()


def mini_index(retained, tmp_path, monkeypatch):
    """Test-only index envelope; chapter bytes remain the actual approved files."""
    rollout, args, prepared = retained
    index = json.loads(args.index.read_text())
    index['chapters'] = [copy.deepcopy(e) for e, _ in prepared.manifests if e['chapter'] in ('007', '011')]
    totals = {k: (len(index['chapters']) if k == 'tranches' else sum(e[k] for e in index['chapters'])) for k in rollout.TOTALS}
    index['totals'] = totals
    monkeypatch.setattr(rollout, 'TOTALS', totals)
    for entry in index['chapters']:
        shutil.copyfile(args.index.parent/entry['file'], tmp_path/entry['file'])
    return index


def write_test_index(rollout, tmp_path, index, monkeypatch):
    path = tmp_path/'INDEX.json'
    path.write_text(json.dumps(index))
    digest = rollout.sha(path.read_bytes())
    monkeypatch.setattr(rollout, 'INDEX_SHA256', digest)
    return path, digest


@pytest.mark.parametrize('case', ['index_hash', 'path', 'symlink', 'chapter_hash', 'count', 'scope', 'duplicate_ids', 'wrong_chapter'])
def test_bad_input_fails_before_effects(retained, tmp_path, monkeypatch, case):
    rollout, args, _ = retained
    index = mini_index(retained, tmp_path, monkeypatch)
    if case == 'path':
        index['chapters'][0]['file'] = '../ksa-ch007.jsonl'
    elif case == 'symlink':
        path = tmp_path/index['chapters'][0]['file'];path.unlink();path.symlink_to(args.index.parent/path.name)
    elif case == 'chapter_hash':
        index['chapters'][0]['sha256'] = '0'*64
    elif case == 'count':
        index['chapters'][0]['records'] += 1
    elif case == 'scope':
        index['instance_slug'] = 'different-instance'
    elif case in ('duplicate_ids', 'wrong_chapter'):
        first = tmp_path/index['chapters'][0]['file'];second = tmp_path/index['chapters'][1]['file']
        records = [json.loads(s) for s in second.read_text().splitlines()]
        original = json.loads(first.read_text().splitlines()[0])
        if case == 'duplicate_ids':
            records[0] = original
        else:
            records[0]['citation_url'] = original['citation_url']
            records[0]['record_digest_sha256'] = rollout.consumer.record_digest(records[0])
        second.write_text(''.join(json.dumps(r)+'\n' for r in records))
        index['chapters'][1].update(sha256=rollout.sha(second.read_bytes()), bytes=second.stat().st_size)
    path, digest = write_test_index(rollout, tmp_path, index, monkeypatch)
    if case == 'index_hash':
        digest = '0'*64
    with pytest.raises(ValueError):
        rollout.load_index(path, digest)
    assert not (tmp_path/'states').exists()


def isolated_apply(retained, tmp_path, monkeypatch):
    rollout, original, full = retained
    args = copy.copy(original);args.operator_root = tmp_path
    manifests = [(e, m) for e, m in full.manifests if e['chapter'] in ('007', '011')]
    seeds = {e['chapter']: {'schema_version': 1, 'vector_store_id': rollout.STORE, 'records': {}} for e, _ in manifests}
    prepared = rollout.Prepared(manifests, full.harvest, seeds, full.pins, {})
    monkeypatch.setattr(rollout.consumer, 'default_headers', lambda **kw: {'X-SVS-Tenant-Id': rollout.TENANT, 'X-SVS-Business-Instance-Id': rollout.BUSINESS})
    monkeypatch.setattr(rollout.consumer, 'ensure_vector_store', lambda **kw: rollout.STORE)
    calls, server = [], {}
    def api(method, base, path, body, **kwargs):
        # This function is the sole HTTP double. No local/live endpoint is called.
        calls.append((method, path, copy.deepcopy(body), kwargs.get('idempotency_key')))
        if path.endswith('/preview'):
            assert body['persist'] is False
            chunks = rollout.chunking.choose_chunker(body['mode'], attributes=body['attributes'])(body['content'])
            return {'mode': body['mode'], 'chunker': 'statecivics_statute_markdown_v1', 'embedding_profile_id': 'voyage_4_docs_1024', 'estimated_chunks': len(chunks)}
        assert path == '/api/v1/documents/ingest'
        key = kwargs['idempotency_key']
        return server.setdefault(key, {'status': 'completed', 'document_id': 'test-doc-'+body['source_identity'], 'vector_store_file_id': 'test-file-'+body['source_identity']})
    monkeypatch.setattr(rollout.consumer, 'api_json', api)
    return rollout, args, prepared, calls, server, api


def test_http_failure_stops_and_resume_replays_completed_records(retained, tmp_path, monkeypatch):
    rollout, args, prepared, calls, server, api = isolated_apply(retained, tmp_path, monkeypatch)
    failed = []
    def fail_after_server_accepts(method, base, path, body, **kw):
        response = api(method, base, path, body, **kw)
        if path.endswith('/ingest') and len(server) == 2:
            failed.append(kw['idempotency_key'])
            raise TimeoutError('explicit test-only lost HTTP response after acceptance')
        return response
    monkeypatch.setattr(rollout.consumer, 'api_json', fail_after_server_accepts)
    with rollout.exclusive_lock(tmp_path), pytest.raises(TimeoutError):
        rollout.apply_prepared(args, prepared)
    failure = json.loads((tmp_path/'progress.json').read_text())
    assert failure['status'] == 'failed' and failure['chapter'] == '007' and failure['logical_document_id']
    assert len(server) == 2
    saved = json.loads((tmp_path/'states/ch007.json').read_text())
    assert sum(v['action'] == 'upsert' for v in saved['records'].values()) == 1
    monkeypatch.setattr(rollout.consumer, 'api_json', api)
    with rollout.exclusive_lock(tmp_path):
        result = rollout.apply_prepared(args, prepared)
    assert result['status'] == 'completed' and len(server) == 11
    keys = [c[3] for c in calls if c[1].endswith('/ingest')]
    assert keys.count(failed[0]) == 2  # same server idempotency key after lost response
    completed = {p.name: p.read_bytes() for p in (tmp_path/'states').iterdir()}
    before = len(calls)
    with rollout.exclusive_lock(tmp_path):
        result = rollout.apply_prepared(args, prepared)
    assert result['results'] == {'upserted': 0, 'removed': 0, 'unchanged': 14}
    assert len(calls) == before and completed == {p.name: p.read_bytes() for p in (tmp_path/'states').iterdir()}
    assert len(list((tmp_path/'attempts').iterdir())) == 3
    assert not any(c[0] == 'DELETE' for c in calls)


def test_graceful_stop_checkpoints_and_preserves_omitted_chapter(retained, tmp_path, monkeypatch):
    rollout, args, prepared, calls, server, _ = isolated_apply(retained, tmp_path, monkeypatch)
    with rollout.exclusive_lock(tmp_path), pytest.raises(InterruptedError):
        rollout.apply_prepared(args, prepared, lambda: len(server) >= 2)
    assert json.loads((tmp_path/'progress.json').read_text())['status'] == 'stopped'
    before = (tmp_path/'states/ch007.json').read_bytes()
    only_b = rollout.Prepared(prepared.manifests[1:], prepared.harvest, prepared.seeds, prepared.pins, {})
    with rollout.exclusive_lock(tmp_path):
        rollout.apply_prepared(args, only_b)
    assert (tmp_path/'states/ch007.json').read_bytes() == before
    assert not any(c[0] == 'DELETE' for c in calls)


def test_lock_excludes_second_writer(retained, tmp_path):
    rollout, *_ = retained
    with rollout.exclusive_lock(tmp_path), pytest.raises(RuntimeError, match='writer'):
        with rollout.exclusive_lock(tmp_path):
            pytest.fail('second lock acquired')


@pytest.mark.parametrize('case', ['seed_hash', 'seed_scope', 'seed_omission', 'target', 'resume_pins', 'output_overlap', 'output_checkout'])
def test_seed_target_resume_and_output_guards(retained, tmp_path, monkeypatch, case):
    rollout, original, prepared = retained
    args = copy.copy(original);args.operator_root = tmp_path/'operator'
    if case.startswith('seed'):
        seed = json.loads(args.seed_state.read_text())
        if case == 'seed_scope':
            seed['vector_store_id'] = 'wrong-store'
        if case == 'seed_omission':
            seed['records']['f'*64] = seed['records'].pop(next(iter(seed['records'])))
        path = tmp_path/'seed.json';path.write_text(json.dumps(seed));digest = rollout.sha(path.read_bytes())
        monkeypatch.setattr(rollout, 'SEED_SHA256', digest)
        with pytest.raises(ValueError):
            rollout.partition_seed(path, '0'*64 if case == 'seed_hash' else digest, prepared.manifests)
    elif case in ('target', 'resume_pins'):
        monkeypatch.setattr(rollout, 'load_index', lambda *a: ({}, prepared.manifests))
        monkeypatch.setattr(rollout, 'partition_seed', lambda *a: prepared.seeds)
        if case == 'target':
            args.api = 'http://other-cell:8080'
        else:
            args.operator_root.mkdir();(args.operator_root/'inputs.lock.json').write_text('{}')
        with pytest.raises(ValueError):
            rollout.prepare(args)
    else:
        if case == 'output_overlap':
            args.operator_root = args.harvest_root/'output'
        else:
            tmp_path.joinpath('.git').mkdir()
        with pytest.raises(ValueError):
            rollout.validate_output_paths(args)


def test_wrong_live_caller_scope_prevents_any_api_call(retained, tmp_path, monkeypatch):
    rollout, args, prepared, calls, _, _ = isolated_apply(retained, tmp_path, monkeypatch)
    monkeypatch.setattr(rollout.consumer, 'default_headers', lambda **kw: {'X-SVS-Tenant-Id': 'wrong'})
    with pytest.raises(ValueError, match='scope'):
        rollout.apply_prepared(args, prepared)
    assert calls == [] and not list(tmp_path.iterdir())


def test_cli_sigterm_during_preflight_stops_before_api_effects(retained, tmp_path, monkeypatch):
    rollout, original, prepared = retained
    args = copy.copy(original);args.operator_root = tmp_path/'operator';args.apply = True
    handlers = {}
    monkeypatch.setattr(rollout, 'parse_args', lambda argv: args)
    monkeypatch.setattr(rollout.signal, 'signal', lambda sig, handler: handlers.update({sig: handler}))
    def prepare_then_stop(args):
        handlers[rollout.signal.SIGTERM](rollout.signal.SIGTERM, None)
        return prepared
    monkeypatch.setattr(rollout, 'prepare', prepare_then_stop)
    monkeypatch.setattr(rollout, 'apply_prepared', lambda *a, **kw: pytest.fail('API apply after SIGTERM'))
    assert rollout.main([]) == 130
    assert not (args.operator_root/'states').exists()


def test_cli_wrong_pin_exits_nonzero_without_api_effects(retained, tmp_path, monkeypatch):
    rollout, original, _ = retained
    args = copy.copy(original);args.operator_root = tmp_path/'operator';args.apply = True;args.index_sha256 = '0'*64
    monkeypatch.setattr(rollout, 'parse_args', lambda argv: args)
    monkeypatch.setattr(rollout.signal, 'signal', lambda *a: None)
    monkeypatch.setattr(rollout, 'apply_prepared', lambda *a, **kw: pytest.fail('API apply after failed preflight'))
    assert rollout.main([]) == 2
    assert not (args.operator_root/'states').exists()
