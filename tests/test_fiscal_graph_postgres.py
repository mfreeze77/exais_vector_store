"""Real SQL/RLS proof; explicit disposable DB only, every fixture rolled back.

Synthetic reviewed_public declarations test the runtime; they do not assert
that any real Kansas source has received canonical review.
"""
import asyncio
import json
import os
from uuid import uuid4

import pytest
import yaml
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from svs_api import main as api
from svs_common.db import set_rls_context
from svs_common.fiscal_graph import FISCAL_RELATIONS, expand_fiscal_graph, fiscal_edge_id, fiscal_node_id, guard_fiscal_graph_generation, validate_fiscal_graph_bindings
from svs_common.retrieval import RetrievalService
from svs_common.schemas import Principal, VectorStoreGraphLoadRequest, SearchResponse, OpenAIVectorStoreSearchRequest
from fiscal_graph_test_support import graph_payload, chunk_for_node
from test_fiscal_graph_routes import ATTRS, profile_payload

TEST_URL = os.getenv('SVS_FISCAL_GRAPH_TEST_DATABASE_URL')
pytestmark = pytest.mark.skipif(not TEST_URL, reason='requires explicitly disposable SVS_FISCAL_GRAPH_TEST_DATABASE_URL')


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    engine = create_engine(TEST_URL)
    with engine.connect() as connection:
        outer = connection.begin()
        db = Session(bind=connection, join_transaction_mode='create_savepoint')
        try:
            suffix = uuid4().hex
            scope = dict(tenant=f't_{suffix}', business=f'b_{suffix}', store=f'vs_{suffix}', kb=f'kb_{suffix}')
            for sql in (
                "INSERT INTO tenants(id,name,slug) VALUES (:tenant,'Synthetic fiscal test',:tenant)",
                "INSERT INTO business_instances(id,tenant_id,name,slug) VALUES (:business,:tenant,'Synthetic fiscal test',:business)",
                "INSERT INTO knowledge_bases(id,tenant_id,business_instance_id,name,slug,security_level) VALUES (:kb,:tenant,:business,'Synthetic fiscal test',:kb,0)",
                "INSERT INTO vector_stores(id,tenant_id,business_instance_id,knowledge_base_id,name,attributes) VALUES (:store,:tenant,:business,:kb,'Synthetic fiscal test',CAST(:attrs AS jsonb))",
            ):
                db.execute(text(sql), {**scope, 'attrs': json.dumps(ATTRS)})
            principal = Principal(tenant_id=scope['tenant'], business_instance_id=scope['business'], max_security_level=0, scopes=['vector_stores:write', 'retrieval:read'])
            payload = graph_payload(scope['store'], run_id=ATTRS['fiscal_graph_derivation_run_id'])
            payload['dry_run'] = False
            for node in payload['nodes']:
                attrs = node['attributes']
                chunk = chunk_for_node(node)
                file_attrs = dict(source_collection='statecivics-kansas-fiscal-documents', logical_document_id=attrs['fiscal_logical_document_id'], source_revision_id=attrs['fiscal_source_revision_id'], source_content_hash_sha256=attrs['fiscal_source_content_hash_sha256'], fiscal_year=2026)
                params = {**scope, 'document': chunk.document_id, 'version': chunk.document_version_id, 'chunk': chunk.id, 'attrs': json.dumps(file_attrs), 'text': chunk.text}
                for sql in (
                    "INSERT INTO documents(id,tenant_id,business_instance_id,knowledge_base_id,vector_store_id,title,content_hash,security_level,classification,current_version_id) VALUES (:document,:tenant,:business,:kb,:store,'Synthetic fiscal evidence','hash',0,'public',:version)",
                    "INSERT INTO document_versions(id,document_id,tenant_id,business_instance_id,version_number,parser_profile_id,vectorization_profile_id,embedding_profile_id,chunking_profile_id,source_content_hash) VALUES (:version,:document,:tenant,:business,1,'test','test','test','test','hash')",
                    "INSERT INTO chunks(id,tenant_id,business_instance_id,knowledge_base_id,vector_store_id,document_id,document_version_id,ordinal,text,text_hash,security_level,classification) VALUES (:chunk,:tenant,:business,:kb,:store,:document,:version,0,:text,'hash',0,'public')",
                    "INSERT INTO vector_store_files(id,tenant_id,business_instance_id,vector_store_id,document_id,status,attributes) VALUES (:chunk,:tenant,:business,:store,:document,'completed',CAST(:attrs AS jsonb))",
                ):
                    db.execute(text(sql), params)
            set_rls_context(db, principal)
            db.execute(text('SET LOCAL ROLE svs_app'))
            assert tuple(db.execute(text('SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user')).one()) == (False, False)
            path = tmp_path / 'profile.yaml'
            path.write_text(yaml.safe_dump(profile_payload(principal, scope['store'])))
            monkeypatch.setenv('SVS_CELL_GRAPH_PROFILE_PATH', str(path))
            monkeypatch.setattr(api, 'enforce_rate_limit', lambda *a: None)
            result = api.load_vector_store_graph(scope['store'], VectorStoreGraphLoadRequest(**payload), principal, db)
            assert result['loaded_nodes'] == 6 and result['loaded_edges'] == 5
            yield dict(db=db, principal=principal, store=scope['store'], payload=payload, profile=path)
        finally:
            db.close()
            outer.rollback()
    engine.dispose()


def expand(corpus, seed=0, relations=FISCAL_RELATIONS, filters=None, principal=None, store=None, run=None):
    principal = principal or corpus['principal']
    set_rls_context(corpus['db'], principal)
    return expand_fiscal_graph(corpus['db'], principal, store or corpus['store'],
        [chunk_for_node(corpus['payload']['nodes'][seed])],
        derivation_run_id=run or ATTRS['fiscal_graph_derivation_run_id'],
        filters=filters or {}, relation_types=relations, limit=3,
        hydrate=RetrievalService.__new__(RetrievalService)._hydrate_and_acl)


@pytest.mark.parametrize('relation,seed,target', [
    ('contains_appropriation', 0, 1), ('targets_account', 1, 2),
    ('account_of_agency', 2, 3), ('account_in_fund', 2, 4), ('documented_by', 1, 5),
])
def test_complete_five_relation_chain_with_original_citations(corpus, relation, seed, target):
    additions, metadata, summary = expand(corpus, seed, (relation,))
    expected = chunk_for_node(corpus['payload']['nodes'][target])
    assert [c.id for c in additions] == [expected.id]
    assert additions[0].citation['file_id'] == expected.document_id
    assert metadata[expected.id]['relationships'][0]['relation_type'] == relation
    assert summary['inserted_chunk_count'] == 1
    reverse, reverse_meta, _ = expand(corpus, target, (relation,))
    assert reverse[0].id == chunk_for_node(corpus['payload']['nodes'][seed]).id
    assert reverse_meta[reverse[0].id]['relationships'][0]['source_node_id'] == metadata[expected.id]['relationships'][0]['source_node_id']


@pytest.mark.parametrize('mutation', [
    "UPDATE vector_store_files SET attributes=jsonb_set(attributes,'{source_content_hash_sha256}','\"stale\"') WHERE id=:id",
    "UPDATE vector_store_files SET attributes=jsonb_set(attributes,'{source_collection}','\"other\"') WHERE id=:id",
    "UPDATE vector_store_files SET attributes=jsonb_set(attributes,'{source_revision_id}','\"wrong\"') WHERE id=:id",
    "UPDATE vector_store_files SET status='cancelled' WHERE id=:id",
    "UPDATE documents SET status='deleted' WHERE id=:doc",
    "UPDATE documents SET current_version_id=NULL WHERE id=:doc",
    "UPDATE chunks SET active=false WHERE id=:id",
    "UPDATE chunks SET security_level=1,classification='private' WHERE id=:id",
    "UPDATE chunks SET allowed_groups=ARRAY['denied'] WHERE id=:id",
    "UPDATE chunks SET allowed_roles=ARRAY['denied'] WHERE id=:id",
])
@pytest.mark.parametrize('index', [0, 1])
def test_stale_withdrawn_or_denied_endpoint_never_returns_metadata(corpus, mutation, index):
    chunk = chunk_for_node(corpus['payload']['nodes'][index])
    # Simulate a privileged source withdrawal, then query as restricted svs_app.
    corpus['db'].execute(text('RESET ROLE'))
    corpus['db'].execute(text(mutation), {'id': chunk.id, 'doc': chunk.document_id})
    corpus['db'].execute(text('SET LOCAL ROLE svs_app'))
    additions, metadata, summary = expand(corpus, relations=('contains_appropriation',))
    assert additions == [] and metadata == {}


@pytest.mark.parametrize('filters', [
    {'file_attribute_filters': {'fiscal_year': 2025}},
    {'file_attribute_ranges': [{'key': 'fiscal_year', 'op': 'gte', 'value': 2027}]},
    {'file_attribute_not_any': [{'key': 'fiscal_year', 'values': [2026]}]},
    {'file_attribute_not_filters': [{'key': 'fiscal_year', 'value': 2026}]},
    {'document_id': 'doc_other'},
])
def test_result_filters_cannot_leak_relationship_metadata(corpus, filters):
    assert expand(corpus, relations=('contains_appropriation',), filters=filters)[:2] == ([], {})


def test_matching_numeric_range_and_negative_filter(corpus):
    additions, _, _ = expand(corpus, relations=('contains_appropriation',), filters={
        'file_attribute_ranges': [{'key': 'fiscal_year', 'op': 'gte', 'value': 2025}],
        'file_attribute_not_filters': [{'key': 'fiscal_year', 'value': 2027}],
    })
    assert len(additions) == 1


def load_new(corpus, payload):
    payload['dry_run'] = False
    return api.load_vector_store_graph(corpus['store'], VectorStoreGraphLoadRequest(**payload), corpus['principal'], corpus['db'])


def test_third_supporting_citation_requires_current_source_and_acl(corpus):
    run = str(uuid4())
    payload = graph_payload(corpus['store'], run_id=run)
    edge = payload['edges'][0]
    edge['attributes']['evidence_citation_ids'] = [payload['nodes'][5]['attributes']['fiscal_source_span_id']]
    edge['id'] = fiscal_edge_id(corpus['store'], edge['type'], edge['source'], edge['target'], edge['attributes'])
    load_new(corpus, payload)
    assert len(expand(corpus, run=run, relations=('contains_appropriation',))[0]) == 1
    support = chunk_for_node(payload['nodes'][5])
    corpus['db'].execute(text("UPDATE vector_store_files SET attributes=jsonb_set(attributes,'{fiscal_year}','2025') WHERE id=:id"), {'id': support.id})
    assert len(expand(corpus, run=run, relations=('contains_appropriation',), filters={'file_attribute_filters': {'fiscal_year': 2026}})[0]) == 1
    corpus['db'].execute(text("UPDATE chunks SET allowed_groups=ARRAY['denied'] WHERE id=:id"), {'id': support.id})
    assert expand(corpus, run=run, relations=('contains_appropriation',))[:2] == ([], {})


@pytest.mark.parametrize('same_chunk', [True, False])
def test_multiple_entities_on_same_document_preserve_exact_chunks(corpus, same_chunk):
    run = str(uuid4())
    payload = graph_payload(corpus['store'], run_id=run)
    source, target = payload['nodes'][:2]
    source_chunk, target_chunk = chunk_for_node(source), chunk_for_node(target)
    previous_id = target['id']
    for key in ('fiscal_logical_document_id', 'fiscal_source_revision_id', 'fiscal_source_content_hash_sha256'):
        target['attributes'][key] = source['attributes'][key]
    if same_chunk:
        target['attributes']['fiscal_chunk_id'] = source_chunk.id
    else:
        corpus['db'].execute(text('UPDATE chunks SET document_id=:document,document_version_id=:version,ordinal=1 WHERE id=:id'),
                             {'id': target_chunk.id, 'document': source_chunk.document_id, 'version': source_chunk.document_version_id})
    target['id'] = fiscal_node_id(corpus['store'], target['type'], target['attributes'])
    for edge in payload['edges']:
        for endpoint in ('source', 'target'):
            if edge[endpoint] == previous_id:
                edge[endpoint] = target['id']
        edge['id'] = fiscal_edge_id(corpus['store'], edge['type'], edge['source'], edge['target'], edge['attributes'])
    load_new(corpus, payload)
    additions, metadata, _ = expand(corpus, run=run, relations=('contains_appropriation',))
    assert len(additions) == (0 if same_chunk else 1)
    assert metadata[source_chunk.id]['relationships'][0]['relation_type'] == 'contains_appropriation'
    if not same_chunk:
        assert additions[0].id == target_chunk.id
        assert additions[0].document_id == source_chunk.document_id


def test_load_binding_rechecks_each_node_even_shared_chunk(corpus):
    payload = graph_payload(corpus['store'], run_id=str(uuid4()))
    source, target = payload['nodes'][:2]
    target['attributes']['fiscal_chunk_id'] = source['attributes']['fiscal_chunk_id']
    # Exact source hashes still describe different files: shared chunk is not enough.
    with pytest.raises(ValueError, match='bindings'):
        validate_fiscal_graph_bindings(corpus['db'], corpus['principal'], corpus['store'], VectorStoreGraphLoadRequest(**payload),
            hydrate=RetrievalService.__new__(RetrievalService)._hydrate_and_acl)


def test_run_and_scope_isolation(corpus):
    assert expand(corpus, run=str(uuid4()))[:2] == ([], {})
    assert expand(corpus, store='vs_other')[:2] == ([], {})
    other = corpus['principal'].model_copy(update={'business_instance_id': 'other'})
    assert expand(corpus, principal=other)[:2] == ([], {})


def test_immutable_replay_and_separate_generation(corpus):
    req = VectorStoreGraphLoadRequest(**corpus['payload'])
    guard_fiscal_graph_generation(corpus['db'], corpus['principal'], corpus['store'], req)
    changed = req.model_copy(deep=True)
    changed.nodes[0].label = 'Changed assertion'
    with pytest.raises(ValueError, match='different content'):
        guard_fiscal_graph_generation(corpus['db'], corpus['principal'], corpus['store'], changed)
    new_run = str(uuid4())
    new = graph_payload(corpus['store'], run_id=new_run)
    new['dry_run'] = False
    result = api.load_vector_store_graph(corpus['store'], VectorStoreGraphLoadRequest(**new), corpus['principal'], corpus['db'])
    assert result['nodes'] == 12 and result['edges'] == 10
    coverage = api._graph_coverage_for_vector_store(corpus['db'], corpus['principal'], corpus['store'], derivation_run_id=new_run)
    assert coverage['node_count'] == 6 and coverage['edge_count'] == 5


def test_search_route_with_real_graph_sql(corpus, monkeypatch):
    async def search(db, principal, req):
        # Offline seed avoids an external embedding provider; graph SQL and
        # file lookup/citations/ACL and API dispatch remain real.
        return SearchResponse(query=req.query, results=[chunk_for_node(corpus['payload']['nodes'][0])])
    monkeypatch.setattr(api.retrieval, 'search', search)
    request = OpenAIVectorStoreSearchRequest(query='synthetic appropriation', lens='fiscal_relationships', inputs={'derivation_run_id': ATTRS['fiscal_graph_derivation_run_id']})
    page = asyncio.run(api._openai_vector_store_search_page(corpus['store'], request, corpus['principal'], corpus['db']))
    assert page['graph_expansion']['inserted_chunk_count'] == 1
    assert page['graph_expansion']['annotated_result_count'] == 2
    assert len(page['data']) == 2
