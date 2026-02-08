from __future__ import annotations

import enum


class MembershipRole(str, enum.Enum):
    admin = "admin"
    agent = "agent"
    viewer = "viewer"


class MailboxPurpose(str, enum.Enum):
    journal = "journal"
    user = "user"


class MailboxProvider(str, enum.Enum):
    gmail = "gmail"


class SendIdentityStatus(str, enum.Enum):
    pending = "pending"
    verified = "verified"
    failed = "failed"


class BlobKind(str, enum.Enum):
    raw_eml = "raw_eml"
    attachment = "attachment"


class MessageDirection(str, enum.Enum):
    inbound = "inbound"
    outbound = "outbound"


class OccurrenceState(str, enum.Enum):
    discovered = "discovered"
    raw_fetched = "raw_fetched"
    parsed = "parsed"
    stitched = "stitched"
    routed = "routed"
    failed = "failed"


class RoutingRecipientSource(str, enum.Enum):
    workspace_header = "workspace_header"
    delivered_to = "delivered_to"
    x_original_to = "x_original_to"
    to_cc_scan = "to_cc_scan"
    unknown = "unknown"


class RoutingConfidence(str, enum.Enum):
    high = "high"
    medium = "medium"
    low = "low"


class TicketStatus(str, enum.Enum):
    new = "new"
    open = "open"
    pending = "pending"
    resolved = "resolved"
    closed = "closed"
    spam = "spam"


class TicketPriority(str, enum.Enum):
    low = "low"
    normal = "normal"
    high = "high"
    urgent = "urgent"


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    cancelled = "cancelled"


class JobType(str, enum.Enum):
    mailbox_backfill = "mailbox_backfill"
    mailbox_history_sync = "mailbox_history_sync"
    mailbox_watch_renew = "mailbox_watch_renew"
    occurrence_fetch_raw = "occurrence_fetch_raw"
    occurrence_parse = "occurrence_parse"
    occurrence_stitch = "occurrence_stitch"
    ticket_apply_routing = "ticket_apply_routing"
    outbound_send = "outbound_send"

