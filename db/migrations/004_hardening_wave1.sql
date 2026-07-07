-- Hardening Wave 1: make RLS enforceable for table owners, track chunk index status,
-- add dedupe/versioning helpers, and include remaining production-control tables.

ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE instance_deployments ENABLE ROW LEVEL SECURITY;
ALTER TABLE eval_runs ENABLE ROW LEVEL SECURITY;

ALTER TABLE tenants FORCE ROW LEVEL SECURITY;
ALTER TABLE business_instances FORCE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;
ALTER TABLE groups FORCE ROW LEVEL SECURITY;
ALTER TABLE group_memberships FORCE ROW LEVEL SECURITY;
ALTER TABLE api_keys FORCE ROW LEVEL SECURITY;
ALTER TABLE knowledge_bases FORCE ROW LEVEL SECURITY;
ALTER TABLE vector_stores FORCE ROW LEVEL SECURITY;
ALTER TABLE sources FORCE ROW LEVEL SECURITY;
ALTER TABLE documents FORCE ROW LEVEL SECURITY;
ALTER TABLE document_versions FORCE ROW LEVEL SECURITY;
ALTER TABLE chunks FORCE ROW LEVEL SECURITY;
ALTER TABLE embeddings FORCE ROW LEVEL SECURITY;
ALTER TABLE vector_store_files FORCE ROW LEVEL SECURITY;
ALTER TABLE file_batches FORCE ROW LEVEL SECURITY;
ALTER TABLE ingestion_jobs FORCE ROW LEVEL SECURITY;
ALTER TABLE audit_events FORCE ROW LEVEL SECURITY;
ALTER TABLE usage_events FORCE ROW LEVEL SECURITY;
ALTER TABLE instance_deployments FORCE ROW LEVEL SECURITY;
ALTER TABLE eval_runs FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_scope_tenants ON tenants;
CREATE POLICY tenant_scope_tenants ON tenants
  USING (id = svs_current_tenant_id())
  WITH CHECK (id = svs_current_tenant_id());

DROP POLICY IF EXISTS tenant_scope_api_keys ON api_keys;
CREATE POLICY tenant_scope_api_keys ON api_keys
  USING (tenant_id = svs_current_tenant_id() AND (business_instance_id IS NULL OR business_instance_id = svs_current_business_instance_id()))
  WITH CHECK (tenant_id = svs_current_tenant_id() AND (business_instance_id IS NULL OR business_instance_id = svs_current_business_instance_id()));

DROP POLICY IF EXISTS tenant_scope_sources ON sources;
CREATE POLICY tenant_scope_sources ON sources
  USING (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id())
  WITH CHECK (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id());

DROP POLICY IF EXISTS tenant_scope_instance_deployments ON instance_deployments;
CREATE POLICY tenant_scope_instance_deployments ON instance_deployments
  USING (tenant_id = svs_current_tenant_id() AND (business_instance_id IS NULL OR business_instance_id = svs_current_business_instance_id()))
  WITH CHECK (tenant_id = svs_current_tenant_id() AND (business_instance_id IS NULL OR business_instance_id = svs_current_business_instance_id()));

DROP POLICY IF EXISTS tenant_scope_eval_runs ON eval_runs;
CREATE POLICY tenant_scope_eval_runs ON eval_runs
  USING (tenant_id = svs_current_tenant_id() AND (business_instance_id IS NULL OR business_instance_id = svs_current_business_instance_id()))
  WITH CHECK (tenant_id = svs_current_tenant_id() AND (business_instance_id IS NULL OR business_instance_id = svs_current_business_instance_id()));

ALTER TABLE chunks ADD COLUMN IF NOT EXISTS dense_index_status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS sparse_index_status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS indexed_at TIMESTAMPTZ;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS last_index_error TEXT;

CREATE INDEX IF NOT EXISTS idx_chunks_index_status ON chunks(tenant_id, business_instance_id, dense_index_status, sparse_index_status);
CREATE INDEX IF NOT EXISTS idx_documents_hash_scope ON documents(tenant_id, business_instance_id, knowledge_base_id, vector_store_id, content_hash) WHERE status='active';
CREATE INDEX IF NOT EXISTS idx_documents_source_version_target ON documents(tenant_id, business_instance_id, knowledge_base_id, vector_store_id, source_uri, filename) WHERE status='active';

-- Recreate tenant policies with explicit WITH CHECK so FORCE RLS remains compatible
-- with application writes through the non-owner runtime role.
DROP POLICY IF EXISTS tenant_scope_business_instances ON business_instances;
CREATE POLICY tenant_scope_business_instances ON business_instances
  USING (tenant_id = svs_current_tenant_id())
  WITH CHECK (tenant_id = svs_current_tenant_id());

DROP POLICY IF EXISTS tenant_scope_users ON users;
CREATE POLICY tenant_scope_users ON users
  USING (tenant_id = svs_current_tenant_id())
  WITH CHECK (tenant_id = svs_current_tenant_id());

DROP POLICY IF EXISTS tenant_scope_groups ON groups;
CREATE POLICY tenant_scope_groups ON groups
  USING (tenant_id = svs_current_tenant_id())
  WITH CHECK (tenant_id = svs_current_tenant_id());

DROP POLICY IF EXISTS tenant_scope_group_memberships ON group_memberships;
CREATE POLICY tenant_scope_group_memberships ON group_memberships
  USING (tenant_id = svs_current_tenant_id())
  WITH CHECK (tenant_id = svs_current_tenant_id());

DROP POLICY IF EXISTS tenant_scope_knowledge_bases ON knowledge_bases;
CREATE POLICY tenant_scope_knowledge_bases ON knowledge_bases
  USING (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id())
  WITH CHECK (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id());

DROP POLICY IF EXISTS tenant_scope_vector_stores ON vector_stores;
CREATE POLICY tenant_scope_vector_stores ON vector_stores
  USING (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id())
  WITH CHECK (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id());

DROP POLICY IF EXISTS tenant_scope_documents ON documents;
CREATE POLICY tenant_scope_documents ON documents
  USING (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id() AND security_level <= svs_current_max_security_level())
  WITH CHECK (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id() AND security_level <= svs_current_max_security_level());

DROP POLICY IF EXISTS tenant_scope_document_versions ON document_versions;
CREATE POLICY tenant_scope_document_versions ON document_versions
  USING (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id())
  WITH CHECK (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id());

DROP POLICY IF EXISTS tenant_scope_chunks ON chunks;
CREATE POLICY tenant_scope_chunks ON chunks
  USING (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id() AND security_level <= svs_current_max_security_level() AND active = true)
  WITH CHECK (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id() AND security_level <= svs_current_max_security_level());

DROP POLICY IF EXISTS tenant_scope_embeddings ON embeddings;
CREATE POLICY tenant_scope_embeddings ON embeddings
  USING (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id())
  WITH CHECK (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id());

DROP POLICY IF EXISTS tenant_scope_vector_store_files ON vector_store_files;
CREATE POLICY tenant_scope_vector_store_files ON vector_store_files
  USING (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id())
  WITH CHECK (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id());

DROP POLICY IF EXISTS tenant_scope_file_batches ON file_batches;
CREATE POLICY tenant_scope_file_batches ON file_batches
  USING (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id())
  WITH CHECK (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id());

DROP POLICY IF EXISTS tenant_scope_jobs ON ingestion_jobs;
CREATE POLICY tenant_scope_jobs ON ingestion_jobs
  USING (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id())
  WITH CHECK (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id());

DROP POLICY IF EXISTS tenant_scope_audit ON audit_events;
CREATE POLICY tenant_scope_audit ON audit_events
  USING (tenant_id = svs_current_tenant_id())
  WITH CHECK (tenant_id = svs_current_tenant_id());

DROP POLICY IF EXISTS tenant_scope_usage ON usage_events;
CREATE POLICY tenant_scope_usage ON usage_events
  USING (tenant_id = svs_current_tenant_id())
  WITH CHECK (tenant_id = svs_current_tenant_id());

ALTER TABLE vector_store_files ADD COLUMN IF NOT EXISTS file_batch_id TEXT REFERENCES file_batches(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_vector_store_files_batch ON vector_store_files(tenant_id, business_instance_id, vector_store_id, file_batch_id);

CREATE OR REPLACE FUNCTION svs_current_api_key_hash() RETURNS TEXT AS $$
  SELECT nullif(current_setting('svs.api_key_hash', true), '')::TEXT;
$$ LANGUAGE SQL STABLE;

CREATE OR REPLACE FUNCTION svs_is_system_worker() RETURNS BOOLEAN AS $$
  SELECT coalesce(nullif(current_setting('svs.system_worker', true), '') = 'true', false);
$$ LANGUAGE SQL STABLE;

DROP POLICY IF EXISTS tenant_scope_api_keys ON api_keys;
CREATE POLICY tenant_scope_api_keys ON api_keys
  USING (
    key_hash = svs_current_api_key_hash()
    OR (tenant_id = svs_current_tenant_id() AND (business_instance_id IS NULL OR business_instance_id = svs_current_business_instance_id()))
  )
  WITH CHECK (tenant_id = svs_current_tenant_id() AND (business_instance_id IS NULL OR business_instance_id = svs_current_business_instance_id()));

DROP POLICY IF EXISTS tenant_scope_jobs ON ingestion_jobs;
CREATE POLICY tenant_scope_jobs ON ingestion_jobs
  USING (svs_is_system_worker() OR (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id()))
  WITH CHECK (svs_is_system_worker() OR (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id()));
