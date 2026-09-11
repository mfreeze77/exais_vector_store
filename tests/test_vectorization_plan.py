from types import SimpleNamespace

from svs_common.chunking import estimate_tokens, STATECIVICS_PAGE_MARKDOWN_PROFILE
from svs_common.hashing import sha256_text
from svs_common.model_registry import estimate_embedding_cost, model_registry
from svs_common.schemas import Principal, DocumentIngestRequest, EmbeddingRequest
from svs_common.vectorization_router import build_ingestion_plan
from svs_model_gateway.main import estimate_cost


def settings(**overrides):
    values = {
        "svs_env": "local",
        "is_local_env": True,
        "default_embedding_provider": "hash_mock",
        "openai_api_key": None,
        "voyage_api_key": None,
        "cohere_api_key": None,
        "tei_endpoint_url": None,
        "runpod_embedding_endpoint_url": None,
        "infinity_endpoint_url": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_router_denies_external_for_regulated_content():
    p = Principal(tenant_id='t', business_instance_id='b', max_security_level=5, scopes=['*'])
    req = DocumentIngestRequest(title='secret', filename='secret.md', content='# Secret\nhello', security_level=4)
    plan = build_ingestion_plan(p, req, settings=settings())
    assert plan.embedding_profile_id == 'openai_text_embedding_3_small_1536'
    assert all(not c.allowed for c in plan.candidates)
    assert any('requires private provider' in reason for c in plan.candidates for reason in c.reasons)


def test_page_coordinate_opt_in_changes_chunking_but_preserves_mode_and_embedding_selection():
    principal = Principal(tenant_id='t', business_instance_id='b')
    content = '<!-- page 1 -->\nfirst\n<!-- page 2 -->\nsecond\n'
    req = DocumentIngestRequest(title='retained text', filename='text.md', content=content, mode='markdown_docs_v1')
    baseline = build_ingestion_plan(principal, req, settings=settings())
    opted = req.model_copy(update={'attributes': {
        'source_page_chunking_profile': STATECIVICS_PAGE_MARKDOWN_PROFILE,
        'source_collection': 'statecivics-kansas-fiscal-documents',
        'extraction_content_hash_sha256': sha256_text(content), 'source_page_count': 2,
    }})
    plan = build_ingestion_plan(principal, opted, settings=settings())
    assert plan.mode == baseline.mode == 'markdown_docs_v1'
    assert plan.embedding_profile_id == baseline.embedding_profile_id
    assert plan.candidates == baseline.candidates
    assert plan.chunker == STATECIVICS_PAGE_MARKDOWN_PROFILE and plan.chunker != baseline.chunker
    assert plan.estimated_chunks == 2


def test_router_uses_private_provider_for_regulated_content_when_configured():
    p = Principal(tenant_id='t', business_instance_id='b', max_security_level=5, scopes=['*'])
    req = DocumentIngestRequest(title='secret', filename='secret.md', content='# Secret\nhello', security_level=4)
    plan = build_ingestion_plan(
        p,
        req,
        settings=settings(runpod_embedding_endpoint_url='http://runpod-embeddings.local'),
    )

    assert plan.embedding_profile_id == 'bge_m3_local'
    bge = next(c for c in plan.candidates if c.model_profile_id == 'bge_m3_local')
    assert bge.allowed is True
    assert bge.configured is True


def test_router_picks_code_mode_candidate():
    p = Principal(tenant_id='t', business_instance_id='b', max_security_level=3, scopes=['*'])
    req = DocumentIngestRequest(title='code', filename='main.py', content='def alpha():\n    return 1', security_level=2)
    plan = build_ingestion_plan(p, req, settings=settings(openai_api_key='sk-test-not-real'))
    assert plan.mode == 'code_repo_v1'
    assert plan.estimated_chunks >= 1


def test_router_with_openai_key_selects_real_openai_profile():
    p = Principal(tenant_id='t', business_instance_id='b', max_security_level=3, scopes=['*'])
    req = DocumentIngestRequest(title='doc', filename='doc.md', content='# Doc\nhello', security_level=1)

    plan = build_ingestion_plan(p, req, settings=settings(openai_api_key='sk-test-not-real'))

    assert plan.embedding_profile_id == 'openai_text_embedding_3_small_1536'
    openai = next(c for c in plan.candidates if c.model_profile_id == 'openai_text_embedding_3_small_1536')
    assert openai.provider == 'openai'
    assert openai.configured is True
    assert openai.required_env == ['OPENAI_API_KEY']


def test_router_without_provider_keys_uses_explicit_hash_profile_for_local_mock():
    p = Principal(tenant_id='t', business_instance_id='b', max_security_level=3, scopes=['*'])
    req = DocumentIngestRequest(title='doc', filename='doc.md', content='# Doc\nhello', security_level=1)

    plan = build_ingestion_plan(p, req, settings=settings(openai_api_key=None))

    assert plan.embedding_profile_id == 'hash_mock_1536'
    openai = next(c for c in plan.candidates if c.model_profile_id == 'openai_text_embedding_3_small_1536')
    assert openai.allowed is False
    assert openai.configured is False
    assert openai.required_env == ['OPENAI_API_KEY']


def test_router_without_keys_and_without_local_mock_leaves_no_allowed_candidate():
    p = Principal(tenant_id='t', business_instance_id='b', max_security_level=3, scopes=['*'])
    req = DocumentIngestRequest(title='doc', filename='doc.md', content='# Doc\nhello', security_level=1)

    plan = build_ingestion_plan(
        p,
        req,
        settings=settings(default_embedding_provider='openai', openai_api_key=None),
    )

    assert plan.embedding_profile_id == 'openai_text_embedding_3_small_1536'
    assert all(not c.allowed for c in plan.candidates)
    assert any('no configured embedding provider candidate is allowed' in w for w in plan.warnings)


def test_pdf_markdown_external_uses_supported_voyage_embedding_profile():
    p = Principal(tenant_id='t', business_instance_id='b', max_security_level=3, scopes=['*'])
    req = DocumentIngestRequest(
        title='pdf',
        filename='source.md',
        mime_type='text/markdown',
        content='# PDF\nconverted markdown',
        mode='pdf_markdown_external_v1',
        security_level=2,
    )

    plan = build_ingestion_plan(p, req, settings=settings(voyage_api_key='pa-test-not-real'))

    assert plan.embedding_profile_id == 'voyage_4_docs_1024'
    voyage = next(c for c in plan.candidates if c.model_profile_id == 'voyage_4_docs_1024')
    assert voyage.provider == 'voyage'
    assert voyage.model == 'voyage-4'
    assert voyage.configured is True
    assert voyage.required_env == ['VOYAGE_API_KEY']


def test_openai_profile_exposes_per_million_cost_metadata():
    registry = model_registry()
    cost = registry['models']['openai_text_embedding_3_small_1536']['cost']

    assert cost['unit'] == '1m_input_tokens'
    assert cost['currency'] == 'USD'
    assert cost['input_per_1m_tokens_usd'] == 0.02


def test_cost_estimator_returns_priced_profile():
    estimate = estimate_embedding_cost('openai_text_embedding_3_small_1536', 1_500_000)

    assert estimate['model_profile_id'] == 'openai_text_embedding_3_small_1536'
    assert estimate['provider'] == 'openai'
    assert estimate['model'] == 'text-embedding-3-small'
    assert estimate['estimated_tokens'] == 1_500_000
    assert estimate['estimated_cost_usd'] == 0.03
    assert estimate['currency'] == 'USD'
    assert estimate['unit'] == '1m_input_tokens'
    assert estimate['reason'] is None


def test_cost_estimator_returns_unpriced_reason_without_guessing():
    estimate = estimate_embedding_cost('voyage_4_docs_1024', 10_000)

    assert estimate['model_profile_id'] == 'voyage_4_docs_1024'
    assert estimate['provider'] == 'voyage'
    assert estimate['estimated_cost_usd'] is None
    assert estimate['reason'] == 'cost_unavailable'


def test_cost_estimator_returns_unknown_reason_without_guessing():
    estimate = estimate_embedding_cost('missing_embedding_profile', 10_000)

    assert estimate['model_profile_id'] == 'missing_embedding_profile'
    assert estimate['estimated_cost_usd'] is None
    assert estimate['reason'] == 'unknown_model_profile'


def test_model_gateway_estimate_cost_route_uses_registry_costs():
    text = 'alpha beta gamma delta'
    estimate = estimate_cost(EmbeddingRequest(input=text, model_profile_id='openai_text_embedding_3_small_1536'))

    assert estimate['estimated_tokens'] == estimate_tokens(text)
    assert estimate['model_profile_id'] == 'openai_text_embedding_3_small_1536'
    assert estimate['provider'] == 'openai'
    assert estimate['model'] == 'text-embedding-3-small'
    assert estimate['estimated_cost_usd'] == round((estimate_tokens(text) / 1_000_000) * 0.02, 10)
    assert estimate['currency'] == 'USD'


def test_plan_candidates_include_cost_hints_without_reordering():
    p = Principal(tenant_id='t', business_instance_id='b', max_security_level=3, scopes=['*'])
    req = DocumentIngestRequest(title='doc', filename='doc.md', content='# Doc\nalpha beta gamma', security_level=1)

    plan = build_ingestion_plan(p, req, settings=settings(openai_api_key='sk-test-not-real'))

    assert [c.model_profile_id for c in plan.candidates] == [
        'openai_text_embedding_3_small_1536',
        'hash_mock_1536',
        'bge_m3_local',
    ]
    openai = plan.candidates[0]
    assert openai.estimated_input_tokens == plan.estimated_tokens
    assert openai.estimated_cost_usd == round((plan.estimated_tokens / 1_000_000) * 0.02, 10)
    assert openai.cost_currency == 'USD'
    assert openai.cost_unit == '1m_input_tokens'
    assert openai.cost_per_1m_tokens_usd == 0.02
    assert openai.cost_reason is None

    local = next(c for c in plan.candidates if c.model_profile_id == 'bge_m3_local')
    assert local.estimated_cost_usd is None
    assert local.cost_reason == 'cost_unavailable'


def _statute_request():
    from svs_common.statecivics_statutes import STATECIVICS_STATUTE_MARKDOWN_PROFILE, STATUTE_SOURCE_COLLECTION
    text = '# K.S.A. 2-303 — Test mechanics\n\n**Source:** https://ksrevisor.gov/statutes/chapters/ch02/002_003_0003.html\n\nA short law.\n'
    return DocumentIngestRequest(title='statute', filename='statute.md', content=text, mode='markdown_docs_v1',
                                 source_identity='test-statute', attributes={
                                     'source_text_chunking_profile': STATECIVICS_STATUTE_MARKDOWN_PROFILE,
                                     'source_collection': STATUTE_SOURCE_COLLECTION,
                                     'extraction_content_hash_sha256': sha256_text(text)})


def test_statutes_select_only_voyage_4_1024_even_when_other_providers_available():
    plan = build_ingestion_plan(Principal(tenant_id='t', business_instance_id='b'), _statute_request(),
                               settings=settings(voyage_api_key='test-not-a-real-key', openai_api_key='also-not-real'))
    assert plan.chunker == 'statecivics_statute_markdown_v1'
    assert plan.mode == 'markdown_docs_v1' and plan.embedding_profile_id == 'voyage_4_docs_1024'
    assert len(plan.candidates) == 1
    assert (plan.candidates[0].provider, plan.candidates[0].model, plan.candidates[0].dimensions) == ('voyage', 'voyage-4', 1024)


def test_statutes_fail_when_voyage_is_unconfigured_or_privacy_denied():
    import pytest
    principal = Principal(tenant_id='t', business_instance_id='b')
    for request, config in [(_statute_request(), settings(openai_api_key='not-real')),
                            (_statute_request().model_copy(update={'security_level': 4}),
                             settings(voyage_api_key='not-real', runpod_embedding_endpoint_url='http://fake'))]:
        with pytest.raises(ValueError, match='fallback is forbidden'):
            build_ingestion_plan(principal, request, settings=config)


def test_statutes_fail_for_wrong_registered_voyage_dimensions(monkeypatch):
    import copy
    import pytest
    from svs_common import vectorization_router as router
    registry = copy.deepcopy(model_registry())
    registry['models']['voyage_4_docs_1024']['dimensions'] = 1536
    monkeypatch.setattr(router, 'model_registry', lambda: registry)
    with pytest.raises(ValueError, match='1024-dimensional'):
        build_ingestion_plan(Principal(tenant_id='t', business_instance_id='b'), _statute_request(),
                             settings=settings(voyage_api_key='not-real'))
