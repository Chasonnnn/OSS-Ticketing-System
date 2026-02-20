from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import MessageDirection, TicketPriority, TicketStatus


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
    collision_group_id: UUID | None
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


class SendIdentityOut(BaseModel):
    id: UUID
    mailbox_id: UUID
    from_email: str
    from_name: str | None
    status: str
    is_enabled: bool
    created_at: datetime
    updated_at: datetime


class TicketReplyRequest(BaseModel):
    send_identity_id: UUID
    to_emails: list[str] = Field(min_length=1, max_length=50)
    cc_emails: list[str] = Field(default_factory=list, max_length=50)
    subject: str = Field(min_length=1, max_length=998)
    body_text: str = Field(min_length=1, max_length=100000)


class TicketReplyResponse(BaseModel):
    status: str
    job_id: UUID
    message_id: UUID
    oss_message_id: UUID


class TicketSavedViewCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    filters: dict[str, Any] = Field(default_factory=dict)


class TicketSavedViewOut(BaseModel):
    id: UUID
    name: str
    filters: dict[str, Any]
    is_default: bool
    created_at: datetime
    updated_at: datetime


class RoutingSimulationRequest(BaseModel):
    recipient: str = Field(min_length=3, max_length=320)
    sender_email: str = Field(min_length=3, max_length=320)
    direction: str = Field(min_length=3, max_length=20)


class RoutingSimulationMatchedRule(BaseModel):
    id: UUID
    name: str
    priority: int


class RoutingSimulationAppliedActions(BaseModel):
    assign_queue_id: UUID | None = None
    assign_user_id: UUID | None = None
    set_status: str | None = None
    drop: bool = False
    auto_close: bool = False


class RoutingSimulationResponse(BaseModel):
    allowlisted: bool
    would_mark_spam: bool
    matched_rule: RoutingSimulationMatchedRule | None
    applied_actions: RoutingSimulationAppliedActions
    explanation: str


class RecipientAllowlistOut(BaseModel):
    id: UUID
    pattern: str
    is_enabled: bool
    created_at: datetime


class RecipientAllowlistCreateRequest(BaseModel):
    pattern: str = Field(min_length=3, max_length=320)
    is_enabled: bool = True


class RecipientAllowlistUpdateRequest(BaseModel):
    pattern: str | None = Field(default=None, min_length=3, max_length=320)
    is_enabled: bool | None = None


class RoutingRuleOut(BaseModel):
    id: UUID
    name: str
    is_enabled: bool
    priority: int
    match_recipient_pattern: str | None
    match_sender_domain_pattern: str | None
    match_sender_email_pattern: str | None
    match_direction: str | None
    action_assign_queue_id: UUID | None
    action_assign_user_id: UUID | None
    action_set_status: str | None
    action_drop: bool
    action_auto_close: bool
    created_at: datetime
    updated_at: datetime


class RoutingRuleCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    is_enabled: bool = True
    priority: int = Field(default=100, ge=0, le=10_000)

    match_recipient_pattern: str | None = Field(default=None, max_length=320)
    match_sender_domain_pattern: str | None = Field(default=None, max_length=255)
    match_sender_email_pattern: str | None = Field(default=None, max_length=320)
    match_direction: MessageDirection | None = None

    action_assign_queue_id: UUID | None = None
    action_assign_user_id: UUID | None = None
    action_set_status: TicketStatus | None = None
    action_drop: bool = False
    action_auto_close: bool = False


class RoutingRuleUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    is_enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=10_000)

    match_recipient_pattern: str | None = Field(default=None, max_length=320)
    match_sender_domain_pattern: str | None = Field(default=None, max_length=255)
    match_sender_email_pattern: str | None = Field(default=None, max_length=320)
    match_direction: MessageDirection | None = None

    action_assign_queue_id: UUID | None = None
    action_assign_user_id: UUID | None = None
    action_set_status: TicketStatus | None = None
    action_drop: bool | None = None
    action_auto_close: bool | None = None
