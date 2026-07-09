-- WAVE-019: OpenAI Responses lifecycle persistence.

CREATE TABLE IF NOT EXISTS openai_responses (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
  business_instance_id TEXT NOT NULL REFERENCES business_instances(id) ON DELETE CASCADE,
  user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  api_key_id TEXT REFERENCES api_keys(id) ON DELETE SET NULL,
  response JSONB NOT NULL DEFAULT '{}'::jsonb,
  input_items JSONB NOT NULL DEFAULT '[]'::jsonb,
  request JSONB NOT NULL DEFAULT '{}'::jsonb,
  status TEXT NOT NULL DEFAULT 'completed',
  deleted_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_openai_responses_scope_time
  ON openai_responses(tenant_id, business_instance_id, created_at DESC);

ALTER TABLE openai_responses ENABLE ROW LEVEL SECURITY;
ALTER TABLE openai_responses FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_scope_openai_responses ON openai_responses;
CREATE POLICY tenant_scope_openai_responses ON openai_responses
  USING (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id())
  WITH CHECK (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id());
