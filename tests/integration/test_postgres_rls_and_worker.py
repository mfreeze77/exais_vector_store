from __future__ import annotations
import os, asyncio, uuid
import pytest
psycopg = pytest.importorskip("psycopg")

pytestmark = pytest.mark.skipif(os.getenv('SVS_RUN_INTEGRATION') != '1', reason='set SVS_RUN_INTEGRATION=1 and run docker compose postgres')

OWNER_DSN = os.getenv('DATABASE_URL_MIGRATIONS', 'postgresql://svs_owner:svs_owner_dev_password@localhost:5432/svs')
APP_DSN = os.getenv('SVS_TEST_APP_DSN', 'postgresql://svs_app:svs_app_dev_password@localhost:5432/svs')
APP_DSN_SA = os.getenv('DATABASE_URL', 'postgresql+psycopg://svs_app:svs_app_dev_password@localhost:5432/svs')

PROTECTED_TABLES = {
    'tenants','business_instances','users','groups','group_memberships','api_keys','knowledge_bases','vector_stores',
    'sources','documents','document_versions','chunks','embeddings','vector_store_files','file_batches','ingestion_jobs',
    'audit_events','usage_events','instance_deployments','eval_runs','model_endpoints','ingestion_plans','bakeoff_runs',
    'bakeoff_results','idempotency_keys','rate_limit_counters','backup_bundles','deployment_locks'
}


def _set_scope(conn, tenant='ten_dev', biz='biz_dev', max_level='5', *, system_worker=False):
    conn.execute("SELECT set_config('svs.tenant_id', %s, true)", (tenant,))
    conn.execute("SELECT set_config('svs.business_instance_id', %s, true)", (biz,))
    conn.execute("SELECT set_config('svs.max_security_level', %s, true)", (str(max_level),))
    if system_worker:
        conn.execute("SELECT set_config('svs.system_worker', 'true', true)")


def _clear_dev_jobs():
    # Honest under FORCE RLS even when OWNER_DSN is not a superuser.
    with psycopg.connect(OWNER_DSN) as owner:
        _set_scope(owner, system_worker=True)
        owner.execute("DELETE FROM ingestion_jobs WHERE tenant_id='ten_dev' AND business_instance_id='biz_dev'")


def _configure_worker_env(monkeypatch, tmp_path, *, strict: bool):
    monkeypatch.setenv('DATABASE_URL', APP_DSN_SA)
    monkeypatch.setenv('SVS_ENV', 'ci')
    monkeypatch.setenv('SVS_DEV_MODE', 'false')
    monkeypatch.setenv('SVS_API_KEY_PEPPER', 'x' * 64)
    monkeypatch.setenv('SVS_INDEX_STRICT', 'true' if strict else 'false')
    monkeypatch.setenv('SVS_DENSE_BACKEND', 'qdrant')
    monkeypatch.setenv('SVS_SPARSE_BACKEND', 'postgres_fts')
    monkeypatch.setenv('SVS_LOCAL_OBJECT_STORE_PATH', str(tmp_path))
    live_qdrant_url = os.getenv('SVS_TEST_QDRANT_URL', 'http://127.0.0.1:6333')
    outage_qdrant_url = os.getenv('SVS_TEST_QDRANT_OUTAGE_URL', 'http://127.0.0.1:65534')
    monkeypatch.setenv('QDRANT_URL', outage_qdrant_url if strict else live_qdrant_url)
    import svs_common.config as cfg
    import svs_common.db as dbmod
    cfg.get_settings.cache_clear()
    dbmod._engine = None
    dbmod._SessionLocal = None


def _enqueue_real_document(title: str):
    from svs_common.db import scoped_session
    from svs_common.ingestion import IngestionService
    from svs_common.schemas import Principal, DocumentIngestRequest

    principal = Principal(
        tenant_id='ten_dev',
        business_instance_id='biz_dev',
        user_id='usr_dev',
        groups=['admins', 'engineering'],
        roles=['owner', 'admin'],
        max_security_level=5,
        scopes=['documents:write', 'retrieval:read'],
    )
    req = DocumentIngestRequest(
        title=title,
        filename=f'{title.lower().replace(" ", "-")}.md',
        mime_type='text/markdown',
        content=f'# {title}\nThis is a live Postgres JSONB integration proof document.',
        mode='markdown_docs_v1',
        knowledge_base_id='kb_dev',
        vector_store_id='vs_dev',
        security_level=1,
        attributes={'integration_test': True, 'title': title},
    )
    with scoped_session(principal) as db:
        return IngestionService().enqueue(db, principal, req).id


def test_runtime_role_is_not_superuser_or_rls_bypass():
    with psycopg.connect(OWNER_DSN) as conn:
        row = conn.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname='svs_app'").fetchone()
    assert row == (False, False)


def test_every_rls_table_is_forced():
    with psycopg.connect(OWNER_DSN) as conn:
        rows = conn.execute('''
            SELECT relname, relrowsecurity, relforcerowsecurity
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND relkind='r' AND relname = ANY(%s)
        ''', (list(PROTECTED_TABLES),)).fetchall()
    seen = {r[0] for r in rows}
    assert PROTECTED_TABLES.issubset(seen)
    assert all(r[1] and r[2] for r in rows)


def test_app_role_cannot_cross_tenant_even_with_plain_sql():
    with psycopg.connect(OWNER_DSN) as owner:
        _set_scope(owner, 'ten_other', 'biz_other')
        owner.execute("INSERT INTO tenants(id,name,slug) VALUES ('ten_other','Other','other') ON CONFLICT DO NOTHING")
        owner.execute("INSERT INTO business_instances(id,tenant_id,name,slug) VALUES ('biz_other','ten_other','Other','other') ON CONFLICT DO NOTHING")
    with psycopg.connect(APP_DSN) as app:
        _set_scope(app, 'ten_dev', 'biz_dev')
        rows = app.execute('SELECT id, tenant_id FROM business_instances ORDER BY id').fetchall()
    assert rows == [('biz_dev', 'ten_dev')]


def test_worker_completes_real_document_against_live_postgres(monkeypatch, tmp_path):
    _clear_dev_jobs()
    _configure_worker_env(monkeypatch, tmp_path, strict=False)
    title = f'JSONB success proof {uuid.uuid4().hex[:8]}'
    job_id = _enqueue_real_document(title)

    from svs_worker import main as worker_main
    assert asyncio.run(worker_main.process_once()) is True
    with psycopg.connect(OWNER_DSN) as owner:
        _set_scope(owner, system_worker=True)
        status, err = owner.execute('SELECT status, last_error FROM ingestion_jobs WHERE id=%s', (job_id,)).fetchone()
        doc_count = owner.execute('SELECT count(*) FROM documents WHERE title=%s', (title,)).fetchone()[0]
        chunk_count = owner.execute('''
            SELECT count(*)
            FROM chunks c JOIN documents d ON d.id=c.document_id
            WHERE d.title=%s AND c.metadata->>'chunker' IS NOT NULL
        ''', (title,)).fetchone()[0]
        usage_count = owner.execute("SELECT count(*) FROM usage_events WHERE event_type='ingestion.chunks_indexed'").fetchone()[0]
    assert status == 'completed'
    assert err is None
    assert doc_count == 1
    assert chunk_count >= 1
    assert usage_count >= 1


def test_qdrant_outage_retries_to_terminal_failure_without_ghost_documents(monkeypatch, tmp_path):
    _clear_dev_jobs()
    _configure_worker_env(monkeypatch, tmp_path, strict=True)
    title = f'Qdrant outage proof {uuid.uuid4().hex[:8]}'
    job_id = _enqueue_real_document(title)

    from svs_worker import main as worker_main
    status = None
    attempts = 0
    max_attempts = 0
    err = None
    for _ in range(10):
        assert asyncio.run(worker_main.process_once()) is True
        with psycopg.connect(OWNER_DSN) as owner:
            _set_scope(owner, system_worker=True)
            status, attempts, max_attempts, err = owner.execute(
                'SELECT status, attempts, max_attempts, last_error FROM ingestion_jobs WHERE id=%s',
                (job_id,),
            ).fetchone()
        if status in {'completed', 'failed', 'cancelled'}:
            break

    assert status == 'failed'
    assert attempts == max_attempts
    assert 'Qdrant' in err or 'Connection' in err or 'Index' in err
    with psycopg.connect(OWNER_DSN) as owner:
        _set_scope(owner, system_worker=True)
        doc_count = owner.execute('SELECT count(*) FROM documents WHERE title=%s', (title,)).fetchone()[0]
        docv_count = owner.execute("""
            SELECT count(*)
            FROM document_versions dv
            JOIN documents d ON d.id=dv.document_id
            WHERE d.title=%s
        """, (title,)).fetchone()[0]
        chunk_count = owner.execute("""
            SELECT count(*)
            FROM chunks c
            JOIN documents d ON d.id=c.document_id
            WHERE d.title=%s
        """, (title,)).fetchone()[0]
    assert doc_count == 0
    assert docv_count == 0
    assert chunk_count == 0
