from svs_common.schemas import Principal, DocumentIngestRequest
from svs_common.vectorization_router import build_ingestion_plan


def test_router_denies_external_for_regulated_content():
    p = Principal(tenant_id='t', business_instance_id='b', max_security_level=5, scopes=['*'])
    req = DocumentIngestRequest(title='secret', filename='secret.md', content='# Secret\nhello', security_level=4)
    plan = build_ingestion_plan(p, req)
    assert plan.embedding_profile_id in {'bge_m3_local', 'hash_mock_1536'}
    assert any(not c.allowed for c in plan.candidates)


def test_router_picks_code_mode_candidate():
    p = Principal(tenant_id='t', business_instance_id='b', max_security_level=3, scopes=['*'])
    req = DocumentIngestRequest(title='code', filename='main.py', content='def alpha():\n    return 1', security_level=2)
    plan = build_ingestion_plan(p, req)
    assert plan.mode == 'code_repo_v1'
    assert plan.estimated_chunks >= 1
