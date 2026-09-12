"""No-provider integration proof: existing ingestion SQL receives exact slices."""
import asyncio
import json
from types import SimpleNamespace
import pytest

from svs_common import ingestion as ingestion_module
from svs_common.chunking import STATECIVICS_PAGE_MARKDOWN_PROFILE, choose_chunker
from svs_common.hashing import sha256_text
from svs_common.ingestion import IngestionService
from svs_common.schemas import DocumentIngestRequest, Principal
from svs_common.vectorization_router import build_ingestion_plan


def _settings():
    return SimpleNamespace(svs_env='local', is_local_env=True, default_embedding_provider='hash_mock',
                           openai_api_key=None, voyage_api_key=None, cohere_api_key=None, tei_endpoint_url=None,
                           runpod_embedding_endpoint_url=None, infinity_endpoint_url=None)


class _Rows:
    def __init__(self, values=()):
        self.values = values

    def mappings(self):
        return self

    def all(self):
        return list(self.values)

    def first(self):
        return self.values[0] if self.values else None


class _Db:
    def __init__(self, retry=False):
        self.calls = []
        self.retry = retry

    def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params or {}))
        if self.retry and 'SELECT coalesce(max(version_number)' in sql:
            return _Rows([{'next_version': 2}])
        if self.retry and 'SELECT id FROM document_versions' in sql:
            return _Rows([{'id': 'old-version'}])
        return _Rows()


def _request():
    text = '# File-Name\n\n<!-- page 1 -->\n\nFirst café passage.\n<!-- page 2 -->\nSecond page.\n'
    return DocumentIngestRequest(title='mechanics', filename='file.md', content=text, mode='markdown_docs_v1',
                                 source_identity='test-source', attributes={
                                     'source_page_chunking_profile': STATECIVICS_PAGE_MARKDOWN_PROFILE,
                                     'source_collection': 'statecivics-kansas-fiscal-documents',
                                     'source_revision_id': 'test-revision',
                                     'source_content_hash_sha256': sha256_text(text),
                                     'extraction_content_hash_sha256': sha256_text(text), 'source_page_count': 2,
                                 })


def _run(monkeypatch, *, retry=False, evidence_changes=None, statute_request=None):
    principal = Principal(tenant_id='test-tenant', business_instance_id='test-business')
    req = statute_request or _request()
    test_settings = _settings()
    if statute_request is not None:
        test_settings.voyage_api_key = 'test-not-a-real-key'
    if evidence_changes is not None:
        attributes = dict(req.attributes)
        for field, value in evidence_changes.items():
            if value is None:
                attributes.pop(field, None)
            else:
                attributes[field] = value
        req = req.model_copy(update={'attributes': attributes})
    plan = build_ingestion_plan(principal, req, settings=test_settings)
    captured = {'provider_texts': [], 'stored_texts': []}
    service = object.__new__(IngestionService)
    service.object_store = SimpleNamespace(put_text=lambda key, text, mime: captured['stored_texts'].append(text))
    service.qdrant = SimpleNamespace(collection_name=lambda *args: 'test-collection',
                                    settings=SimpleNamespace(svs_sparse_backend='postgres_fts'),
                                    upsert=lambda *args: None)
    service.opensearch = SimpleNamespace(index_name=lambda *args: 'test-index')

    class Provider:
        async def embed(self, texts, model, dimensions, input_type):
            captured['provider_texts'] = list(texts)
            assert input_type == 'document'
            return SimpleNamespace(provider='voyage' if statute_request is not None else 'hash_mock', model=model,
                                   data=[SimpleNamespace(embedding=[0.0] * dimensions) for _ in texts])

    monkeypatch.setattr(ingestion_module, 'provider_for', lambda provider: Provider())
    monkeypatch.setattr(ingestion_module, 'build_ingestion_plan', lambda p, r: build_ingestion_plan(p, r, settings=test_settings))
    monkeypatch.setattr(service, '_find_exact_duplicate', lambda *args: None)
    monkeypatch.setattr(service, '_find_version_target', lambda *args: {'id': 'existing-doc'} if retry else None)
    monkeypatch.setattr(service, '_link_vector_store_file', lambda *args, **kwargs: None)
    monkeypatch.setattr(ingestion_module, 'enqueue_purge_stale_vectors', lambda *args, **kwargs: None)
    db = _Db(retry=retry)
    result = asyncio.run(service.ingest_now(db, principal, req))
    return req, plan, captured, db.calls, result


def test_preview_and_ingestion_sql_use_same_page_chunker_and_exact_coordinates(monkeypatch):
    req, plan, captured, calls, result = _run(monkeypatch)
    chunks = choose_chunker('markdown_docs_v1', attributes=req.attributes)(req.content)
    assert plan.chunker == STATECIVICS_PAGE_MARKDOWN_PROFILE
    assert plan.mode == 'markdown_docs_v1' and plan.embedding_profile_id == 'hash_mock_1536'
    assert plan.estimated_chunks == len(chunks) == 3
    assert captured['provider_texts'] == [chunk.text for chunk in chunks]
    assert captured['stored_texts'] == [req.content, req.content]
    inserted = [params for sql, params in calls if 'INSERT INTO chunks(' in sql]
    assert len(inserted) == len(chunks)
    for params, chunk in zip(inserted, chunks):
        assert params['text'] == req.content[params['char_start']:params['char_end']] == chunk.text
        assert params['page_start'] == params['page_end'] == chunk.page_start
        metadata = json.loads(params['metadata'])
        assert metadata['char_start'] == params['char_start'] and metadata['char_end'] == params['char_end']
        assert metadata['line_start'] == chunk.metadata['line_start']
        assert metadata['extraction_content_hash_sha256'] == sha256_text(req.content)
        assert metadata['source_revision_id'] == 'test-revision'
        assert not {'provision_id', 'appropriation_action_id', 'action_id'} & set(metadata)
    versions = [params for sql, params in calls if 'INSERT INTO document_versions(' in sql]
    assert versions[0]['chunker'] == STATECIVICS_PAGE_MARKDOWN_PROFILE
    assert result.status == 'completed'


def test_same_source_retry_reuses_document_and_creates_a_fresh_version(monkeypatch):
    _, _, _, calls, result = _run(monkeypatch, retry=True)
    assert result.document_id == 'existing-doc'
    assert not any('INSERT INTO documents(' in sql for sql, _ in calls)
    versions = [params for sql, params in calls if 'INSERT INTO document_versions(' in sql]
    assert versions[0]['doc_id'] == 'existing-doc' and versions[0]['version_number'] == 2
    assert versions[0]['chunker'] == STATECIVICS_PAGE_MARKDOWN_PROFILE


@pytest.mark.parametrize('changes', [
    {'source_revision_id': 'new-revision'}, {'source_revision_id': None},
    {'citation_url': 'https://example.invalid/corrected-evidence.pdf'},
    {'extraction_revision_id': 'new-extraction-revision'}, {'source_page_count': None},
])
def test_changed_evidence_context_creates_fresh_version_and_consistent_chunk_metadata(monkeypatch, changes):
    req, _, _, calls, result = _run(monkeypatch, retry=True, evidence_changes=changes)
    assert result.document_id == 'existing-doc'
    version = next(params for sql, params in calls if 'INSERT INTO document_versions(' in sql)
    assert version['version_number'] == 2
    assert json.loads(version['metadata'])['attributes'] == {**req.attributes, 'source_identity': req.source_identity}
    chunks = [json.loads(params['metadata']) for sql, params in calls if 'INSERT INTO chunks(' in sql]
    assert chunks
    for metadata in chunks:
        for field, value in changes.items():
            if value is None:
                assert field not in metadata
            else:
                assert metadata[field] == value
    assert not any("UPDATE document_versions SET metadata" in sql for sql, _ in calls)


@pytest.mark.parametrize('digest', [None, '0' * 64])
def test_missing_or_changed_extraction_hash_fails_before_dedupe_or_provider(monkeypatch, digest):
    service = object.__new__(IngestionService)
    request = _request().model_copy(update={'attributes': {**_request().attributes,
                                                           'extraction_content_hash_sha256': digest}})

    def forbidden(*args, **kwargs):
        pytest.fail('invalid extraction hash reached dedupe or provider')

    monkeypatch.setattr(service, '_find_exact_duplicate', forbidden)
    monkeypatch.setattr(ingestion_module, 'provider_for', forbidden)
    db = _Db()
    with pytest.raises(ValueError, match='SHA-256|hash mismatch'):
        asyncio.run(service.ingest_now(db, Principal(tenant_id='t', business_instance_id='b'), request))
    assert db.calls == []


def test_unchanged_evidence_repeat_deduplicates_without_provider_or_new_version(monkeypatch):
    request = _request()
    expected_context = ingestion_module._page_coordinate_evidence_context(request.attributes)

    class CompleteDb(_Db):
        def execute(self, statement, params=None):
            sql = str(statement)
            if 'FROM documents d' in sql and 'source_evidence_context' in sql:
                self.calls.append((sql, params))
                assert json.loads(params['source_evidence_context']) == expected_context
                assert params['source_identity'] == request.source_identity
                return _Rows([{'id': 'existing-doc', 'current_version_id': 'existing-version'}])
            return super().execute(statement, params)

    def forbidden(*args, **kwargs):
        pytest.fail('unchanged evidence replay must not request embeddings')

    service = object.__new__(IngestionService)
    monkeypatch.setattr(ingestion_module, 'provider_for', forbidden)
    monkeypatch.setattr(service, '_link_vector_store_file', lambda *args, **kwargs: None)
    db = CompleteDb()
    result = asyncio.run(service.ingest_now(db, Principal(tenant_id='t', business_instance_id='b'), request))
    assert result.status == 'deduplicated' and result.document_id == 'existing-doc'
    assert not any('INSERT INTO chunks' in sql or 'INSERT INTO document_versions' in sql for sql, _ in db.calls)


def _retained_statute_request():
    import os
    from pathlib import Path
    configured = os.environ.get('SVS_STATUTE_CORPUS_ROOT')
    if not configured:
        pytest.skip('set SVS_STATUTE_CORPUS_ROOT for retained statute ingestion proof')
    path = Path(configured) / 'data/ksa/ksa_002_003_0003.md'
    assert path.is_file(), 'explicitly required statute corpus is missing'
    text = path.read_bytes().decode('utf-8')
    assert sha256_text(text) == '5501388fc2e8da55cef32d49d15e7f5f14c0b20341d43e9f46d8c4cb381c7d02'
    return DocumentIngestRequest(title='Retained K.S.A. 2-303', filename=path.name, content=text,
        mode='markdown_docs_v1', source_identity='test-only-retained-statute', attributes={
            'source_text_chunking_profile': 'statecivics_statute_markdown_v1',
            'source_collection': 'statecivics-kansas-statutes', 'extraction_content_hash_sha256': sha256_text(text),
            'citation_url': 'https://ksrevisor.gov/statutes/chapters/ch02/002_003_0003.html',
            'source_revision_id': 'test-only-custody-revision',
            'statute_harvest_evidence': {'history_events': [{'ordinal': 1, 'year': 1915, 'chapter': '178', 'section': '3',
                'citation_text': 'L. 1915, ch. 178, § 3', 'resolution_status': 'unresolved'}]},
        })


def test_real_statute_preview_and_ingestion_persist_exact_coordinates_with_provider_double(monkeypatch):
    req, plan, captured, calls, result = _run(monkeypatch, statute_request=_retained_statute_request())
    assert plan.embedding_profile_id == 'voyage_4_docs_1024' and plan.chunker == 'statecivics_statute_markdown_v1'
    inserted = [params for sql, params in calls if 'INSERT INTO chunks(' in sql]
    assert plan.estimated_chunks == len(inserted) == len(captured['provider_texts'])
    for params, expected in zip(inserted, captured['provider_texts']):
        assert params['page_start'] is params['page_end'] is None
        assert params['text'] == expected == req.content[params['char_start']:params['char_end']]
        metadata = json.loads(params['metadata'])
        assert metadata['char_start'] == params['char_start'] and metadata['char_end'] == params['char_end']
        assert metadata['statute_harvest_evidence'] == req.attributes['statute_harvest_evidence']
        assert metadata['source_revision_id'] == 'test-only-custody-revision'
    version = next(params for sql, params in calls if 'INSERT INTO document_versions(' in sql)
    assert version['embedding_profile_id'] == 'voyage_4_docs_1024' and version['chunker'] == plan.chunker
    assert result.status == 'completed'


def test_unconfigured_statute_provider_fails_before_dedupe_writes_or_provider(monkeypatch):
    req = _retained_statute_request()
    service = object.__new__(IngestionService)
    monkeypatch.setattr(ingestion_module, 'build_ingestion_plan', lambda p, r: build_ingestion_plan(p, r, settings=_settings()))
    def forbidden(*args, **kwargs):
        pytest.fail('unconfigured statute route reached dedupe/write/provider')
    monkeypatch.setattr(service, '_find_exact_duplicate', forbidden)
    monkeypatch.setattr(ingestion_module, 'provider_for', forbidden)
    db = _Db()
    with pytest.raises(ValueError, match='fallback is forbidden'):
        asyncio.run(service.ingest_now(db, Principal(tenant_id='t', business_instance_id='b'), req))
    assert db.calls == []


def test_changed_statute_harvest_context_creates_new_version_with_same_exact_text(monkeypatch):
    request = _retained_statute_request()
    changed = {'history_events': [], 'response_hash_basis': 'decoded_response_text_reencoded_utf8'}
    req, _, _, calls, result = _run(monkeypatch, retry=True, statute_request=request,
                                   evidence_changes={'statute_harvest_evidence': changed})
    assert result.document_id == 'existing-doc'
    version = next(params for sql, params in calls if 'INSERT INTO document_versions(' in sql)
    assert version['version_number'] == 2
    assert json.loads(version['metadata'])['attributes']['statute_harvest_evidence'] == changed
    chunks = [json.loads(params['metadata']) for sql, params in calls if 'INSERT INTO chunks(' in sql]
    assert chunks and all(c['statute_harvest_evidence'] == changed for c in chunks)
    assert req.content == request.content


def test_unchanged_statute_context_deduplicates_without_provider_or_new_version(monkeypatch):
    request = _retained_statute_request()
    settings = _settings()
    settings.voyage_api_key = 'test-not-real'
    service = object.__new__(IngestionService)
    monkeypatch.setattr(ingestion_module, 'build_ingestion_plan', lambda p, r: build_ingestion_plan(p, r, settings=settings))
    monkeypatch.setattr(service, '_link_vector_store_file', lambda *args, **kwargs: None)
    monkeypatch.setattr(ingestion_module, 'provider_for', lambda *args: pytest.fail('deduplicated statute called provider'))
    class CompleteDb(_Db):
        def execute(self, statement, params=None):
            if 'FROM documents d' in str(statement) and 'source_evidence_context' in str(statement):
                self.calls.append((str(statement), params))
                assert params['source_embedding_profile'] == 'voyage_4_docs_1024'
                assert json.loads(params['source_evidence_context']) == ingestion_module._page_coordinate_evidence_context(request.attributes)
                return _Rows([{'id': 'existing-doc', 'current_version_id': 'retained-version'}])
            return super().execute(statement, params)
    db = CompleteDb()
    result = asyncio.run(service.ingest_now(db, Principal(tenant_id='t', business_instance_id='b'), request))
    assert result.status == 'deduplicated'
    assert not any('INSERT INTO document_versions' in sql or 'INSERT INTO chunks' in sql for sql, _ in db.calls)
