from __future__ import annotations

import enum


class MembershipRole(enum.StrEnum):
    admin = "admin"
    agent = "agent"
    viewer = "viewer"


class MailboxPurpose(enum.StrEnum):
    journal = "journal"
    user = "user"


class MailboxProvider(enum.StrEnum):
    gmail = "gmail"


class SendIdentityStatus(enum.StrEnum):
    pending = "pending"
    verified = "verified"
    failed = "failed"


class BlobKind(enum.StrEnum):
    raw_eml = "raw_eml"
    attachment = "attachment"


class MessageDirection(enum.StrEnum):
    inbound = "inbound"
    outbound = "outbound"


class OccurrenceState(enum.StrEnum):
    discovered = "discovered"
    raw_fetched = "raw_fetched"
    parsed = "parsed"
    stitched = "stitched"
    routed = "routed"
    failed = "failed"


class RoutingRecipientSource(enum.StrEnum):
    workspace_header = "workspace_header"
    delivered_to = "delivered_to"
    x_original_to = "x_original_to"
    to_cc_scan = "to_cc_scan"
    unknown = "unknown"


class RoutingConfidence(enum.StrEnum):
    high = "high"
    medium = "medium"
    low = "low"


class TicketStatus(enum.StrEnum):
    new = "new"
    open = "open"
    pending = "pending"
    resolved = "resolved"
    closed = "closed"
    spam = "spam"


class TicketPriority(enum.StrEnum):
    low = "low"
    normal = "normal"
    high = "high"
    urgent = "urgent"


class JobStatus(enum.StrEnum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class JobType(enum.StrEnum):
    mailbox_backfill = "mailbox_backfill"
    mailbox_history_sync = "mailbox_history_sync"
    mailbox_watch_renew = "mailbox_watch_renew"
    occurrence_fetch_raw = "occurrence_fetch_raw"
    occurrence_parse = "occurrence_parse"
    occurrence_stitch = "occurrence_stitch"
    ticket_apply_routing = "ticket_apply_routing"
    outbound_send = "outbound_send"
