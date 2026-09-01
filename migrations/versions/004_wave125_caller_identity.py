"""WAVE-125: caller-provisioned users, user-bound API keys, and per-key attribution.

- users.external_id (caller-side id) with a unique index on (tenant_id, external_id)
- users.business_instance_id so a cell admin key only sees users it provisioned;
  CHECK (business_instance_id IS NULL OR external_id IS NOT NULL) makes the
  "caller-provisioned user" discriminator structural: every instance-scoped
  user has an external_id, and legacy tenant-level users (bootstrap admin) stay
  NULL/NULL
- users.email becomes nullable (external_id-only users have no email)
- users.deactivated_at / users.updated_at for the deactivate lifecycle
- usage_events.api_key_id and rate_limit_counters.{api_key_id,user_id} so usage
  and rate-limit rows carry the same attribution as audit_events already do

RLS review: `users` keeps the tenant-scoped `tenant_scope_users` policy from
db/migrations/004 (USING/WITH CHECK tenant_id = svs_current_tenant_id()); the
business-instance fence is applied in application SQL (svs_common.users). The
principal bootstrap in `resolve_api_key_principal` reads `users` only after the
tenant context is set, so the deactivation check is inside the policy.
`usage_events` and `rate_limit_counters` policies are unchanged; the new columns
are attribution data, not access-control inputs. The runtime role grant follows
db/migrations/999_grant_runtime_role.sh: ALTER DEFAULT PRIVILEGES already covers
new tables, and new columns inherit table grants, so the explicit re-grant below
is idempotent belt-and-braces for cells where the owner role changed.
"""

from __future__ import annotations

import os

from alembic import op
from sqlalchemy import text

revision = "004_wave125_caller_identity"
down_revision = "003_expert_conversation_sessions"
branch_labels = None
depends_on = None


TOUCHED_TABLES = ("users", "api_keys", "usage_events", "rate_limit_counters", "audit_events")


def _formatted(connection, template: str, *values: str) -> str:
    params = {f"value_{index}": value for index, value in enumerate(values)}
    placeholders = ", ".join(f"CAST(:value_{index} AS text)" for index in range(len(values)))
    return connection.execute(
        text(f"SELECT format(:template, {placeholders})"),
        {"template": template, **params},
    ).scalar_one()


def _grant_runtime_role(connection) -> None:
    user = os.getenv("POSTGRES_APP_USER", "svs_app")
    for table in TOUCHED_TABLES:
        connection.exec_driver_sql(
            _formatted(connection, "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE %I TO %I", table, user)
        )


def upgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql(
        """
        ALTER TABLE users ADD COLUMN IF NOT EXISTS external_id TEXT;
        ALTER TABLE users ADD COLUMN IF NOT EXISTS business_instance_id TEXT
          REFERENCES business_instances(id) ON DELETE CASCADE;
        ALTER TABLE users ADD COLUMN IF NOT EXISTS deactivated_at TIMESTAMPTZ;
        ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now();
        ALTER TABLE users ALTER COLUMN email DROP NOT NULL;
        ALTER TABLE users DROP CONSTRAINT IF EXISTS users_external_id_not_blank;
        ALTER TABLE users ADD CONSTRAINT users_external_id_not_blank
          CHECK (external_id IS NULL OR btrim(external_id) <> '');
        ALTER TABLE users DROP CONSTRAINT IF EXISTS users_instance_user_has_external_id;
        ALTER TABLE users ADD CONSTRAINT users_instance_user_has_external_id
          CHECK (business_instance_id IS NULL OR external_id IS NOT NULL);

        CREATE UNIQUE INDEX IF NOT EXISTS uq_users_tenant_external_id
          ON users(tenant_id, external_id)
          WHERE external_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS idx_users_instance_created
          ON users(tenant_id, business_instance_id, created_at DESC, id DESC);

        ALTER TABLE usage_events ADD COLUMN IF NOT EXISTS api_key_id TEXT;
        CREATE INDEX IF NOT EXISTS idx_usage_events_scope_user
          ON usage_events(tenant_id, business_instance_id, user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_usage_events_scope_api_key
          ON usage_events(tenant_id, business_instance_id, api_key_id, created_at DESC);

        ALTER TABLE rate_limit_counters ADD COLUMN IF NOT EXISTS api_key_id TEXT;
        ALTER TABLE rate_limit_counters ADD COLUMN IF NOT EXISTS user_id TEXT;

        CREATE INDEX IF NOT EXISTS idx_api_keys_scope_user
          ON api_keys(tenant_id, business_instance_id, user_id, created_at DESC);
        """
    )
    _grant_runtime_role(connection)


def _ensure_no_null_emails(connection) -> None:
    """Downgrade restores ``users.email NOT NULL``; refuse loudly if data would violate it."""
    null_emails = int(connection.execute(text("SELECT count(*) FROM users WHERE email IS NULL")).scalar_one() or 0)
    if null_emails:
        raise RuntimeError(
            f"cannot downgrade 004_wave125_caller_identity: {null_emails} users row(s) have NULL email; "
            "set an email (or delete those caller-provisioned users) before restoring NOT NULL"
        )


def downgrade() -> None:
    connection = op.get_bind()
    _ensure_no_null_emails(connection)
    connection.exec_driver_sql(
        """
        ALTER TABLE users ALTER COLUMN email SET NOT NULL;
        DROP INDEX IF EXISTS idx_api_keys_scope_user;
        ALTER TABLE rate_limit_counters DROP COLUMN IF EXISTS user_id;
        ALTER TABLE rate_limit_counters DROP COLUMN IF EXISTS api_key_id;
        DROP INDEX IF EXISTS idx_usage_events_scope_api_key;
        DROP INDEX IF EXISTS idx_usage_events_scope_user;
        ALTER TABLE usage_events DROP COLUMN IF EXISTS api_key_id;
        DROP INDEX IF EXISTS idx_users_instance_created;
        DROP INDEX IF EXISTS uq_users_tenant_external_id;
        ALTER TABLE users DROP CONSTRAINT IF EXISTS users_instance_user_has_external_id;
        ALTER TABLE users DROP CONSTRAINT IF EXISTS users_external_id_not_blank;
        ALTER TABLE users DROP COLUMN IF EXISTS updated_at;
        ALTER TABLE users DROP COLUMN IF EXISTS deactivated_at;
        ALTER TABLE users DROP COLUMN IF EXISTS business_instance_id;
        ALTER TABLE users DROP COLUMN IF EXISTS external_id;
        """
    )
