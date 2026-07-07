-- Brand existing local/dev seed records for Expert AI Services.
-- This is intentionally idempotent because the migration runner reapplies files.

UPDATE tenants
SET name = 'Expert AI Services',
    slug = 'expertaiservices'
WHERE id = 'ten_dev';

UPDATE business_instances
SET name = 'Expert AI Services',
    slug = 'expert-ai-services'
WHERE id = 'biz_dev';

UPDATE users
SET email = 'mfrieson@expertaiservices.com',
    display_name = 'Expert AI Services Builder'
WHERE id = 'usr_dev'
  AND tenant_id = 'ten_dev';

UPDATE knowledge_bases
SET name = 'exai_vector_store KB',
    slug = 'exai-vector-store'
WHERE id = 'kb_dev'
  AND tenant_id = 'ten_dev'
  AND business_instance_id = 'biz_dev';

UPDATE vector_stores
SET name = 'Expert AI Services Vector Store',
    attributes = coalesce(attributes, '{}'::jsonb) || '{"environment":"local","project":"exai_vector_store","builder":"mfrieson@expertaiservices.com","domain":"expertaiservices.com"}'::jsonb
WHERE id = 'vs_dev'
  AND tenant_id = 'ten_dev'
  AND business_instance_id = 'biz_dev';
