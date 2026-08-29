"""Add scoped persistence for expert conversations and forks."""

from __future__ import annotations

import os

from alembic import op
from sqlalchemy import text

revision = "003_expert_conversation_sessions"
down_revision = "002_graphrag_staging"
branch_labels = None
depends_on = None


EXPERT_TABLES = (
    "expert_sessions",
    "expert_messages",
    "expert_tool_calls",
    "expert_retrieval_runs",
    "expert_feedback",
    "expert_memory_events",
    "expert_session_forks",
)


def _formatted(connection, template: str, *values: str) -> str:
    params = {f"value_{index}": value for index, value in enumerate(values)}
    placeholders = ", ".join(f"CAST(:value_{index} AS text)" for index in range(len(values)))
    return connection.execute(
        text(f"SELECT format(:template, {placeholders})"),
        {"template": template, **params},
    ).scalar_one()


def _grant_runtime_role(connection) -> None:
    user = os.getenv("POSTGRES_APP_USER", "svs_app")
    for table in EXPERT_TABLES:
        connection.exec_driver_sql(
            _formatted(connection, "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE %I TO %I", table, user)
        )


def _enable_scoped_rls(connection) -> None:
    for table in EXPERT_TABLES:
        policy = f"expert_scope_{table}"
        connection.exec_driver_sql(_formatted(connection, "ALTER TABLE %I ENABLE ROW LEVEL SECURITY", table))
        connection.exec_driver_sql(_formatted(connection, "ALTER TABLE %I FORCE ROW LEVEL SECURITY", table))
        connection.exec_driver_sql(_formatted(connection, "DROP POLICY IF EXISTS %I ON %I", policy, table))
        connection.exec_driver_sql(
            _formatted(
                connection,
                """
                CREATE POLICY %I ON %I
                  USING (
                    tenant_id = svs_current_tenant_id()
                    AND business_instance_id = svs_current_business_instance_id()
                    AND api_key_id IS NOT DISTINCT FROM svs_current_api_key_id()
                    AND user_id IS NOT DISTINCT FROM svs_current_user_id()
                  )
                  WITH CHECK (
                    tenant_id = svs_current_tenant_id()
                    AND business_instance_id = svs_current_business_instance_id()
                    AND api_key_id IS NOT DISTINCT FROM svs_current_api_key_id()
                    AND user_id IS NOT DISTINCT FROM svs_current_user_id()
                  )
                """,
                policy,
                table,
            )
        )


def upgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        """
        CREATE OR REPLACE FUNCTION svs_current_api_key_id() RETURNS TEXT
        LANGUAGE sql STABLE AS $$
          SELECT nullif(current_setting('svs.api_key_id', true), '')::TEXT;
        $$;

        CREATE OR REPLACE FUNCTION svs_current_user_id() RETURNS TEXT
        LANGUAGE sql STABLE AS $$
          SELECT nullif(current_setting('svs.user_id', true), '')::TEXT;
        $$;

        CREATE TABLE expert_sessions (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          business_instance_id TEXT NOT NULL REFERENCES business_instances(id) ON DELETE CASCADE,
          api_key_id TEXT,
          user_id TEXT,
          expert_id TEXT NOT NULL CHECK (btrim(expert_id) <> ''),
          external_user_id TEXT,
          conversation_id TEXT,
          session_key TEXT NOT NULL CHECK (btrim(session_key) <> ''),
          label TEXT,
          parent_session_id TEXT,
          status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived', 'deleted')),
          metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          last_active_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (tenant_id, business_instance_id, id),
          UNIQUE (tenant_id, business_instance_id, session_key),
          UNIQUE (tenant_id, business_instance_id, id, session_key),
          FOREIGN KEY (tenant_id, business_instance_id, parent_session_id)
            REFERENCES expert_sessions(tenant_id, business_instance_id, id)
            ON DELETE RESTRICT
        );

        CREATE TABLE expert_messages (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          business_instance_id TEXT NOT NULL REFERENCES business_instances(id) ON DELETE CASCADE,
          api_key_id TEXT,
          user_id TEXT,
          expert_id TEXT NOT NULL,
          external_user_id TEXT,
          conversation_id TEXT,
          session_id TEXT NOT NULL,
          session_key TEXT NOT NULL,
          source_message_id TEXT,
          role TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant', 'tool')),
          content JSONB NOT NULL,
          sequence_no INT NOT NULL CHECK (sequence_no >= 0),
          metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (tenant_id, business_instance_id, session_id, id),
          UNIQUE (tenant_id, business_instance_id, session_id, sequence_no),
          FOREIGN KEY (tenant_id, business_instance_id, session_id, session_key)
            REFERENCES expert_sessions(tenant_id, business_instance_id, id, session_key)
            ON DELETE CASCADE
        );

        CREATE TABLE expert_tool_calls (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          business_instance_id TEXT NOT NULL REFERENCES business_instances(id) ON DELETE CASCADE,
          api_key_id TEXT,
          user_id TEXT,
          expert_id TEXT NOT NULL,
          external_user_id TEXT,
          conversation_id TEXT,
          session_id TEXT NOT NULL,
          session_key TEXT NOT NULL,
          message_id TEXT,
          source_tool_call_id TEXT,
          tool_name TEXT NOT NULL CHECK (btrim(tool_name) <> ''),
          status TEXT NOT NULL DEFAULT 'completed'
            CHECK (status IN ('pending', 'running', 'completed', 'failed')),
          input JSONB NOT NULL DEFAULT '{}'::jsonb,
          output JSONB,
          error TEXT,
          sequence_no INT NOT NULL CHECK (sequence_no >= 0),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          completed_at TIMESTAMPTZ,
          UNIQUE (tenant_id, business_instance_id, session_id, id),
          UNIQUE (tenant_id, business_instance_id, session_id, sequence_no),
          FOREIGN KEY (tenant_id, business_instance_id, session_id, session_key)
            REFERENCES expert_sessions(tenant_id, business_instance_id, id, session_key)
            ON DELETE CASCADE,
          FOREIGN KEY (tenant_id, business_instance_id, session_id, message_id)
            REFERENCES expert_messages(tenant_id, business_instance_id, session_id, id)
            ON DELETE SET NULL (message_id)
        );

        CREATE TABLE expert_retrieval_runs (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          business_instance_id TEXT NOT NULL REFERENCES business_instances(id) ON DELETE CASCADE,
          api_key_id TEXT,
          user_id TEXT,
          expert_id TEXT NOT NULL,
          external_user_id TEXT,
          conversation_id TEXT,
          session_id TEXT NOT NULL,
          session_key TEXT NOT NULL,
          message_id TEXT,
          tool_call_id TEXT,
          source_retrieval_run_id TEXT,
          sequence_no INT NOT NULL CHECK (sequence_no >= 0),
          payload JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (tenant_id, business_instance_id, session_id, id),
          UNIQUE (tenant_id, business_instance_id, session_id, sequence_no),
          FOREIGN KEY (tenant_id, business_instance_id, session_id, session_key)
            REFERENCES expert_sessions(tenant_id, business_instance_id, id, session_key)
            ON DELETE CASCADE,
          FOREIGN KEY (tenant_id, business_instance_id, session_id, message_id)
            REFERENCES expert_messages(tenant_id, business_instance_id, session_id, id)
            ON DELETE SET NULL (message_id),
          FOREIGN KEY (tenant_id, business_instance_id, session_id, tool_call_id)
            REFERENCES expert_tool_calls(tenant_id, business_instance_id, session_id, id)
            ON DELETE SET NULL (tool_call_id)
        );

        CREATE TABLE expert_feedback (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          business_instance_id TEXT NOT NULL REFERENCES business_instances(id) ON DELETE CASCADE,
          api_key_id TEXT,
          user_id TEXT,
          expert_id TEXT NOT NULL,
          external_user_id TEXT,
          conversation_id TEXT,
          session_id TEXT NOT NULL,
          session_key TEXT NOT NULL,
          message_id TEXT,
          feedback_type TEXT NOT NULL CHECK (btrim(feedback_type) <> ''),
          rating INT,
          comment TEXT,
          payload JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (tenant_id, business_instance_id, session_id, id),
          FOREIGN KEY (tenant_id, business_instance_id, session_id, session_key)
            REFERENCES expert_sessions(tenant_id, business_instance_id, id, session_key)
            ON DELETE CASCADE,
          FOREIGN KEY (tenant_id, business_instance_id, session_id, message_id)
            REFERENCES expert_messages(tenant_id, business_instance_id, session_id, id)
            ON DELETE SET NULL (message_id)
        );

        CREATE TABLE expert_memory_events (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          business_instance_id TEXT NOT NULL REFERENCES business_instances(id) ON DELETE CASCADE,
          api_key_id TEXT,
          user_id TEXT,
          expert_id TEXT NOT NULL,
          external_user_id TEXT,
          conversation_id TEXT,
          session_id TEXT NOT NULL,
          session_key TEXT NOT NULL,
          source_message_id TEXT,
          source_feedback_id TEXT,
          event_type TEXT NOT NULL CHECK (btrim(event_type) <> ''),
          status TEXT NOT NULL DEFAULT 'candidate'
            CHECK (status IN ('candidate', 'promoted', 'rejected', 'deleted')),
          payload JSONB NOT NULL DEFAULT '{}'::jsonb,
          confidence DOUBLE PRECISION CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          promoted_at TIMESTAMPTZ,
          deleted_at TIMESTAMPTZ,
          UNIQUE (tenant_id, business_instance_id, session_id, id),
          FOREIGN KEY (tenant_id, business_instance_id, session_id, session_key)
            REFERENCES expert_sessions(tenant_id, business_instance_id, id, session_key)
            ON DELETE CASCADE,
          FOREIGN KEY (tenant_id, business_instance_id, session_id, source_message_id)
            REFERENCES expert_messages(tenant_id, business_instance_id, session_id, id)
            ON DELETE SET NULL (source_message_id),
          FOREIGN KEY (tenant_id, business_instance_id, session_id, source_feedback_id)
            REFERENCES expert_feedback(tenant_id, business_instance_id, session_id, id)
            ON DELETE SET NULL (source_feedback_id)
        );

        CREATE TABLE expert_session_forks (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          business_instance_id TEXT NOT NULL REFERENCES business_instances(id) ON DELETE CASCADE,
          api_key_id TEXT,
          user_id TEXT,
          expert_id TEXT NOT NULL,
          external_user_id TEXT,
          conversation_id TEXT,
          parent_session_id TEXT NOT NULL,
          parent_session_key TEXT NOT NULL,
          child_session_id TEXT NOT NULL,
          child_session_key TEXT NOT NULL,
          label TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (tenant_id, business_instance_id, child_session_id),
          FOREIGN KEY (tenant_id, business_instance_id, parent_session_id, parent_session_key)
            REFERENCES expert_sessions(tenant_id, business_instance_id, id, session_key)
            ON DELETE RESTRICT,
          FOREIGN KEY (tenant_id, business_instance_id, child_session_id, child_session_key)
            REFERENCES expert_sessions(tenant_id, business_instance_id, id, session_key)
            ON DELETE CASCADE
        );

        CREATE INDEX idx_expert_sessions_resume
          ON expert_sessions(
            tenant_id, business_instance_id, api_key_id, user_id,
            expert_id, external_user_id, conversation_id, last_active_at DESC
          );
        CREATE INDEX idx_expert_sessions_parent
          ON expert_sessions(tenant_id, business_instance_id, parent_session_id);
        CREATE INDEX idx_expert_messages_context
          ON expert_messages(tenant_id, business_instance_id, session_id, sequence_no);
        CREATE INDEX idx_expert_tool_calls_context
          ON expert_tool_calls(tenant_id, business_instance_id, session_id, sequence_no);
        CREATE INDEX idx_expert_retrieval_runs_context
          ON expert_retrieval_runs(tenant_id, business_instance_id, session_id, sequence_no);
        CREATE INDEX idx_expert_feedback_session
          ON expert_feedback(tenant_id, business_instance_id, session_id, created_at);
        CREATE INDEX idx_expert_memory_events_session
          ON expert_memory_events(tenant_id, business_instance_id, session_id, status, created_at);
        CREATE INDEX idx_expert_session_forks_parent
          ON expert_session_forks(tenant_id, business_instance_id, parent_session_id, created_at);
        """
    )
    _enable_scoped_rls(connection)
    _grant_runtime_role(connection)


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        """
        DROP TABLE IF EXISTS expert_session_forks;
        DROP TABLE IF EXISTS expert_memory_events;
        DROP TABLE IF EXISTS expert_feedback;
        DROP TABLE IF EXISTS expert_retrieval_runs;
        DROP TABLE IF EXISTS expert_tool_calls;
        DROP TABLE IF EXISTS expert_messages;
        DROP TABLE IF EXISTS expert_sessions;
        DROP FUNCTION IF EXISTS svs_current_user_id();
        DROP FUNCTION IF EXISTS svs_current_api_key_id();
        """
    )
