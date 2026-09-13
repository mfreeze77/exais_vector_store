"""Real retained tranche inputs; HTTP effects are explicit isolated test doubles."""
from __future__ import annotations
import copy
import hashlib
import json
import os
from pathlib import Path
import pytest
from test_kansas_fiscal_document_ingest import CONTRACT_FIXTURE, _load_module, _write_manifest
from svs_common.chunking import choose_chunker
from svs_common.ingestion import _page_coordinate_evidence_context
from svs_common.statecivics_statutes import preflight_statute_harvest, statecivics_statute_markdown_chunks

STORE = 'vs_daafbc5d7aa54b23b3f10392'
INDEX_SHA = '65d2424709bb1e54ab7fad9142ceffb6c00f961d463ca78b5dc7c277194f63e0'
HARVEST_SHA = '17bed3eec5f0946de1e2f5126b84b8637d9aa4b910199f98fe4c9f3e3eb207a2'


def required_path(variable):
    value = os.environ.get(variable)
    assert value, f'{variable} is required; this proof must not skip retained inputs'
    path = Path(value)
    assert path.exists(), f'required retained input missing: {variable}'
    return path


@pytest.fixture(scope='module')
def retained():
    exports = required_path('SVS_STATUTE_EXPORT_ROOT')
    corpus = required_path('SVS_STATUTE_CORPUS_ROOT')
    custody = required_path('SVS_STATUTE_CUSTODY_ROOT')
    state_path = required_path('SVS_STATUTE_CANARY_STATE')
    index_bytes = (exports / 'chapters/INDEX.json').read_bytes()
    assert hashlib.sha256(index_bytes).hexdigest() == INDEX_SHA
    index = json.loads(index_bytes)
    ingest = _load_module()
    harvest = preflight_statute_harvest(corpus / 'manifests/statute_scrape_20260911_030653.json', corpus,
                                       expected_manifest_sha256=HARVEST_SHA)
    manifests = {}
    for chapter in ('007', '011', '001', '002', '073', '079', '041', '060'):
        entry = next(e for e in index['chapters'] if e['chapter'] == chapter)
        path = exports / 'chapters' / entry['file']
        raw = path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == entry['sha256'] and len(raw) == entry['bytes']
        manifests[chapter] = ingest.load_manifest(path, vector_store_slug='kansas-statutes', source_family='kansas-statutes', contract_schema=CONTRACT_FIXTURE)
    canary_raw = (exports / 'kansas-statutes.jsonl').read_bytes()
    assert hashlib.sha256(canary_raw).hexdigest() == 'c9a06920795b47d92c8d336395ab94c459fa8404e029a92708444d06276ea3a7'
    canary = ingest.load_manifest(exports / 'kansas-statutes.jsonl', vector_store_slug='kansas-statutes', source_family='kansas-statutes', contract_schema=CONTRACT_FIXTURE)
    state = ingest.load_state(state_path, vector_store_id=STORE)
    assert len(state['records']) == len(canary.records) == 6
    return ingest, harvest, custody, manifests, canary, state


def operations(retained, manifest, state):
    ingest, harvest, custody, *_ = retained
    return ingest.plan_operations(manifest, custody_root=custody, state=state,
                                   source_family='kansas-statutes', statute_harvest=harvest)


def apply_test(ingest, planned, state, tmp_path):
    return ingest.apply_operations(planned, state=state, state_path=tmp_path/'test-state.json',
        api_base='http://test-double.invalid', headers={}, vector_store_id=STORE, knowledge_base_id='kb_ks_civics',
        timeout=1, cell='test-only', transport='auto')


def api_double(calls):
    def call(method, base, path, body, **kwargs):
        assert base == 'http://test-double.invalid'
        calls.append((method, path, copy.deepcopy(body)))
        if path.endswith('/preview'):
            assert body['persist'] is False
            chunks = choose_chunker(body['mode'], attributes=body['attributes'])(body['content'])
            return {'mode': body['mode'], 'chunker': 'statecivics_statute_markdown_v1',
                    'embedding_profile_id': 'voyage_4_docs_1024', 'estimated_chunks': len(chunks)}
        if method == 'DELETE':
            return {}
        assert path == '/api/v1/documents/ingest'
        return {'status': 'completed', 'document_id': 'test-document-'+body['source_identity'],
                'vector_store_file_id': 'test-file-'+body['source_identity']}
    return call


def test_real_chapters_append_to_shared_canary_state_without_omission_deletes(retained, tmp_path, monkeypatch):
    ingest, _, _, manifests, _, seed = retained
    state = copy.deepcopy(seed)
    calls = []
    monkeypatch.setattr(ingest, 'api_json', api_double(calls))
    chapter_a = operations(retained, manifests['007'], state)
    assert [o.action for o in chapter_a].count('upsert') == 5
    assert [o.action for o in chapter_a].count('noop') == 1
    assert sum(len(statecivics_statute_markdown_chunks(o.content.decode('utf-8'), expected_sha256=o.record['content_hash_sha256']))
               for o in chapter_a if o.action == 'upsert') == 22
    assert apply_test(ingest, chapter_a, state, tmp_path) == {'upserted': 5, 'removed': 0, 'unchanged': 1}
    after_a = copy.deepcopy(state['records'])
    chapter_b = operations(retained, manifests['011'], state)
    assert [o.action for o in chapter_b].count('upsert') == 6
    assert [o.action for o in chapter_b].count('noop') == 2
    assert not any(o.logical_document_id in after_a for o in chapter_b)
    assert apply_test(ingest, chapter_b, state, tmp_path) == {'upserted': 6, 'removed': 0, 'unchanged': 2}
    assert all(state['records'][key] == value for key, value in after_a.items())
    assert all(state['records'][key] == value for key, value in seed['records'].items())
    assert len(state['records']) == 20
    assert not any(method == 'DELETE' for method, _, _ in calls)
    before_replay = copy.deepcopy(state)
    call_count = len(calls)
    replay = operations(retained, manifests['011'], state)
    assert all(o.action == 'noop' for o in replay)
    assert apply_test(ingest, replay, state, tmp_path) == {'upserted': 0, 'removed': 0, 'unchanged': 8}
    assert state == before_replay and len(calls) == call_count


def test_test_only_explicit_withdrawal_removes_only_named_document(retained, tmp_path, monkeypatch):
    ingest, _, _, manifests, _, seed = retained
    state = copy.deepcopy(seed)
    calls = []
    monkeypatch.setattr(ingest, 'api_json', api_double(calls))
    for chapter in ('007', '011'):
        apply_test(ingest, operations(retained, manifests[chapter], state), state, tmp_path)
    before = copy.deepcopy(state)
    original = next(r for r in manifests['007'].records if state['records'][r['logical_document_id']]['action'] == 'upsert')
    removal = copy.deepcopy(original)  # altered lifecycle exists only in this isolated test
    removal['lifecycle'].update(state='withdrawn', removal_required=True)
    removal['ingestion'].update(action='remove', recall_evaluation_required=False)
    removal['record_digest_sha256'] = ingest.record_digest(removal)
    path = tmp_path/'test-only-withdrawal.jsonl'
    _write_manifest(path, [removal])
    manifest = ingest.load_manifest(path, vector_store_slug='kansas-statutes', source_family='kansas-statutes', contract_schema=CONTRACT_FIXTURE)
    planned = operations(retained, manifest, state)
    assert len(planned) == 1 and planned[0].action == 'remove'
    call_start = len(calls)
    assert apply_test(ingest, planned, state, tmp_path)['removed'] == 1
    identity = removal['logical_document_id']
    assert calls[call_start:] == [('DELETE', f"/v1/vector_stores/{STORE}/files/{before['records'][identity]['vector_store_file_id']}", None)]
    assert state['records'][identity]['action'] == 'remove'
    assert all(state['records'][key] == value for key, value in before['records'].items() if key != identity)
    assert original['lifecycle']['state'] == 'current'


def test_real_reexport_changes_digest_but_preserves_all_six_canonical_source_identities(retained):
    ingest, _, _, manifests, canary, _ = retained
    current = {r['logical_document_id']:r for manifest in manifests.values() for r in manifest.records}
    for old in canary.records:
        new = current[old['logical_document_id']]
        changed = {key for key in old if old[key] != new[key]}
        assert changed == {'exporter', 'record_digest_sha256'}
        for key in ('logical_document_id', 'source_revision_id', 'content_hash_sha256', 'custody_uri', 'export_record_id'):
            assert old[key] == new[key]
        assert ingest.record_digest(new) == new['record_digest_sha256']


def test_reexport_planner_upsert_is_distinct_from_server_dedupe(retained, tmp_path, monkeypatch):
    ingest, harvest, custody, manifests, canary, seed = retained
    old = next(r for r in canary.records if r['citation_url'].endswith('/001_002_0004.html'))
    new = next(r for r in manifests['001'].records if r['logical_document_id'] == old['logical_document_id'])
    state = copy.deepcopy(seed)
    manifest = ingest.LoadedManifest(Path('test-only-selection'), '0'*64, 0, (new,))
    planned = operations(retained, manifest, state)
    assert len(planned) == 1 and planned[0].action == 'upsert'
    old_evidence = ingest._statute_evidence(old, ingest.read_custody_object(custody, old), harvest)
    def attrs(record, evidence):
        return {**ingest._record_attributes(record), 'extraction_content_hash_sha256':record['content_hash_sha256'],
                'statute_harvest_evidence':evidence}
    assert _page_coordinate_evidence_context(attrs(old, old_evidence)) == _page_coordinate_evidence_context(attrs(new, planned[0].statute_evidence))
    previous = copy.deepcopy(state['records'][old['logical_document_id']])
    monkeypatch.setattr(ingest, 'submit_upsert', lambda *a, **k: {'status':'deduplicated',
        'document_id':previous['document_id'], 'vector_store_file_id':previous['vector_store_file_id']})
    result = apply_test(ingest, planned, state, tmp_path)
    assert result['upserted'] == 1  # acknowledged operation, not an assertion of a new server version
    updated = state['records'][old['logical_document_id']]
    assert updated['record_digest_sha256'] == new['record_digest_sha256']
    assert updated['document_id'] == previous['document_id'] and updated['vector_store_file_id'] == previous['vector_store_file_id']
    assert operations(retained, manifest, state)[0].action == 'noop'
