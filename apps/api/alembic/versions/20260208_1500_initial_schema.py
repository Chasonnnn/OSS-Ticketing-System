"""Initial schema (org, tickets, messages, occurrences, jobs)

Revision ID: 20260208_1500
Revises:
Create Date: 2026-02-08

"""

from __future__ import annotations

from alembic import op

revision = "20260208_1500"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")
    op.execute("CREATE EXTENSION IF NOT EXISTS citext;")

    op.execute(
        """
DO $$ BEGIN
  CREATE TYPE membership_role AS ENUM ('admin','agent','viewer');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
"""
    )
    op.execute(
        """
DO $$ BEGIN
  CREATE TYPE mailbox_purpose AS ENUM ('journal','user');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
"""
    )
    op.execute(
        """
DO $$ BEGIN
  CREATE TYPE mailbox_provider AS ENUM ('gmail');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
"""
    )
    op.execute(
        """
DO $$ BEGIN
  CREATE TYPE send_identity_status AS ENUM ('pending','verified','failed');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
"""
    )
    op.execute(
        """
DO $$ BEGIN
  CREATE TYPE blob_kind AS ENUM ('raw_eml','attachment');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
"""
    )
    op.execute(
        """
DO $$ BEGIN
  CREATE TYPE message_direction AS ENUM ('inbound','outbound');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
"""
    )
    op.execute(
        """
DO $$ BEGIN
  CREATE TYPE occurrence_state AS ENUM ('discovered','raw_fetched','parsed','stitched','routed','failed');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
"""
    )
    op.execute(
        """
DO $$ BEGIN
  CREATE TYPE routing_recipient_source AS ENUM ('workspace_header','delivered_to','x_original_to','to_cc_scan','unknown');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
"""
    )
    op.execute(
        """
DO $$ BEGIN
  CREATE TYPE routing_confidence AS ENUM ('high','medium','low');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
"""
    )
    op.execute(
        """
DO $$ BEGIN
  CREATE TYPE ticket_status AS ENUM ('new','open','pending','resolved','closed','spam');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
"""
    )
    op.execute(
        """
DO $$ BEGIN
  CREATE TYPE ticket_priority AS ENUM ('low','normal','high','urgent');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
"""
    )
    op.execute(
        """
DO $$ BEGIN
  CREATE TYPE job_status AS ENUM ('queued','running','succeeded','failed','cancelled');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
"""
    )
    op.execute(
        """
DO $$ BEGIN
  CREATE TYPE job_type AS ENUM (
    'mailbox_backfill',
    'mailbox_history_sync',
    'mailbox_watch_renew',
    'occurrence_fetch_raw',
    'occurrence_parse',
    'occurrence_stitch',
    'ticket_apply_routing',
    'outbound_send'
  );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
"""
    )

    op.execute(
        """
CREATE TABLE IF NOT EXISTS organizations (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL,
  primary_domain citext,
  created_at timestamptz NOT NULL DEFAULT now()
);
"""
    )
    op.execute(
        """
CREATE UNIQUE INDEX IF NOT EXISTS organizations_primary_domain_uq
  ON organizations (primary_domain)
  WHERE primary_domain IS NOT NULL;
"""
    )

    op.execute(
        """
CREATE TABLE IF NOT EXISTS users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email citext NOT NULL,
  display_name text,
  is_disabled boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now()
);
"""
    )
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS users_email_uq ON users (email);")

    op.execute(
        """
CREATE TABLE IF NOT EXISTS memberships (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  role membership_role NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, user_id)
);
"""
    )

    op.execute(
        """
CREATE TABLE IF NOT EXISTS queues (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  name text NOT NULL,
  slug text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, slug)
);
"""
    )

    op.execute(
        """
CREATE TABLE IF NOT EXISTS queue_memberships (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  queue_id uuid NOT NULL REFERENCES queues(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, queue_id, user_id)
);
"""
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS queue_memberships_user_idx ON queue_memberships (organization_id, user_id);"
    )

    op.execute(
        """
CREATE TABLE IF NOT EXISTS oauth_credentials (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  provider text NOT NULL CHECK (provider IN ('google')),
  subject text NOT NULL,
  scopes text[] NOT NULL,
  encrypted_refresh_token bytea NOT NULL,
  encrypted_access_token bytea,
  access_token_expires_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, provider, subject)
);
"""
    )

    op.execute(
        """
CREATE TABLE IF NOT EXISTS mailboxes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  purpose mailbox_purpose NOT NULL,
  provider mailbox_provider NOT NULL,
  email_address citext NOT NULL,
  display_name text,
  oauth_credential_id uuid NOT NULL REFERENCES oauth_credentials(id) ON DELETE RESTRICT,
  is_enabled boolean NOT NULL DEFAULT true,

  ingestion_paused_until timestamptz,
  ingestion_pause_reason text,

  gmail_history_id bigint,
  gmail_watch_expiration timestamptz,
  gmail_watch_resource_id text,
  gmail_profile_email citext,
  last_incremental_sync_at timestamptz,
  last_full_sync_at timestamptz,
  last_sync_error text,

  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),

  UNIQUE (organization_id, email_address)
);
"""
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS mailboxes_sync_idx ON mailboxes (organization_id, is_enabled, last_incremental_sync_at);"
    )

    op.execute(
        """
CREATE TABLE IF NOT EXISTS send_identities (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  mailbox_id uuid NOT NULL REFERENCES mailboxes(id) ON DELETE CASCADE,
  from_email citext NOT NULL,
  from_name text,
  gmail_send_as_id text NOT NULL,
  status send_identity_status NOT NULL DEFAULT 'pending',
  is_enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, from_email)
);
"""
    )

    op.execute(
        """
CREATE TABLE IF NOT EXISTS blobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  kind blob_kind NOT NULL,
  sha256 bytea NOT NULL,
  size_bytes bigint NOT NULL,
  storage_key text NOT NULL,
  content_type text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, kind, sha256)
);
"""
    )
    op.execute("CREATE INDEX IF NOT EXISTS blobs_sha_idx ON blobs (organization_id, sha256);")

    op.execute(
        """
CREATE TABLE IF NOT EXISTS messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

  direction message_direction NOT NULL,
  oss_message_id uuid,
  rfc_message_id text,

  fingerprint_v1 bytea NOT NULL,
  signature_v1 bytea NOT NULL,

  collision_group_id uuid,

  created_at timestamptz NOT NULL DEFAULT now(),
  first_seen_at timestamptz NOT NULL DEFAULT now(),

  UNIQUE (organization_id, oss_message_id)
);
"""
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS messages_org_created_idx ON messages (organization_id, created_at DESC);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS messages_rfc_message_id_idx ON messages (organization_id, rfc_message_id) WHERE rfc_message_id IS NOT NULL;"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS messages_fingerprint_idx ON messages (organization_id, fingerprint_v1);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS messages_signature_idx ON messages (organization_id, signature_v1);"
    )

    op.execute(
        """
CREATE TABLE IF NOT EXISTS message_oss_ids (
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  oss_message_id uuid NOT NULL,
  message_id uuid NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (organization_id, oss_message_id)
);
"""
    )

    op.execute(
        """
CREATE TABLE IF NOT EXISTS message_rfc_ids (
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  rfc_message_id text NOT NULL,
  signature_v1 bytea NOT NULL,
  message_id uuid NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (organization_id, rfc_message_id, signature_v1)
);
"""
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS message_rfc_ids_lookup_idx ON message_rfc_ids (organization_id, rfc_message_id);"
    )

    op.execute(
        """
CREATE TABLE IF NOT EXISTS message_fingerprints (
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  fingerprint_version int NOT NULL,
  fingerprint bytea NOT NULL,
  signature_v1 bytea NOT NULL,
  message_id uuid NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (organization_id, fingerprint_version, fingerprint, signature_v1)
);
"""
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS message_fingerprints_lookup_idx ON message_fingerprints (organization_id, fingerprint_version, fingerprint);"
    )

    op.execute(
        """
CREATE TABLE IF NOT EXISTS message_contents (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  message_id uuid NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  content_version int NOT NULL,
  parser_version int NOT NULL,
  parsed_at timestamptz NOT NULL DEFAULT now(),

  date_header timestamptz,
  subject text,
  subject_norm text,
  from_email citext,
  from_name text,
  reply_to_emails citext[] NOT NULL DEFAULT '{}'::citext[],
  to_emails citext[] NOT NULL DEFAULT '{}'::citext[],
  cc_emails citext[] NOT NULL DEFAULT '{}'::citext[],

  headers_json jsonb NOT NULL DEFAULT '{}'::jsonb,

  body_text text,
  body_html_sanitized text,

  has_attachments boolean NOT NULL DEFAULT false,
  attachment_count int NOT NULL DEFAULT 0,

  snippet text,

  search_tsv tsvector GENERATED ALWAYS AS (
    to_tsvector('english', coalesce(subject,'') || ' ' || coalesce(body_text,''))
  ) STORED,

  UNIQUE (organization_id, message_id, content_version)
);
"""
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS message_contents_search_idx ON message_contents USING gin (search_tsv);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS message_contents_from_idx ON message_contents (organization_id, from_email);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS message_contents_date_idx ON message_contents (organization_id, date_header DESC);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS message_contents_to_gin_idx ON message_contents USING gin (to_emails);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS message_contents_cc_gin_idx ON message_contents USING gin (cc_emails);"
    )

    op.execute(
        """
CREATE TABLE IF NOT EXISTS message_attachments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  message_id uuid NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  blob_id uuid NOT NULL REFERENCES blobs(id) ON DELETE RESTRICT,
  filename text,
  content_type text,
  size_bytes bigint NOT NULL,
  sha256 bytea NOT NULL,
  is_inline boolean NOT NULL DEFAULT false,
  content_id text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, message_id, blob_id)
);
"""
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS message_attachments_msg_idx ON message_attachments (organization_id, message_id);"
    )

    op.execute(
        """
CREATE TABLE IF NOT EXISTS message_thread_refs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  message_id uuid NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
  ref_type text NOT NULL CHECK (ref_type IN ('in_reply_to','references')),
  ref_rfc_message_id text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, message_id, ref_type, ref_rfc_message_id)
);
"""
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS message_thread_refs_ref_idx ON message_thread_refs (organization_id, ref_rfc_message_id);"
    )

    op.execute(
        """
CREATE TABLE IF NOT EXISTS tickets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  ticket_code text NOT NULL,

  status ticket_status NOT NULL DEFAULT 'new',
  priority ticket_priority NOT NULL DEFAULT 'normal',

  subject text,
  subject_norm text,

  requester_email citext,
  requester_name text,

  assignee_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  assignee_queue_id uuid REFERENCES queues(id) ON DELETE SET NULL,

  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  first_message_at timestamptz,
  last_message_at timestamptz,
  last_activity_at timestamptz,
  closed_at timestamptz,

  stitch_reason text,
  stitch_confidence routing_confidence NOT NULL DEFAULT 'low',

  UNIQUE (organization_id, ticket_code)
);
"""
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS tickets_inbox_idx ON tickets (organization_id, status, last_activity_at DESC);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS tickets_assignee_user_idx ON tickets (organization_id, assignee_user_id, status);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS tickets_assignee_queue_idx ON tickets (organization_id, assignee_queue_id, status);"
    )

    op.execute(
        """
CREATE TABLE IF NOT EXISTS ticket_messages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  ticket_id uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
  message_id uuid NOT NULL REFERENCES messages(id) ON DELETE RESTRICT,
  stitched_at timestamptz NOT NULL DEFAULT now(),
  stitch_reason text NOT NULL,
  stitch_confidence routing_confidence NOT NULL,
  UNIQUE (organization_id, message_id),
  UNIQUE (organization_id, ticket_id, message_id)
);
"""
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ticket_messages_ticket_idx ON ticket_messages (organization_id, ticket_id, stitched_at);"
    )

    op.execute(
        """
CREATE TABLE IF NOT EXISTS ticket_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  ticket_id uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
  actor_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  event_type text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  event_data jsonb NOT NULL DEFAULT '{}'::jsonb
);
"""
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ticket_events_ticket_idx ON ticket_events (organization_id, ticket_id, created_at DESC);"
    )

    op.execute(
        """
CREATE TABLE IF NOT EXISTS ticket_notes (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  ticket_id uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
  author_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  body_markdown text NOT NULL,
  body_html_sanitized text,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
"""
    )

    op.execute(
        """
CREATE TABLE IF NOT EXISTS tags (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  name text NOT NULL,
  color text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, name)
);
"""
    )

    op.execute(
        """
CREATE TABLE IF NOT EXISTS ticket_tags (
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  ticket_id uuid NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
  tag_id uuid NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (organization_id, ticket_id, tag_id)
);
"""
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ticket_tags_tag_idx ON ticket_tags (organization_id, tag_id);"
    )

    op.execute(
        """
CREATE TABLE IF NOT EXISTS recipient_allowlist (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  pattern text NOT NULL,
  is_enabled boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (organization_id, pattern)
);
"""
    )

    op.execute(
        """
CREATE TABLE IF NOT EXISTS routing_rules (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  name text NOT NULL,
  is_enabled boolean NOT NULL DEFAULT true,
  priority int NOT NULL DEFAULT 100,

  match_recipient_pattern text,
  match_sender_domain_pattern text,
  match_sender_email_pattern text,
  match_direction message_direction,

  action_assign_queue_id uuid REFERENCES queues(id) ON DELETE SET NULL,
  action_assign_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  action_set_status ticket_status,
  action_drop boolean NOT NULL DEFAULT false,
  action_auto_close boolean NOT NULL DEFAULT false,

  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
"""
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS routing_rules_eval_idx ON routing_rules (organization_id, is_enabled, priority);"
    )

    op.execute(
        """
CREATE TABLE IF NOT EXISTS routing_rule_add_tags (
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  routing_rule_id uuid NOT NULL REFERENCES routing_rules(id) ON DELETE CASCADE,
  tag_id uuid NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (organization_id, routing_rule_id, tag_id)
);
"""
    )

    op.execute(
        """
CREATE TABLE IF NOT EXISTS message_occurrences (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
  mailbox_id uuid NOT NULL REFERENCES mailboxes(id) ON DELETE CASCADE,

  gmail_message_id text NOT NULL,
  gmail_thread_id text,
  gmail_history_id bigint,
  gmail_internal_date timestamptz,
  label_ids text[] NOT NULL DEFAULT '{}'::text[],

  state occurrence_state NOT NULL DEFAULT 'discovered',

  raw_blob_id uuid REFERENCES blobs(id) ON DELETE SET NULL,
  raw_fetched_at timestamptz,
  raw_fetch_error text,

  message_id uuid REFERENCES messages(id) ON DELETE SET NULL,
  parsed_at timestamptz,
  parse_error text,

  ticket_id uuid REFERENCES tickets(id) ON DELETE SET NULL,
  stitched_at timestamptz,
  stitch_error text,

  routed_at timestamptz,
  route_error text,

  original_recipient citext,
  original_recipient_source routing_recipient_source NOT NULL DEFAULT 'unknown',
  original_recipient_confidence routing_confidence NOT NULL DEFAULT 'low',
  original_recipient_evidence jsonb NOT NULL DEFAULT '{}'::jsonb,

  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),

  UNIQUE (organization_id, mailbox_id, gmail_message_id)
);
"""
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS message_occurrences_thread_idx ON message_occurrences (organization_id, gmail_thread_id);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS message_occurrences_state_idx ON message_occurrences (organization_id, state);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS message_occurrences_message_idx ON message_occurrences (organization_id, message_id);"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS message_occurrences_ticket_idx ON message_occurrences (organization_id, ticket_id);"
    )

    op.execute(
        """
CREATE TABLE IF NOT EXISTS bg_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  organization_id uuid REFERENCES organizations(id) ON DELETE CASCADE,
  mailbox_id uuid REFERENCES mailboxes(id) ON DELETE CASCADE,

  type job_type NOT NULL,
  status job_status NOT NULL DEFAULT 'queued',

  run_at timestamptz NOT NULL DEFAULT now(),
  attempts int NOT NULL DEFAULT 0,
  max_attempts int NOT NULL DEFAULT 25,

  locked_at timestamptz,
  locked_by text,
  last_error text,

  dedupe_key text,
  payload jsonb NOT NULL DEFAULT '{}'::jsonb,

  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
"""
    )
    op.execute("CREATE INDEX IF NOT EXISTS bg_jobs_runner_idx ON bg_jobs (status, run_at);")
    op.execute(
        "CREATE INDEX IF NOT EXISTS bg_jobs_mailbox_idx ON bg_jobs (organization_id, mailbox_id, status);"
    )
    op.execute(
        """
CREATE UNIQUE INDEX IF NOT EXISTS bg_jobs_dedupe_uq
  ON bg_jobs (organization_id, type, dedupe_key)
  WHERE dedupe_key IS NOT NULL AND status IN ('queued','running');
"""
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS bg_jobs CASCADE;")
    op.execute("DROP TABLE IF EXISTS message_occurrences CASCADE;")
    op.execute("DROP TABLE IF EXISTS routing_rule_add_tags CASCADE;")
    op.execute("DROP TABLE IF EXISTS routing_rules CASCADE;")
    op.execute("DROP TABLE IF EXISTS recipient_allowlist CASCADE;")
    op.execute("DROP TABLE IF EXISTS ticket_tags CASCADE;")
    op.execute("DROP TABLE IF EXISTS tags CASCADE;")
    op.execute("DROP TABLE IF EXISTS ticket_notes CASCADE;")
    op.execute("DROP TABLE IF EXISTS ticket_events CASCADE;")
    op.execute("DROP TABLE IF EXISTS ticket_messages CASCADE;")
    op.execute("DROP TABLE IF EXISTS tickets CASCADE;")
    op.execute("DROP TABLE IF EXISTS message_thread_refs CASCADE;")
    op.execute("DROP TABLE IF EXISTS message_attachments CASCADE;")
    op.execute("DROP TABLE IF EXISTS message_contents CASCADE;")
    op.execute("DROP TABLE IF EXISTS message_fingerprints CASCADE;")
    op.execute("DROP TABLE IF EXISTS message_rfc_ids CASCADE;")
    op.execute("DROP TABLE IF EXISTS message_oss_ids CASCADE;")
    op.execute("DROP TABLE IF EXISTS messages CASCADE;")
    op.execute("DROP TABLE IF EXISTS blobs CASCADE;")
    op.execute("DROP TABLE IF EXISTS send_identities CASCADE;")
    op.execute("DROP TABLE IF EXISTS mailboxes CASCADE;")
    op.execute("DROP TABLE IF EXISTS oauth_credentials CASCADE;")
    op.execute("DROP TABLE IF EXISTS queue_memberships CASCADE;")
    op.execute("DROP TABLE IF EXISTS queues CASCADE;")
    op.execute("DROP TABLE IF EXISTS memberships CASCADE;")
    op.execute("DROP TABLE IF EXISTS users CASCADE;")
    op.execute("DROP TABLE IF EXISTS organizations CASCADE;")

    op.execute("DROP TYPE IF EXISTS job_type;")
    op.execute("DROP TYPE IF EXISTS job_status;")
    op.execute("DROP TYPE IF EXISTS ticket_priority;")
    op.execute("DROP TYPE IF EXISTS ticket_status;")
    op.execute("DROP TYPE IF EXISTS routing_confidence;")
    op.execute("DROP TYPE IF EXISTS routing_recipient_source;")
    op.execute("DROP TYPE IF EXISTS occurrence_state;")
    op.execute("DROP TYPE IF EXISTS message_direction;")
    op.execute("DROP TYPE IF EXISTS blob_kind;")
    op.execute("DROP TYPE IF EXISTS send_identity_status;")
    op.execute("DROP TYPE IF EXISTS mailbox_provider;")
    op.execute("DROP TYPE IF EXISTS mailbox_purpose;")
    op.execute("DROP TYPE IF EXISTS membership_role;")
