ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE business_instances ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE group_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_bases ENABLE ROW LEVEL SECURITY;
ALTER TABLE vector_stores ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE embeddings ENABLE ROW LEVEL SECURITY;
ALTER TABLE vector_store_files ENABLE ROW LEVEL SECURITY;
ALTER TABLE file_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE ingestion_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_events ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION svs_current_tenant_id() RETURNS TEXT AS $$
  SELECT nullif(current_setting('svs.tenant_id', true), '')::TEXT;
$$ LANGUAGE SQL STABLE;

CREATE OR REPLACE FUNCTION svs_current_business_instance_id() RETURNS TEXT AS $$
  SELECT nullif(current_setting('svs.business_instance_id', true), '')::TEXT;
$$ LANGUAGE SQL STABLE;

CREATE OR REPLACE FUNCTION svs_current_max_security_level() RETURNS INT AS $$
  SELECT coalesce(nullif(current_setting('svs.max_security_level', true), '')::INT, 0);
$$ LANGUAGE SQL STABLE;

CREATE POLICY tenant_scope_business_instances ON business_instances USING (tenant_id = svs_current_tenant_id());
CREATE POLICY tenant_scope_users ON users USING (tenant_id = svs_current_tenant_id());
CREATE POLICY tenant_scope_groups ON groups USING (tenant_id = svs_current_tenant_id());
CREATE POLICY tenant_scope_group_memberships ON group_memberships USING (tenant_id = svs_current_tenant_id());
CREATE POLICY tenant_scope_knowledge_bases ON knowledge_bases USING (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id());
CREATE POLICY tenant_scope_vector_stores ON vector_stores USING (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id());
CREATE POLICY tenant_scope_documents ON documents USING (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id() AND security_level <= svs_current_max_security_level());
CREATE POLICY tenant_scope_document_versions ON document_versions USING (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id());
CREATE POLICY tenant_scope_chunks ON chunks USING (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id() AND security_level <= svs_current_max_security_level() AND active = true);
CREATE POLICY tenant_scope_embeddings ON embeddings USING (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id());
CREATE POLICY tenant_scope_vector_store_files ON vector_store_files USING (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id());
CREATE POLICY tenant_scope_file_batches ON file_batches USING (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id());
CREATE POLICY tenant_scope_jobs ON ingestion_jobs USING (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id());
CREATE POLICY tenant_scope_audit ON audit_events USING (tenant_id = svs_current_tenant_id());
CREATE POLICY tenant_scope_usage ON usage_events USING (tenant_id = svs_current_tenant_id());
