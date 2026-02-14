from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import TicketPriority, TicketStatus


class TicketListItem(BaseModel):
    id: UUID
    ticket_code: str
    status: str
    priority: str
    subject: str | None
    requester_email: str | None
    requester_name: str | None
    assignee_user_id: UUID | None
    assignee_queue_id: UUID | None
    created_at: datetime
    updated_at: datetime
    first_message_at: datetime | None
    last_message_at: datetime | None
    last_activity_at: datetime | None
    closed_at: datetime | None
    stitch_reason: str | None
    stitch_confidence: str


class TicketListResponse(BaseModel):
    items: list[TicketListItem]
    next_cursor: str | None


class TicketOut(BaseModel):
    id: UUID
    ticket_code: str
    status: str
    priority: str
    subject: str | None
    requester_email: str | None
    requester_name: str | None
    assignee_user_id: UUID | None
    assignee_queue_id: UUID | None
    created_at: datetime
    updated_at: datetime
    first_message_at: datetime | None
    last_message_at: datetime | None
    last_activity_at: datetime | None
    closed_at: datetime | None
    stitch_reason: str | None
    stitch_confidence: str


class TicketMessageAttachmentOut(BaseModel):
    id: UUID
    filename: str | None
    content_type: str | None
    size_bytes: int
    is_inline: bool
    content_id: str | None


class TicketOccurrenceOut(BaseModel):
    id: UUID
    mailbox_id: UUID
    gmail_message_id: str
    state: str
    original_recipient: str | None
    original_recipient_source: str
    original_recipient_confidence: str
    original_recipient_evidence: dict[str, Any]
    routed_at: datetime | None
    parse_error: str | None
    stitch_error: str | None
    route_error: str | None


class TicketThreadMessageOut(BaseModel):
    message_id: UUID
    stitched_at: datetime
    stitch_reason: str
    stitch_confidence: str
    direction: str
    rfc_message_id: str | None
    date_header: datetime | None
    subject: str | None
    from_email: str | None
    to_emails: list[str]
    cc_emails: list[str]
    snippet: str | None
    body_text: str | None
    body_html_sanitized: str | None
    attachments: list[TicketMessageAttachmentOut]
    occurrences: list[TicketOccurrenceOut]


class TicketEventOut(BaseModel):
    id: UUID
    actor_user_id: UUID | None
    event_type: str
    created_at: datetime
    event_data: dict[str, Any]


class TicketNoteOut(BaseModel):
    id: UUID
    author_user_id: UUID | None
    body_markdown: str
    body_html_sanitized: str | None
    created_at: datetime
    updated_at: datetime


class TicketDetailResponse(BaseModel):
    ticket: TicketOut
    messages: list[TicketThreadMessageOut]
    events: list[TicketEventOut]
    notes: list[TicketNoteOut]


class TicketUpdateRequest(BaseModel):
    status: TicketStatus | None = None
    priority: TicketPriority | None = None
    assignee_user_id: UUID | None = None
    assignee_queue_id: UUID | None = None


class TicketNoteCreateRequest(BaseModel):
    body_markdown: str = Field(min_length=1, max_length=20000)
