from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import (
    BlobKind,
    MailboxProvider,
    MailboxPurpose,
    MessageDirection,
    OccurrenceState,
    RoutingConfidence,
    RoutingRecipientSource,
    SendIdentityStatus,
)


class OAuthCredential(Base):
    __tablename__ = "oauth_credentials"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    encrypted_refresh_token: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    encrypted_access_token: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class Mailbox(Base):
    __tablename__ = "mailboxes"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    purpose: Mapped[MailboxPurpose] = mapped_column(
        Enum(MailboxPurpose, name="mailbox_purpose", create_type=False), nullable=False
    )
    provider: Mapped[MailboxProvider] = mapped_column(
        Enum(MailboxProvider, name="mailbox_provider", create_type=False), nullable=False
    )
    email_address: Mapped[str] = mapped_column(CITEXT, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    oauth_credential_id: Mapped[UUID] = mapped_column(
        ForeignKey("oauth_credentials.id", ondelete="RESTRICT"), nullable=False
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    ingestion_paused_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ingestion_pause_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    gmail_history_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    gmail_watch_expiration: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    gmail_watch_resource_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    gmail_profile_email: Mapped[str | None] = mapped_column(CITEXT, nullable=True)
    last_incremental_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_full_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class SendIdentity(Base):
    __tablename__ = "send_identities"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    mailbox_id: Mapped[UUID] = mapped_column(ForeignKey("mailboxes.id", ondelete="CASCADE"), nullable=False)
    from_email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    from_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    gmail_send_as_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[SendIdentityStatus] = mapped_column(
        Enum(SendIdentityStatus, name="send_identity_status", create_type=False),
        nullable=False,
        server_default=text("'pending'"),
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class Blob(Base):
    __tablename__ = "blobs"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[BlobKind] = mapped_column(
        Enum(BlobKind, name="blob_kind", create_type=False), nullable=False
    )
    sha256: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    direction: Mapped[MessageDirection] = mapped_column(
        Enum(MessageDirection, name="message_direction", create_type=False), nullable=False
    )
    oss_message_id: Mapped[UUID | None] = mapped_column(nullable=True)
    rfc_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    fingerprint_v1: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    signature_v1: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    collision_group_id: Mapped[UUID | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class MessageOssId(Base):
    __tablename__ = "message_oss_ids"

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    oss_message_id: Mapped[UUID] = mapped_column(primary_key=True)
    message_id: Mapped[UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class MessageRfcId(Base):
    __tablename__ = "message_rfc_ids"

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    rfc_message_id: Mapped[str] = mapped_column(Text, primary_key=True)
    signature_v1: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    message_id: Mapped[UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class MessageFingerprint(Base):
    __tablename__ = "message_fingerprints"

    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), primary_key=True
    )
    fingerprint_version: Mapped[int] = mapped_column(Integer, primary_key=True)
    fingerprint: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    signature_v1: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    message_id: Mapped[UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class MessageContent(Base):
    __tablename__ = "message_contents"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    content_version: Mapped[int] = mapped_column(Integer, nullable=False)
    parser_version: Mapped[int] = mapped_column(Integer, nullable=False)
    parsed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

    date_header: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    subject_norm: Mapped[str | None] = mapped_column(Text, nullable=True)
    from_email: Mapped[str | None] = mapped_column(CITEXT, nullable=True)
    from_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    reply_to_emails: Mapped[list[str]] = mapped_column(ARRAY(CITEXT), nullable=False, server_default=text("'{}'"))
    to_emails: Mapped[list[str]] = mapped_column(ARRAY(CITEXT), nullable=False, server_default=text("'{}'"))
    cc_emails: Mapped[list[str]] = mapped_column(ARRAY(CITEXT), nullable=False, server_default=text("'{}'"))

    headers_json: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))

    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_html_sanitized: Mapped[str | None] = mapped_column(Text, nullable=True)

    has_attachments: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    attachment_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))

    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)

    search_tsv: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "to_tsvector('english', coalesce(subject,'') || ' ' || coalesce(body_text,''))",
            persisted=True,
        ),
        nullable=False,
    )


class MessageAttachment(Base):
    __tablename__ = "message_attachments"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    blob_id: Mapped[UUID] = mapped_column(ForeignKey("blobs.id", ondelete="RESTRICT"), nullable=False)
    filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    is_inline: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    content_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class MessageThreadRef(Base):
    __tablename__ = "message_thread_refs"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[UUID] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), nullable=False)
    ref_type: Mapped[str] = mapped_column(Text, nullable=False)
    ref_rfc_message_id: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))


class MessageOccurrence(Base):
    __tablename__ = "message_occurrences"

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    organization_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    mailbox_id: Mapped[UUID] = mapped_column(ForeignKey("mailboxes.id", ondelete="CASCADE"), nullable=False)

    gmail_message_id: Mapped[str] = mapped_column(Text, nullable=False)
    gmail_thread_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    gmail_history_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    gmail_internal_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    label_ids: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default=text("'{}'"))

    state: Mapped[OccurrenceState] = mapped_column(
        Enum(OccurrenceState, name="occurrence_state", create_type=False),
        nullable=False,
        server_default=text("'discovered'"),
    )

    raw_blob_id: Mapped[UUID | None] = mapped_column(ForeignKey("blobs.id", ondelete="SET NULL"), nullable=True)
    raw_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_fetch_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    message_id: Mapped[UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    parsed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    ticket_id: Mapped[UUID | None] = mapped_column(ForeignKey("tickets.id", ondelete="SET NULL"), nullable=True)
    stitched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stitch_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    routed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    route_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    original_recipient: Mapped[str | None] = mapped_column(CITEXT, nullable=True)
    original_recipient_source: Mapped[RoutingRecipientSource] = mapped_column(
        Enum(RoutingRecipientSource, name="routing_recipient_source", create_type=False),
        nullable=False,
        server_default=text("'unknown'"),
    )
    original_recipient_confidence: Mapped[RoutingConfidence] = mapped_column(
        Enum(RoutingConfidence, name="routing_confidence", create_type=False),
        nullable=False,
        server_default=text("'low'"),
    )
    original_recipient_evidence: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("now()"))

