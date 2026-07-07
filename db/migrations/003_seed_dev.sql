INSERT INTO tenants(id, name, slug) VALUES ('ten_dev', 'Expert AI Services', 'expertaiservices') ON CONFLICT DO NOTHING;
INSERT INTO business_instances(id, tenant_id, name, slug) VALUES ('biz_dev', 'ten_dev', 'Expert AI Services', 'expert-ai-services') ON CONFLICT DO NOTHING;
INSERT INTO users(id, tenant_id, email, display_name) VALUES ('usr_dev', 'ten_dev', 'mfrieson@expertaiservices.com', 'Expert AI Services Builder') ON CONFLICT DO NOTHING;
INSERT INTO groups(id, tenant_id, business_instance_id, name, slug)
VALUES ('grp_admin', 'ten_dev', 'biz_dev', 'Admins', 'admins'), ('grp_eng', 'ten_dev', 'biz_dev', 'Engineering', 'engineering') ON CONFLICT DO NOTHING;
INSERT INTO group_memberships(tenant_id, group_id, user_id, role)
VALUES ('ten_dev', 'grp_admin', 'usr_dev', 'owner'), ('ten_dev', 'grp_eng', 'usr_dev', 'member') ON CONFLICT DO NOTHING;
INSERT INTO knowledge_bases(id, tenant_id, business_instance_id, name, slug) VALUES ('kb_dev', 'ten_dev', 'biz_dev', 'exai_vector_store KB', 'exai-vector-store') ON CONFLICT DO NOTHING;
INSERT INTO vector_stores(id, tenant_id, business_instance_id, knowledge_base_id, name, attributes)
VALUES ('vs_dev', 'ten_dev', 'biz_dev', 'kb_dev', 'Expert AI Services Vector Store', '{"environment":"local","project":"exai_vector_store","builder":"mfrieson@expertaiservices.com"}') ON CONFLICT DO NOTHING;
