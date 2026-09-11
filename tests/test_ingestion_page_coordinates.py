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


def _run(monkeypatch, *, retry=False, evidence_changes=None):
    principal = Principal(tenant_id='test-tenant', business_instance_id='test-business')
    req = _request()
    if evidence_changes is not None:
        attributes = dict(req.attributes)
        for field, value in evidence_changes.items():
            if value is None:
                attributes.pop(field, None)
            else:
                attributes[field] = value
        req = req.model_copy(update={'attributes': attributes})
    plan = build_ingestion_plan(principal, req, settings=_settings())
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
            return SimpleNamespace(provider='hash_mock', model=model,
                                   data=[SimpleNamespace(embedding=[0.0] * dimensions) for _ in texts])

    monkeypatch.setattr(ingestion_module, 'provider_for', lambda provider: Provider())
    monkeypatch.setattr(ingestion_module, 'build_ingestion_plan', lambda p, r: build_ingestion_plan(p, r, settings=_settings()))
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
