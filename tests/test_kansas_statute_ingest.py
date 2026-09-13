"""Consumer-boundary tests use explicit test export records, never a live export."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_kansas_fiscal_document_ingest import _load_module, _record, _write_manifest, _write_custody
from test_statecivics_statutes import small_harvest, sha, URL
from svs_common.statecivics_statutes import preflight_statute_harvest, STATECIVICS_STATUTE_MARKDOWN_PROFILE, StatuteHarvest


@pytest.fixture
def setup(tmp_path):
    ingest = _load_module()
    path, root, records, text = small_harvest(tmp_path)
    harvest = preflight_statute_harvest(path, root, expected_manifest_sha256=sha(path.read_bytes()))
    record = _record(ingest, text.encode(), mime_type='text/markdown')
    record.update(artifact_type='statute', citation_url=URL, title='K.S.A. test mechanics')
    record['ingestion']['target_vector_store_slug'] = 'kansas-statutes'
    record['record_digest_sha256'] = ingest.record_digest(record)
    manifest_path = tmp_path / 'export.jsonl'
    _write_manifest(manifest_path, [record])
    manifest = ingest.load_manifest(manifest_path, vector_store_slug='kansas-statutes', source_family='kansas-statutes')
    custody = tmp_path / 'custody'
    _write_custody(custody, record, text.encode())
    state = {'schema_version': 1, 'vector_store_id': 'vs_statutes', 'records': {}}
    return ingest, manifest, custody, state, harvest


def plan(setup, **kwargs):
    ingest, manifest, custody, state, harvest = setup
    return ingest.plan_operations(manifest, custody_root=custody, state=state, source_family='kansas-statutes',
                                  statute_harvest=harvest, **kwargs)


def apply(ingest, operations, state, tmp_path):
    return ingest.apply_operations(operations, state=state, state_path=tmp_path / 'state.json', api_base='http://no-network',
                                   headers={}, vector_store_id='vs_statutes', knowledge_base_id='kb', timeout=1,
                                   cell='test', transport='auto')


def preview_ok():
    return {'mode': 'markdown_docs_v1', 'chunker': STATECIVICS_STATUTE_MARKDOWN_PROFILE,
            'embedding_profile_id': 'voyage_4_docs_1024', 'estimated_chunks': 2}


def test_statute_export_join_preview_ingest_and_repeat_preserve_bytes_and_digest(setup, tmp_path, monkeypatch):
    ingest, manifest, _, state, _ = setup
    original = copy.deepcopy(manifest.records[0])
    calls = []
    def api(method, base, path, body, **kwargs):
        calls.append((method, path, body, kwargs))
        if path.endswith('/preview'):
            return preview_ok()
        return {'status': 'completed', 'document_id': 'doc', 'vector_store_file_id': 'file'}
    monkeypatch.setattr(ingest, 'api_json', api)
    operations = plan(setup)
    assert operations[0].action == 'upsert'
    assert apply(ingest, operations, state, tmp_path)['upserted'] == 1
    assert [c[1] for c in calls] == ['/api/v1/ingestion/preview', '/api/v1/documents/ingest']
    preview, request = calls[0][2], calls[1][2]
    assert preview == {**request, 'persist': False}
    assert request['content'].encode() == operations[0].content
    attrs = request['attributes']
    assert attrs['source_collection'] == 'statecivics-kansas-statutes'
    assert attrs['source_text_chunking_profile'] == STATECIVICS_STATUTE_MARKDOWN_PROFILE
    assert 'source_page_chunking_profile' not in attrs and 'marker_profile' not in attrs
    assert attrs['statute_harvest_evidence']['history_events'][0]['resolution_status'] == 'unresolved'
    assert attrs['source_revision_id'] == original['source_revision_id']
    assert request['source_identity'] == original['logical_document_id']
    assert manifest.records[0] == original
    assert plan(setup)[0].action == 'noop'
    apply(ingest, plan(setup), state, tmp_path)
    assert len(calls) == 2


@pytest.mark.parametrize('preview', [None, {}, {'error': 'unsupported'},
    {**preview_ok(), 'chunker': 'markdown_heading_chunks'}, {**preview_ok(), 'mode': 'pdf_markdown_external_v1'},
    {**preview_ok(), 'embedding_profile_id': 'openai_text_embedding_3_small_1536'},
    {**preview_ok(), 'estimated_chunks': 0}, {**preview_ok(), 'estimated_chunks': True}])
def test_preview_rejection_never_ingests_or_advances_state(setup, tmp_path, monkeypatch, preview):
    ingest, _, _, state, _ = setup
    calls = []
    def api(*args, **kwargs):
        calls.append(args[2])
        return preview
    monkeypatch.setattr(ingest, 'api_json', api)
    with pytest.raises(ingest.FiscalIngestError, match='preview'):
        apply(ingest, plan(setup), state, tmp_path)
    assert calls == ['/api/v1/ingestion/preview'] and state['records'] == {}
    assert not (tmp_path / 'state.json').exists()


def test_preview_error_does_not_ingest(setup, tmp_path, monkeypatch):
    ingest, _, _, state, _ = setup
    def api(*args, **kwargs):
        assert args[2] == '/api/v1/ingestion/preview'
        raise RuntimeError('HTTP 404')
    monkeypatch.setattr(ingest, 'api_json', api)
    with pytest.raises(RuntimeError):
        apply(ingest, plan(setup), state, tmp_path)
    assert state['records'] == {}


def test_changed_joined_history_refreshes_state_and_idempotency_without_export_mutation(setup):
    ingest, manifest, _, state, harvest = setup
    first = plan(setup)[0]
    state['records'][first.logical_document_id] = {'action': 'upsert', 'record_digest_sha256': first.record['record_digest_sha256'],
        'vector_store_file_id': 'file', 'source_text_chunking_profile': STATECIVICS_STATUTE_MARKDOWN_PROFILE,
        'statute_evidence_context_sha256': first.statute_evidence['evidence_context_sha256']}
    assert plan(setup)[0].action == 'noop'
    changed = copy.deepcopy(harvest.documents)
    evidence = next(iter(changed.values()))
    evidence['history_events'][0]['citation_text'] += '; corrected capture'
    evidence['evidence_context_sha256'] = 'c' * 64
    updated = (*setup[:4], StatuteHarvest(harvest.manifest_sha256, changed, harvest.proof))
    second = plan(updated)[0]
    assert second.action == 'upsert' and second.record == first.record
    assert ingest.ingest_idempotency_key('vs', first.record, statute_evidence=first.statute_evidence) != ingest.ingest_idempotency_key('vs', second.record, statute_evidence=second.statute_evidence)
    state['records'][first.logical_document_id].pop('source_text_chunking_profile')
    assert plan(setup)[0].action == 'upsert'


@pytest.mark.parametrize('body', ['', 'History: L. 2024, ch. 59, § 1; Expired, July 1, 2025.'])
def test_excluded_bodies_remove_prior_searchable_version_and_repeat_absent(tmp_path, monkeypatch, body):
    ingest = _load_module()
    path, root, _, text = small_harvest(tmp_path, body=body)
    harvest = preflight_statute_harvest(path, root, expected_manifest_sha256=sha(path.read_bytes()))
    record = _record(ingest, text.encode(), mime_type='text/markdown')
    record.update(artifact_type='statute', citation_url=URL)
    record['record_digest_sha256'] = ingest.record_digest(record)
    manifest = ingest.LoadedManifest(Path('test'), 'a'*64, 1, (record,))
    custody = tmp_path / 'custody'
    _write_custody(custody, record, text.encode())
    state = {'schema_version': 1, 'vector_store_id': 'vs_statutes', 'records': {record['logical_document_id']:
        {'action': 'upsert', 'vector_store_file_id': 'old-file', 'document_id': 'old-doc'}}}
    setup = ingest, manifest, custody, state, harvest
    calls = []
    monkeypatch.setattr(ingest, 'api_json', lambda method, base, path, *a, **k: calls.append((method, path)) or {})
    operations = plan(setup)
    assert operations[0].action == 'remove' and operations[0].content_exclusion
    assert apply(ingest, operations, state, tmp_path)['removed'] == 1
    assert calls == [('DELETE', '/v1/vector_stores/vs_statutes/files/old-file')]
    assert state['records'][record['logical_document_id']]['action'] == 'remove'
    assert plan(setup)[0].action == 'noop'
    assert record['ingestion']['action'] == 'upsert'  # Never rewrite the producer's eligibility decision.


def test_join_and_family_mismatch_fail_before_any_api_effect(setup, tmp_path, monkeypatch):
    ingest, manifest, custody, state, harvest = setup
    monkeypatch.setattr(ingest, 'api_json', lambda *a, **k: pytest.fail('validation reached API'))
    empty = StatuteHarvest(harvest.manifest_sha256, {}, harvest.proof)
    with pytest.raises(ingest.FiscalIngestError, match='reviewed statute harvest'):
        plan((*setup[:4], empty))
    with pytest.raises(ingest.FiscalIngestError, match='reject'):
        plan(setup, source_page_chunking_profile='statecivics_page_markdown_v1')
    with pytest.raises(ingest.FiscalIngestError, match='explicit'):
        ingest.plan_operations(manifest, custody_root=custody, state=state, statute_harvest=harvest)
    with pytest.raises(ingest.FiscalIngestError, match='slug'):
        ingest.load_manifest(manifest.path, source_family='kansas-statutes')
    object_path = _write_custody(custody, manifest.records[0], b'wrong')
    original_path = custody / 'kanview' / manifest.records[0]['content_hash_sha256'][:2] / manifest.records[0]['content_hash_sha256']
    original_path.write_bytes(b'wrong')
    with pytest.raises(ingest.FiscalIngestError, match='hash mismatch'):
        plan(setup)


def test_main_validates_custody_before_store_lookup_or_credentials(setup, tmp_path, monkeypatch):
    ingest, manifest, custody, _, harvest = setup
    args = SimpleNamespace(source_family='kansas-statutes', vector_store_slug='kansas-statutes',
        harvest_manifest=tmp_path/'harvest.json', harvest_root=tmp_path/'corpus', harvest_manifest_sha256=harvest.manifest_sha256,
        allow_create_vector_store=False, apply=True, vector_store_id='vs_statutes', manifest=manifest.path,
        instance_slug='ks-state-civics', state=tmp_path/'state.json', custody_root=custody,
        source_page_chunking_profile=None,
        contract_schema=Path(__file__).parent/'fixtures'/'statecivics-retrieval-export-record.314beafe.json')
    monkeypatch.setattr(ingest, 'parse_args', lambda: args)
    monkeypatch.setattr(ingest, 'default_headers', lambda **k: pytest.fail('read credentials before custody validation'))
    monkeypatch.setattr(ingest, 'ensure_vector_store', lambda **k: pytest.fail('called API before custody validation'))
    for p in custody.rglob('*'):
        if p.is_file(): p.write_bytes(b'wrong')
    with pytest.raises(ingest.FiscalIngestError, match='hash mismatch'):
        ingest.main()
