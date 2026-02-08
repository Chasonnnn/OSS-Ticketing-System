"""Auth sessions + audit events + updated_at triggers

Revision ID: 20260208_1600
Revises: 20260208_1500
Create Date: 2026-02-08
"""

from __future__ import annotations

from alembic import op

revision = "20260208_1600"
down_revision = "20260208_1500"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
CREATE TABLE IF NOT EXISTS auth_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  active_organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  token_hash bytea NOT NULL,

  created_at timestamptz NOT NULL DEFAULT now(),
  last_seen_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,

  revoked_at timestamptz,
  revoked_reason text,

  UNIQUE (token_hash)
);
"""
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS auth_sessions_user_idx ON auth_sessions (user_id, revoked_at, expires_at);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS auth_sessions_org_idx ON auth_sessions (active_organization_id, revoked_at, expires_at);"
    )

    op.execute(
        """
CREATE TABLE IF NOT EXISTS audit_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  actor_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  event_type text NOT NULL,
  event_data jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);
"""
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS audit_events_org_created_idx ON audit_events (organization_id, created_at DESC);"
    )

    # Keep updated_at consistent even for raw SQL updates (worker code, etc.).
    op.execute(
        """
CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""
    )

    for table in (
        "oauth_credentials",
        "mailboxes",
        "send_identities",
        "routing_rules",
        "tickets",
        "ticket_notes",
        "bg_jobs",
    ):
        op.execute(
            f"""
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_trigger WHERE tgname = 'set_updated_at_{table}'
  ) THEN
    CREATE TRIGGER set_updated_at_{table}
    BEFORE UPDATE ON {table}
    FOR EACH ROW
    EXECUTE FUNCTION set_updated_at();
  END IF;
END $$;
"""
        )


def downgrade() -> None:
    # No downgrade support (early-stage schema; breaking changes allowed).
    pass
