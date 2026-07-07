from types import SimpleNamespace

from svs_common.schemas import Principal, DocumentIngestRequest
from svs_common.vectorization_router import build_ingestion_plan


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
