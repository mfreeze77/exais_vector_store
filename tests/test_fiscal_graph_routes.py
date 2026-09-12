"""State Civics fiscal route isolation; all evidence here is synthetic."""
import asyncio
from uuid import uuid4

import pytest
import yaml
from fastapi import HTTPException
from svs_api import main as api
from svs_common.cell_graph import cell_graph_profile_for_store
from svs_common.fiscal_graph import FISCAL_CORPUS_KIND, FISCAL_GRAPH_HANDLER_ID, FISCAL_PROFILE_ID
from svs_common.openai_compat import OpenAICompatError
from svs_common.schemas import OpenAIVectorStoreSearchRequest, Principal, SearchResponse, VectorStoreGraphLoadRequest
from svs_common.search_lenses import search_lenses_for_vector_store
from fiscal_graph_test_support import graph_payload, chunk_for_node
from test_grant_cell_graph import Db

STORE = 'vs_fiscal_test'
RUN = str(uuid4())
ATTRS = {'corpus': FISCAL_CORPUS_KIND, 'graph_profile_id': FISCAL_PROFILE_ID, 'fiscal_graph_derivation_run_id': RUN}
PRINCIPAL = Principal(tenant_id='ten_ks_state_civics', business_instance_id='biz_ks_state_civics', max_security_level=0, scopes=['retrieval:read'])


def profile_payload(principal=PRINCIPAL, store=STORE, enabled=True):
    return dict(schema_version='svs.cell-graph.v1', profile_id=FISCAL_PROFILE_ID,
                handler_id=FISCAL_GRAPH_HANDLER_ID, corpus_kind=FISCAL_CORPUS_KIND,
                binding=dict(tenant_id=principal.tenant_id, business_instance_id=principal.business_instance_id, vector_store_ids=[store]),
                enabled=enabled, max_expansions=3, max_hops=1)


@pytest.fixture
def setup_route(monkeypatch, tmp_path):
    path = tmp_path / 'profile.yaml'
    path.write_text(yaml.safe_dump(profile_payload()))
    monkeypatch.setenv('SVS_CELL_GRAPH_PROFILE_PATH', str(path))
    monkeypatch.setattr(api, '_refresh_vector_store_activity_or_404', lambda *a: None)
    monkeypatch.setattr(api, '_vector_store_attributes_for_search', lambda *a: ATTRS)
    monkeypatch.setattr(api, '_graph_coverage_for_vector_store', lambda *a, **kw: {'node_count': 6, 'edge_count': 5})
    monkeypatch.setattr(api, '_vector_store_file_lookup', lambda db, p, s, ids: {i: {'file_id': i} for i in ids})
    async def search(db, p, req):
        return SearchResponse(query=req.query, results=[chunk_for_node(graph_payload()['nodes'][0])])
    monkeypatch.setattr(api.retrieval, 'search', search)
    return path


def request(**kwargs):
    return OpenAIVectorStoreSearchRequest(query='appropriation supporting budget', lens='fiscal_relationships', inputs={'derivation_run_id': RUN}, **kwargs)


def test_fiscal_dispatch_preserves_filters_and_is_explicit(setup_route, monkeypatch):
    calls = []
    def expand(*a, **kw):
        calls.append(kw)
        return [], {}, {'applied': False}
    monkeypatch.setattr(api, 'expand_fiscal_graph', expand)
    page = asyncio.run(api._openai_vector_store_search_page(STORE, request(filters={'fiscal_year': 2026}).bind_graph_expansion_limit(10), PRINCIPAL, Db()))
    assert calls[0]['derivation_run_id'] == RUN
    assert calls[0]['filters'] == {'vector_store_id': STORE, 'file_attribute_filters': {'fiscal_year': 2026}}
    assert calls[0]['limit'] == 3
    assert page['graph_expansion']['cell_profile_id'] == FISCAL_PROFILE_ID
    assert page['search_lens']['source'] == 'explicit'


@pytest.mark.parametrize('lens', [None, 'semantic'])
def test_semantic_independent_even_with_invalid_graph_config(setup_route, monkeypatch, lens):
    setup_route.write_text('invalid: [')
    monkeypatch.setattr(api, 'expand_fiscal_graph', lambda *a, **kw: pytest.fail('implicit fiscal expansion'))
    page = asyncio.run(api._openai_vector_store_search_page(STORE, OpenAIVectorStoreSearchRequest(query='law and money', lens=lens), PRINCIPAL, Db()))
    assert 'graph_expansion' not in page


@pytest.mark.parametrize('inputs', [{}, {'derivation_run_id': str(uuid4())}, {'derivation_run_id': RUN, 'unexpected': True}, {'derivation_run_id': RUN, 'relationship': 'payment'}])
def test_bad_selector_rejected_before_retrieval(setup_route, monkeypatch, inputs):
    monkeypatch.setattr(api.retrieval, 'search', lambda *a: pytest.fail('invalid input reached retrieval'))
    req = request().model_copy(update={'inputs': inputs})
    with pytest.raises(OpenAICompatError):
        asyncio.run(api._openai_vector_store_search_page(STORE, req, PRINCIPAL, Db()))


def test_run_withdrawal_during_retrieval_refused(setup_route, monkeypatch):
    async def search(*a):
        monkeypatch.setattr(api, '_vector_store_attributes_for_search', lambda *a: {**ATTRS, 'fiscal_graph_derivation_run_id': str(uuid4())})
        return SearchResponse(query='test', results=[])
    monkeypatch.setattr(api.retrieval, 'search', search)
    monkeypatch.setattr(api, 'expand_fiscal_graph', lambda *a, **kw: pytest.fail('withdrawn run expanded'))
    with pytest.raises(OpenAICompatError, match='currently served'):
        asyncio.run(api._openai_vector_store_search_page(STORE, request(), PRINCIPAL, Db()))


@pytest.mark.parametrize('mismatch', ['tenant', 'business', 'store', 'corpus', 'profile'])
def test_exact_cell_and_store_binding(setup_route, mismatch):
    principal, store, attrs = PRINCIPAL, STORE, dict(ATTRS)
    if mismatch in {'tenant', 'business'}:
        principal = principal.model_copy(update={('tenant_id' if mismatch == 'tenant' else 'business_instance_id'): 'other'})
    elif mismatch == 'store':
        store = 'vs_other'
    else:
        attrs['corpus' if mismatch == 'corpus' else 'graph_profile_id'] = 'other'
    assert cell_graph_profile_for_store(principal, store, attrs) is None


def test_lens_does_not_appear_in_other_cells():
    for corpus in ('grant_intelligence', 'kansas_court_decisions', 'topeka_municipal_code', 'unknown'):
        assert 'fiscal_relationships' not in {x['id'] for x in search_lenses_for_vector_store({'corpus': corpus}, query_planner_profile_id=None, graph_enabled=True)}


@pytest.mark.parametrize('case', ['fixture', 'replace', 'unbound'])
def test_loader_refuses_before_sql_write(setup_route, monkeypatch, case):
    monkeypatch.setattr(api, 'enforce_rate_limit', lambda *a: None)
    monkeypatch.setattr(api, '_load_vector_store_graph', lambda *a: pytest.fail('invalid load'))
    payload = graph_payload(artifact_class='fixture_only' if case == 'fixture' else 'reviewed_public')
    if case == 'replace':
        payload['replace'] = True
    if case == 'unbound':
        monkeypatch.delenv('SVS_CELL_GRAPH_PROFILE_PATH')
    with pytest.raises(HTTPException) as error:
        api.load_vector_store_graph(STORE, VectorStoreGraphLoadRequest(**payload), PRINCIPAL.model_copy(update={'scopes': ['vector_stores:write']}), Db())
    assert error.value.status_code == 422
