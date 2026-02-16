"""Ticket saved views + updated_at trigger

Revision ID: 20260216_1600
Revises: 20260208_1700
Create Date: 2026-02-16
"""

from __future__ import annotations

from alembic import op

revision = "20260216_1600"
down_revision = "20260208_1700"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
CREATE TABLE IF NOT EXISTS ticket_saved_views (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  name text NOT NULL,
  filters_json jsonb NOT NULL DEFAULT '{}'::jsonb,
  is_default boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, name)
);
"""
    )
    op.execute(
        """
CREATE INDEX IF NOT EXISTS ticket_saved_views_org_idx
  ON ticket_saved_views (organization_id, created_at DESC);
"""
    )

    op.execute(
        """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'set_updated_at') THEN
    IF NOT EXISTS (
      SELECT 1 FROM pg_trigger WHERE tgname = 'set_updated_at_ticket_saved_views'
    ) THEN
      CREATE TRIGGER set_updated_at_ticket_saved_views
      BEFORE UPDATE ON ticket_saved_views
      FOR EACH ROW
      EXECUTE FUNCTION set_updated_at();
    END IF;
  END IF;
END $$;
"""
    )


def downgrade() -> None:
    # No downgrade support (early-stage schema; breaking changes allowed).
    pass
