"""OAuth states (one-time, expiring)

Revision ID: 20260208_1700
Revises: 20260208_1600
Create Date: 2026-02-08
"""

from __future__ import annotations

from alembic import op

revision = "20260208_1700"
down_revision = "20260208_1600"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
CREATE TABLE IF NOT EXISTS oauth_states (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider text NOT NULL,
  purpose text NOT NULL,
  state text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  used_at timestamptz,
  UNIQUE (state)
);
"""
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS oauth_states_lookup_idx ON oauth_states (state, expires_at, used_at);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS oauth_states_org_idx ON oauth_states (organization_id, created_at DESC);"
    )


def downgrade() -> None:
    # No downgrade support (early-stage schema; breaking changes allowed).
    pass
