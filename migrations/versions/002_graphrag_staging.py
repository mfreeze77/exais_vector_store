"""Add tenant-scoped GraphRAG staging tables."""

from __future__ import annotations

import os

from alembic import op
from sqlalchemy import text

revision = "002_graphrag_staging"
down_revision = "001_initial_schema"
branch_labels = None
depends_on = None


def _formatted(connection, template: str, *values: str) -> str:
    params = {f"value_{index}": value for index, value in enumerate(values)}
    placeholders = ", ".join(f"CAST(:value_{index} AS text)" for index in range(len(values)))
    return connection.execute(
        text(f"SELECT format(:template, {placeholders})"),
        {"template": template, **params},
    ).scalar_one()


def _grant_runtime_role(connection) -> None:
    user = os.getenv("POSTGRES_APP_USER", "svs_app")
    for table in ("graph_nodes", "graph_edges"):
        connection.exec_driver_sql(_formatted(connection, "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE %I TO %I", table, user))


def upgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        """
        CREATE TABLE IF NOT EXISTS graph_nodes (
          id TEXT NOT NULL,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          business_instance_id TEXT NOT NULL REFERENCES business_instances(id) ON DELETE CASCADE,
          vector_store_id TEXT NOT NULL REFERENCES vector_stores(id) ON DELETE CASCADE,
          node_type TEXT NOT NULL,
          node_key TEXT NOT NULL,
          label TEXT NOT NULL,
          attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
          provenance JSONB NOT NULL DEFAULT '[]'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, business_instance_id, vector_store_id, id)
        );

        CREATE TABLE IF NOT EXISTS graph_edges (
          id TEXT NOT NULL,
          tenant_id TEXT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
          business_instance_id TEXT NOT NULL REFERENCES business_instances(id) ON DELETE CASCADE,
          vector_store_id TEXT NOT NULL REFERENCES vector_stores(id) ON DELETE CASCADE,
          edge_type TEXT NOT NULL,
          source_node_id TEXT NOT NULL,
          target_node_id TEXT NOT NULL,
          attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
          provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          PRIMARY KEY (tenant_id, business_instance_id, vector_store_id, id),
          FOREIGN KEY (tenant_id, business_instance_id, vector_store_id, source_node_id)
            REFERENCES graph_nodes(tenant_id, business_instance_id, vector_store_id, id)
            ON DELETE CASCADE,
          FOREIGN KEY (tenant_id, business_instance_id, vector_store_id, target_node_id)
            REFERENCES graph_nodes(tenant_id, business_instance_id, vector_store_id, id)
            ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_graph_nodes_scope_type
          ON graph_nodes(tenant_id, business_instance_id, vector_store_id, node_type, node_key);
        CREATE INDEX IF NOT EXISTS idx_graph_edges_source
          ON graph_edges(tenant_id, business_instance_id, vector_store_id, source_node_id, edge_type);
        CREATE INDEX IF NOT EXISTS idx_graph_edges_target
          ON graph_edges(tenant_id, business_instance_id, vector_store_id, target_node_id, edge_type);
        CREATE INDEX IF NOT EXISTS idx_graph_edges_type
          ON graph_edges(tenant_id, business_instance_id, vector_store_id, edge_type);

        ALTER TABLE graph_nodes ENABLE ROW LEVEL SECURITY;
        ALTER TABLE graph_edges ENABLE ROW LEVEL SECURITY;
        ALTER TABLE graph_nodes FORCE ROW LEVEL SECURITY;
        ALTER TABLE graph_edges FORCE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS tenant_scope_graph_nodes ON graph_nodes;
        CREATE POLICY tenant_scope_graph_nodes ON graph_nodes
          USING (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id())
          WITH CHECK (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id());

        DROP POLICY IF EXISTS tenant_scope_graph_edges ON graph_edges;
        CREATE POLICY tenant_scope_graph_edges ON graph_edges
          USING (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id())
          WITH CHECK (tenant_id = svs_current_tenant_id() AND business_instance_id = svs_current_business_instance_id());
        """
    )
    _grant_runtime_role(connection)


def downgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        """
        DROP TABLE IF EXISTS graph_edges;
        DROP TABLE IF EXISTS graph_nodes;
        """
    )
