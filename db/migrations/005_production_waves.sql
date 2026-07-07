-- v0.9.5 production waves: router tables, idempotency, rate limits, maintenance, backups.

ALTER TABLE vector_stores ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE document_versions ADD COLUMN IF NOT EXISTS superseded_by_version_id TEXT;
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
ALTER TABLE vector_store_files ADD COLUMN IF NOT EXISTS file_batch_id TEXT REFERENCES file_batches(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_vector_store_files_batch ON vector_store_files(tenant_id, business_instance_id, vector_store_id, file_batch_id);

CREATE TABLE IF NOT EXISTS model_endpoints (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  business_instance_id TEXT NOT NULL REFERENCES business_instances(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  provider TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'embedding',
  base_url TEXT,
  model TEXT,
  dimensions INT,
  privacy TEXT NOT NULL DEFAULT 'external_api',
  security_max_level INT NOT NULL DEFAULT 3 CHECK(security_max_level BETWEEN 0 AND 5),
  status TEXT NOT NULL DEFAULT 'active',
  config JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(tenant_id, business_instance_id, name)
);

CREATE TABLE IF NOT EXISTS ingestion_plans (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  business_instance_id TEXT NOT NULL REFERENCES business_instances(id) ON DELETE CASCADE,
  user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  vector_store_id TEXT REFERENCES vector_stores(id) ON DELETE SET NULL,
  knowledge_base_id TEXT REFERENCES knowledge_bases(id) ON DELETE SET NULL,
  mode TEXT NOT NULL,
  parser_profile_id TEXT,
  chunking_profile_id TEXT,
  embedding_profile_id TEXT,
  retrieval_profile_id TEXT,
  request JSONB NOT NULL DEFAULT '{}'::jsonb,
  plan JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'planned',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  accepted_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_ingestion_plans_scope ON ingestion_plans(tenant_id, business_instance_id, created_at DESC);

CREATE TABLE IF NOT EXISTS bakeoff_runs (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  business_instance_id TEXT NOT NULL REFERENCES business_instances(id) ON DELETE CASCADE,
  user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  mode TEXT NOT NULL,
  model_profile_ids TEXT[] NOT NULL DEFAULT '{}',
  queries JSONB NOT NULL DEFAULT '[]'::jsonb,
  metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'queued',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS bakeoff_results (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  business_instance_id TEXT NOT NULL REFERENCES business_instances(id) ON DELETE CASCADE,
  run_id TEXT NOT NULL REFERENCES bakeoff_runs(id) ON DELETE CASCADE,
  model_profile_id TEXT NOT NULL,
  metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'completed',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_bakeoff_results_run ON bakeoff_results(tenant_id, business_instance_id, run_id);

CREATE TABLE IF NOT EXISTS idempotency_keys (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  business_instance_id TEXT NOT NULL REFERENCES business_instances(id) ON DELETE CASCADE,
  user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  api_key_id TEXT REFERENCES api_keys(id) ON DELETE SET NULL,
  idempotency_key TEXT NOT NULL,
  request_fingerprint TEXT NOT NULL,
  response JSONB NOT NULL DEFAULT '{}'::jsonb,
  status_code INT NOT NULL DEFAULT 200,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(tenant_id, business_instance_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_idempotency_expiry ON idempotency_keys(expires_at);

CREATE TABLE IF NOT EXISTS rate_limit_counters (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  business_instance_id TEXT NOT NULL REFERENCES business_instances(id) ON DELETE CASCADE,
  subject_id TEXT NOT NULL,
  bucket TEXT NOT NULL,
  window_start TIMESTAMPTZ NOT NULL,
  count INT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(tenant_id, business_instance_id, subject_id, bucket, window_start)
);
CREATE INDEX IF NOT EXISTS idx_rate_limit_window ON rate_limit_counters(window_start);

CREATE TABLE IF NOT EXISTS backup_bundles (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  business_instance_id TEXT NOT NULL REFERENCES business_instances(id) ON DELETE CASCADE,
  instance_id TEXT,
  bundle_type TEXT NOT NULL DEFAULT 'instance',
  status TEXT NOT NULL DEFAULT 'planned',
  manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
  object_key TEXT,
  checksum_sha256 TEXT,
  size_bytes BIGINT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS deployment_locks (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  business_instance_id TEXT,
  instance_id TEXT NOT NULL,
  locked_by TEXT NOT NULL,
  reason TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(instance_id)
);

ALTER TABLE model_endpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE ingestion_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE bakeoff_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE bakeoff_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE idempotency_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE rate_limit_counters ENABLE ROW LEVEL SECURITY;
ALTER TABLE backup_bundles ENABLE ROW LEVEL SECURITY;
ALTER TABLE deployment_locks ENABLE ROW LEVEL SECURITY;

ALTER TABLE model_endpoints FORCE ROW LEVEL SECURITY;
ALTER TABLE ingestion_plans FORCE ROW LEVEL SECURITY;
ALTER TABLE bakeoff_runs FORCE ROW LEVEL SECURITY;
ALTER TABLE bakeoff_results FORCE ROW LEVEL SECURITY;
ALTER TABLE idempotency_keys FORCE ROW LEVEL SECURITY;
ALTER TABLE rate_limit_counters FORCE ROW LEVEL SECURITY;
ALTER TABLE backup_bundles FORCE ROW LEVEL SECURITY;
ALTER TABLE deployment_locks FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_scope_model_endpoints ON model_endpoints;
CREATE POLICY tenant_scope_model_endpoints ON model_endpoints
  USING (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id())
  WITH CHECK (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id());

DROP POLICY IF EXISTS tenant_scope_ingestion_plans ON ingestion_plans;
CREATE POLICY tenant_scope_ingestion_plans ON ingestion_plans
  USING (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id())
  WITH CHECK (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id());

DROP POLICY IF EXISTS tenant_scope_bakeoff_runs ON bakeoff_runs;
CREATE POLICY tenant_scope_bakeoff_runs ON bakeoff_runs
  USING (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id())
  WITH CHECK (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id());

DROP POLICY IF EXISTS tenant_scope_bakeoff_results ON bakeoff_results;
CREATE POLICY tenant_scope_bakeoff_results ON bakeoff_results
  USING (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id())
  WITH CHECK (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id());

DROP POLICY IF EXISTS tenant_scope_idempotency ON idempotency_keys;
CREATE POLICY tenant_scope_idempotency ON idempotency_keys
  USING (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id())
  WITH CHECK (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id());

DROP POLICY IF EXISTS tenant_scope_rate_limits ON rate_limit_counters;
CREATE POLICY tenant_scope_rate_limits ON rate_limit_counters
  USING (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id())
  WITH CHECK (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id());

DROP POLICY IF EXISTS tenant_scope_backup_bundles ON backup_bundles;
CREATE POLICY tenant_scope_backup_bundles ON backup_bundles
  USING (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id())
  WITH CHECK (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id());

DROP POLICY IF EXISTS tenant_scope_deployment_locks ON deployment_locks;
CREATE POLICY tenant_scope_deployment_locks ON deployment_locks
  USING (tenant_id = svs_current_tenant_id() AND (business_instance_id IS NULL OR business_instance_id = svs_current_business_instance_id()))
  WITH CHECK (tenant_id = svs_current_tenant_id() AND (business_instance_id IS NULL OR business_instance_id = svs_current_business_instance_id()));
