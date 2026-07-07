-- WAVE-004: runtime RLS + asynchronous physical index cleanup.
-- App/API role is non-owner/NOBYPASSRLS; system worker can see inactive chunks
-- only inside the tenant/business context of the claimed job so it can purge
-- superseded/expired/deleted points from Qdrant/OpenSearch.

CREATE OR REPLACE FUNCTION svs_is_system_worker() RETURNS BOOLEAN AS $$
  SELECT coalesce(nullif(current_setting('svs.system_worker', true), '') = 'true', false);
$$ LANGUAGE SQL STABLE;

DROP POLICY IF EXISTS tenant_scope_chunks ON chunks;
CREATE POLICY tenant_scope_chunks ON chunks
  USING (
    (
      svs_is_system_worker()
      AND tenant_id = svs_current_tenant_id()
      AND business_instance_id = svs_current_business_instance_id()
    )
    OR (
      tenant_id = svs_current_tenant_id()
      AND business_instance_id = svs_current_business_instance_id()
      AND security_level <= svs_current_max_security_level()
      AND active = true
    )
  )
  WITH CHECK (
    (
      svs_is_system_worker()
      AND tenant_id = svs_current_tenant_id()
      AND business_instance_id = svs_current_business_instance_id()
    )
    OR (
      tenant_id = svs_current_tenant_id()
      AND business_instance_id = svs_current_business_instance_id()
      AND security_level <= svs_current_max_security_level()
    )
  );

CREATE INDEX IF NOT EXISTS idx_chunks_delete_queued
  ON chunks(tenant_id, business_instance_id, vector_store_id, document_version_id)
  WHERE active = false AND (dense_index_status = 'delete_queued' OR sparse_index_status = 'delete_queued');
