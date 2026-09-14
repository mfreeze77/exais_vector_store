"""Candidate API → real adapter → index calls; providers/index are test doubles."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from svs_common.qdrant_adapter import QdrantAdapter
from svs_common.statecivics_entity_store import (
    CandidateEntityStore, CandidateStorageError, canonical, digest_record,
    validate_candidate_manifest,
)
from svs_common.statecivics_record_adapter import EntityCollectionCollision
from svs_api import statecivics_candidates as routes

ROOT = Path(__file__).resolve().parents[1]
PRINCIPAL = SimpleNamespace(tenant_id='ten_ks_state_civics', business_instance_id='biz_ks_state_civics', scopes=['documents:write', 'retrieval:read'])


def manifest(records):
    body = ''.join(canonical(r) + '\n' for r in records)
    return body, hashlib.sha256(body.encode()).hexdigest()


@pytest.fixture
def records():
    path = ROOT / 'tests/fixtures/statecivics-ks600-a2-1-entities-candidates.677d126d.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    for row in rows:
        if row['entity_type'] == 'appropriation_action':
            row['entity']['amount_kind'] = 'no_limit'
        row['record_digest_sha256'] = digest_record(row)
    return rows


class Index:
    def __init__(self):
        self.points = {}
        self.names = set()
        self.writes = 0
        self.damage_readback = False

    def get_collections(self):
        return SimpleNamespace(collections=[SimpleNamespace(name=n) for n in self.names])

    def create_collection(self, collection_name, vectors_config):
        self.names.add(collection_name)

    def retrieve(self, collection_name, ids, with_payload):
        return [SimpleNamespace(id=id, payload=copy.deepcopy(self.points[(collection_name, id)]))
                for id in ids if (collection_name, id) in self.points]

    def upsert(self, collection_name, points, wait):
        assert wait is True
        self.writes += 1
        for p in points:
            self.points[(collection_name, str(p.id))] = copy.deepcopy(p.payload)
        if self.damage_readback:
            self.points[(collection_name, str(points[0].id))]['manifest_sha256'] = 'wrong'


@pytest.fixture
def store():
    adapter = QdrantAdapter.__new__(QdrantAdapter)
    adapter.settings = SimpleNamespace(qdrant_collection_prefix='svs_', svs_index_version='', svs_index_strict=True)
    adapter.client = Index()
    calls = []
    def embed(value, input_type='document'):
        calls.append((value, input_type))
        return [1.0] * 1536
    result = CandidateEntityStore(adapter=adapter, embed=embed)
    result.embedding_calls = calls
    return result


def test_apply_reads_back_exact_records_and_repeat_does_not_embed_or_write(records, store):
    body, sha = manifest(records)
    admitted = validate_candidate_manifest(body, sha, path='candidate')
    plan = store.ingest(admitted, principal=PRINCIPAL, manifest_sha256=sha, apply=False)
    assert plan['applied'] is False
    assert not store.embedding_calls and not store.adapter.client.points
    first = store.ingest(admitted, principal=PRINCIPAL, manifest_sha256=sha, apply=True)
    assert first['written'] == first['embedded'] == len(records)
    assert first['collection'] not in (
        'svs_biz_ks_state_civics_voyage_4_docs_1024',
        'svs_biz_ks_state_civics_openai_text_embedding_3_small_1536',
    )
    assert len(store.adapter.client.points) == len(records)
    for record in records:
        assert store.adapter.client.points[(first['collection'], store.point_id(record))]['entity_record'] == record
    second = store.ingest(admitted, principal=PRINCIPAL, manifest_sha256=sha, apply=True)
    assert second['unchanged'] == len(records)
    assert second['written'] == second['embedded'] == 0
    assert len(store.embedding_calls) == len(records)
    assert store.adapter.client.writes == 1


def test_readback_failure_cannot_report_success(records, store):
    store.adapter.client.damage_readback = True
    with pytest.raises(CandidateStorageError, match='readback differs'):
        store.ingest(records, principal=PRINCIPAL, manifest_sha256='a'*64, apply=True)


def test_a_profile_absent_from_sources_but_in_runtime_registry_is_also_protected(records, store):
    store.policy['candidate_index_profile'] = 'hash_mock_1536'
    with pytest.raises(EntityCollectionCollision):
        store.ingest(records, principal=PRINCIPAL, manifest_sha256='a'*64, apply=True)
    assert not store.embedding_calls and not store.adapter.client.points


def test_stale_revision_and_contradictory_same_revision_refuse_before_embedding(records, store):
    store.ingest(records, principal=PRINCIPAL, manifest_sha256='a'*64, apply=True)
    before = len(store.embedding_calls)
    older = copy.deepcopy(records)
    for r in older:
        r['entity_revision'] = 1
        r['entity']['revision' if r['entity_type'] == 'appropriation_action' else 'provision_reference_revision'] = 1
    with pytest.raises(CandidateStorageError, match='older than'):
        store.ingest(older, principal=PRINCIPAL, manifest_sha256='b'*64, apply=True)
    changed = copy.deepcopy(records)
    changed[0]['entity']['status'] = 'candidate'
    changed[0]['entity']['conditions'] = ['different row']
    with pytest.raises(CandidateStorageError, match='contradictory payloads'):
        store.ingest(changed, principal=PRINCIPAL, manifest_sha256='b'*64, apply=True)
    assert len(store.embedding_calls) == before


def test_search_uses_authenticated_scope_and_returns_stored_citation(records, store):
    store.ingest(records, principal=PRINCIPAL, manifest_sha256='a'*64, apply=True)
    def search(collection, vector, filters, limit):
        assert filters['must'] == [
            {'key': 'tenant_id', 'match': {'value': PRINCIPAL.tenant_id}},
            {'key': 'business_instance_id', 'match': {'value': PRINCIPAL.business_instance_id}},
            {'key': 'entity_path', 'match': {'value': 'candidate'}},
        ]
        return [{'id': id, 'score': 0.9, 'payload': payload}
                for (name, id), payload in store.adapter.client.points.items() if name == collection]
    store.adapter.search = search
    hits = store.search('Nurse fair treatment and recovery fund', principal=PRINCIPAL)['results']
    assert {h['record']['record_digest_sha256'] for h in hits} == {r['record_digest_sha256'] for r in records}
    assert store.embedding_calls[-1][1] == 'query'
    wrong = SimpleNamespace(tenant_id='other', business_instance_id=PRINCIPAL.business_instance_id)
    with pytest.raises(CandidateStorageError, match='authenticated principal'):
        store.search('query', principal=wrong)


@pytest.fixture
def client(monkeypatch, store):
    db = SimpleNamespace(execute=lambda *a, **kw: None, commit=lambda: None, rollback=lambda: None)
    monkeypatch.setattr(routes, 'get_settings', lambda: SimpleNamespace(svs_entity_candidate_enabled=True))
    monkeypatch.setattr(routes, 'CandidateEntityStore', lambda: store)
    app = FastAPI()
    app.include_router(routes.candidate_router(lambda: PRINCIPAL, lambda: db))
    return TestClient(app)


def test_api_writes_then_retrieves_through_real_adapter(records, client, store):
    body, sha = manifest(records)
    response = client.post('/api/v1/statecivics/entities/ingest', json={
        'manifest': body, 'manifest_sha256': sha, 'path': 'candidate', 'apply': True,
    })
    assert response.status_code == 200, response.text
    assert response.json()['written'] == len(records)
    assert store.adapter.client.writes == 1
    store.adapter.search = lambda collection, vector, filters, limit: [
        {'id': id, 'score': 0.9, 'payload': payload}
        for (name, id), payload in store.adapter.client.points.items() if name == collection
    ]
    found = client.post('/api/v1/statecivics/entities/candidate/search', json={'query': 'Nurse fund'})
    assert found.status_code == 200
    assert {hit['record']['record_digest_sha256'] for hit in found.json()['results']} == {
        r['record_digest_sha256'] for r in records
    }


def test_operator_command_submits_the_exact_manifest_to_the_candidate_api(records, client, monkeypatch, tmp_path):
    import importlib.util
    import sys
    release = ROOT / 'scripts/release'
    monkeypatch.syspath_prepend(str(release))
    spec = importlib.util.spec_from_file_location('candidate_operator_test', release / 'kansas-fiscal-document-ingest.py')
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    body, sha = manifest(records)
    path = tmp_path / 'candidate.jsonl'
    path.write_text(body)
    monkeypatch.setattr(sys, 'argv', [str(release / 'kansas-fiscal-document-ingest.py'),
        '--record-kind', 'entity', '--entity-path', 'candidate', '--apply',
        '--manifest', str(path), '--contract-schema', str(ROOT / 'configs/statecivics-contracts/retrieval-export-record.schema.json'),
        '--custody-root', str(tmp_path), '--state', str(tmp_path / 'state.json'), '--api', 'http://test',
    ])
    calls = []
    def api(method, base, endpoint, payload, **kwargs):
        calls.append(endpoint)
        assert payload['manifest'] == body and payload['manifest_sha256'] == sha
        response = client.post(endpoint, json=payload)
        assert response.status_code == 200, response.text
        assert response.json()['written'] == len(records)
        return response.json()
    monkeypatch.setattr(module, 'api_json', api)
    monkeypatch.setattr(module, 'default_headers', lambda **kwargs: {})
    assert module.main() == 0
    assert calls == ['/api/v1/statecivics/entities/ingest']


@pytest.mark.parametrize('failure', ['live', 'digest', 'payload', 'amount_kind'])
def test_api_refusals_happen_before_backend_construction(records, client, monkeypatch, failure):
    if failure == 'payload':
        next(r for r in records if r['entity_type'] == 'appropriation_action')['entity']['source']['source_url'] = 'not a URI'
    if failure == 'amount_kind':
        next(r for r in records if r['entity_type'] == 'appropriation_action')['entity'].pop('amount_kind')
    if failure in ('payload', 'amount_kind'):
        for r in records:
            r['record_digest_sha256'] = digest_record(r)
    body, sha = manifest(records)
    def forbidden():
        raise AssertionError('backend constructed before record refusal')
    monkeypatch.setattr(routes, 'CandidateEntityStore', forbidden)
    response = client.post('/api/v1/statecivics/entities/ingest', json={
        'manifest': body, 'manifest_sha256': '0'*64 if failure == 'digest' else sha,
        'path': 'live' if failure == 'live' else 'candidate', 'apply': True,
    })
    assert response.status_code == 422, response.text
    if failure == 'live':
        assert response.json()['detail']['error'] == 'CandidateRecordRefused'
