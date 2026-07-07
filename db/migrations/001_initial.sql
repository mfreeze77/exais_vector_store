CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS tenants (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  slug TEXT UNIQUE NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS business_instances (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  slug TEXT NOT NULL,
  deployment_mode TEXT NOT NULL DEFAULT 'shared_micro_cell',
  isolation_level TEXT NOT NULL DEFAULT 'business_instance',
  config JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(tenant_id, slug)
);

CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  email TEXT NOT NULL,
  display_name TEXT,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(tenant_id, email)
);

CREATE TABLE IF NOT EXISTS groups (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  business_instance_id TEXT REFERENCES business_instances(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  slug TEXT NOT NULL,
  UNIQUE(tenant_id, business_instance_id, slug)
);

CREATE TABLE IF NOT EXISTS group_memberships (
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  group_id TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role TEXT NOT NULL DEFAULT 'member',
  PRIMARY KEY(group_id, user_id)
);

CREATE TABLE IF NOT EXISTS api_keys (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  business_instance_id TEXT REFERENCES business_instances(id) ON DELETE CASCADE,
  user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  key_hash TEXT NOT NULL UNIQUE,
  label TEXT NOT NULL,
  scopes TEXT[] NOT NULL DEFAULT '{}',
  max_security_level INT NOT NULL DEFAULT 1 CHECK(max_security_level BETWEEN 0 AND 5),
  status TEXT NOT NULL DEFAULT 'active',
  last_used_at TIMESTAMPTZ,
  expires_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS knowledge_bases (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  business_instance_id TEXT NOT NULL REFERENCES business_instances(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  slug TEXT NOT NULL,
  security_level INT NOT NULL DEFAULT 1 CHECK(security_level BETWEEN 0 AND 5),
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(tenant_id, business_instance_id, slug)
);

CREATE TABLE IF NOT EXISTS vector_stores (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  business_instance_id TEXT NOT NULL REFERENCES business_instances(id) ON DELETE CASCADE,
  knowledge_base_id TEXT REFERENCES knowledge_bases(id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
  expires_after JSONB,
  expires_at TIMESTAMPTZ,
  last_active_at TIMESTAMPTZ,
  usage_bytes BIGINT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  business_instance_id TEXT NOT NULL REFERENCES business_instances(id) ON DELETE CASCADE,
  knowledge_base_id TEXT REFERENCES knowledge_bases(id) ON DELETE SET NULL,
  source_type TEXT NOT NULL,
  external_ref TEXT,
  config JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS documents (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  business_instance_id TEXT NOT NULL REFERENCES business_instances(id) ON DELETE CASCADE,
  knowledge_base_id TEXT REFERENCES knowledge_bases(id) ON DELETE SET NULL,
  vector_store_id TEXT REFERENCES vector_stores(id) ON DELETE SET NULL,
  source_id TEXT REFERENCES sources(id) ON DELETE SET NULL,
  title TEXT NOT NULL,
  filename TEXT,
  mime_type TEXT,
  source_uri TEXT,
  content_hash TEXT NOT NULL,
  security_level INT NOT NULL DEFAULT 1 CHECK(security_level BETWEEN 0 AND 5),
  classification TEXT NOT NULL DEFAULT 'tenant_private',
  allowed_groups TEXT[] NOT NULL DEFAULT '{}',
  allowed_roles TEXT[] NOT NULL DEFAULT '{}',
  denied_groups TEXT[] NOT NULL DEFAULT '{}',
  contains_pii BOOLEAN NOT NULL DEFAULT false,
  contains_secrets BOOLEAN NOT NULL DEFAULT false,
  prompt_injection_risk TEXT NOT NULL DEFAULT 'unknown',
  source_trust TEXT NOT NULL DEFAULT 'user_upload',
  status TEXT NOT NULL DEFAULT 'active',
  current_version_id TEXT,
  acl_version TEXT NOT NULL DEFAULT 'v1',
  retention_policy_id TEXT,
  expires_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS document_versions (
  id TEXT PRIMARY KEY,
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  tenant_id TEXT NOT NULL,
  business_instance_id TEXT NOT NULL,
  version_number INT NOT NULL,
  object_key TEXT,
  parsed_object_key TEXT,
  parser_profile_id TEXT NOT NULL,
  vectorization_profile_id TEXT NOT NULL,
  embedding_profile_id TEXT NOT NULL,
  chunking_profile_id TEXT NOT NULL,
  source_content_hash TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'indexed',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(document_id, version_number)
);

CREATE TABLE IF NOT EXISTS chunks (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  business_instance_id TEXT NOT NULL REFERENCES business_instances(id) ON DELETE CASCADE,
  knowledge_base_id TEXT REFERENCES knowledge_bases(id) ON DELETE SET NULL,
  vector_store_id TEXT REFERENCES vector_stores(id) ON DELETE SET NULL,
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  document_version_id TEXT NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
  ordinal INT NOT NULL,
  heading_path TEXT[] NOT NULL DEFAULT '{}',
  page_start INT,
  page_end INT,
  char_start INT,
  char_end INT,
  token_count INT,
  text TEXT NOT NULL,
  text_hash TEXT NOT NULL,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  security_level INT NOT NULL DEFAULT 1 CHECK(security_level BETWEEN 0 AND 5),
  classification TEXT NOT NULL DEFAULT 'tenant_private',
  allowed_groups TEXT[] NOT NULL DEFAULT '{}',
  allowed_roles TEXT[] NOT NULL DEFAULT '{}',
  acl_bucket TEXT NOT NULL DEFAULT 'default',
  active BOOLEAN NOT NULL DEFAULT true,
  search_vector tsvector GENERATED ALWAYS AS (to_tsvector('english', coalesce(text,''))) STORED,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_chunks_scope ON chunks(tenant_id, business_instance_id, knowledge_base_id, active, security_level);
CREATE INDEX IF NOT EXISTS idx_chunks_doc_ord ON chunks(document_id, ordinal);
CREATE INDEX IF NOT EXISTS idx_chunks_fts ON chunks USING GIN(search_vector);
CREATE INDEX IF NOT EXISTS idx_chunks_trgm ON chunks USING GIN(text gin_trgm_ops);

CREATE TABLE IF NOT EXISTS embeddings (
  id TEXT PRIMARY KEY,
  chunk_id TEXT NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
  tenant_id TEXT NOT NULL,
  business_instance_id TEXT NOT NULL,
  embedding_profile_id TEXT NOT NULL,
  model_provider TEXT NOT NULL,
  model_name TEXT NOT NULL,
  dimensions INT NOT NULL,
  vector_point_id TEXT NOT NULL,
  vector_collection TEXT NOT NULL,
  input_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE(chunk_id, embedding_profile_id)
);

CREATE TABLE IF NOT EXISTS vector_store_files (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  business_instance_id TEXT NOT NULL REFERENCES business_instances(id) ON DELETE CASCADE,
  vector_store_id TEXT NOT NULL REFERENCES vector_stores(id) ON DELETE CASCADE,
  document_id TEXT REFERENCES documents(id) ON DELETE SET NULL,
  status TEXT NOT NULL DEFAULT 'in_progress',
  attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
  usage_bytes BIGINT NOT NULL DEFAULT 0,
  last_error JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS file_batches (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  business_instance_id TEXT NOT NULL REFERENCES business_instances(id) ON DELETE CASCADE,
  vector_store_id TEXT NOT NULL REFERENCES vector_stores(id) ON DELETE CASCADE,
  status TEXT NOT NULL DEFAULT 'in_progress',
  file_counts JSONB NOT NULL DEFAULT '{"in_progress":0,"completed":0,"failed":0,"cancelled":0,"total":0}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS ingestion_jobs (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  business_instance_id TEXT NOT NULL REFERENCES business_instances(id) ON DELETE CASCADE,
  job_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued',
  priority INT NOT NULL DEFAULT 100,
  payload JSONB NOT NULL,
  attempts INT NOT NULL DEFAULT 0,
  max_attempts INT NOT NULL DEFAULT 3,
  locked_by TEXT,
  locked_at TIMESTAMPTZ,
  last_error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_jobs_queue ON ingestion_jobs(status, priority, created_at);

CREATE TABLE IF NOT EXISTS audit_events (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  business_instance_id TEXT,
  user_id TEXT,
  api_key_id TEXT,
  event_type TEXT NOT NULL,
  action TEXT NOT NULL,
  resource_type TEXT,
  resource_id TEXT,
  security_level INT,
  query_hash TEXT,
  allowed BOOLEAN NOT NULL DEFAULT true,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_scope_time ON audit_events(tenant_id, business_instance_id, created_at DESC);

CREATE TABLE IF NOT EXISTS usage_events (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  business_instance_id TEXT,
  user_id TEXT,
  event_type TEXT NOT NULL,
  quantity NUMERIC NOT NULL DEFAULT 0,
  unit TEXT NOT NULL,
  provider TEXT,
  model TEXT,
  cost_estimate_usd NUMERIC,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS instance_deployments (
  id TEXT PRIMARY KEY,
  instance_id TEXT NOT NULL,
  tenant_id TEXT,
  business_instance_id TEXT,
  from_version TEXT,
  to_version TEXT NOT NULL,
  image_digests JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'planned',
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS eval_runs (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  business_instance_id TEXT,
  eval_profile_id TEXT NOT NULL,
  vectorization_profile_id TEXT,
  model_profile_id TEXT,
  status TEXT NOT NULL DEFAULT 'queued',
  metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  report_object_key TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  completed_at TIMESTAMPTZ
);
