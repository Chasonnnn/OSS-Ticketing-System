from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import quote
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import Text, and_, cast, func, or_, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.tickets import Ticket
from app.storage.base import BlobStoreError
from app.storage.factory import build_blob_store


@dataclass(frozen=True)
class TicketListPage:
    items: list[dict]
    next_cursor: str | None


@dataclass(frozen=True)
class TicketDetailView:
    ticket: dict
    messages: list[dict]
    events: list[dict]
    notes: list[dict]


@dataclass(frozen=True)
class TicketAttachmentDownload:
    bytes_data: bytes | None
    content_type: str
    content_disposition: str
    redirect_url: str | None


def list_tickets(
    *,
    session: Session,
    organization_id: UUID,
    limit: int,
    cursor: str | None,
    status_filter: str | None,
    q: str | None,
    assignee_user_id: UUID | None,
    assignee_queue_id: UUID | None,
) -> TicketListPage:
    cursor_data = _decode_cursor(cursor) if cursor else None
    q_like = None
    if q is not None and q.strip():
        q_like = f"%{q.strip()}%"

    sort_ts = func.coalesce(Ticket.last_activity_at, Ticket.created_at)
    query = (
        select(Ticket, sort_ts.label("sort_ts"))
        .where(Ticket.organization_id == organization_id)
        .order_by(sort_ts.desc(), Ticket.id.desc())
        .limit(limit + 1)
    )
    if status_filter is not None:
        query = query.where(Ticket.status == status_filter)
    if assignee_user_id is not None:
        query = query.where(Ticket.assignee_user_id == assignee_user_id)
    if assignee_queue_id is not None:
        query = query.where(Ticket.assignee_queue_id == assignee_queue_id)
    if q_like is not None:
        query = query.where(
            or_(
                Ticket.subject.ilike(q_like),
                cast(Ticket.requester_email, Text).ilike(q_like),
                Ticket.ticket_code.ilike(q_like),
            )
        )
    if cursor_data is not None:
        query = query.where(
            or_(
                sort_ts < cursor_data["sort_ts"],
                and_(sort_ts == cursor_data["sort_ts"], Ticket.id < cursor_data["id"]),
            )
        )

    rows = session.execute(query).all()

    has_more = len(rows) > limit
    page_rows = rows[:limit]

    items = []
    for ticket, row_sort_ts in page_rows:
        items.append(
            {
                "id": ticket.id,
                "ticket_code": ticket.ticket_code,
                "status": ticket.status.value,
                "priority": ticket.priority.value,
                "subject": ticket.subject,
                "requester_email": ticket.requester_email,
                "requester_name": ticket.requester_name,
                "assignee_user_id": ticket.assignee_user_id,
                "assignee_queue_id": ticket.assignee_queue_id,
                "created_at": ticket.created_at,
                "updated_at": ticket.updated_at,
                "first_message_at": ticket.first_message_at,
                "last_message_at": ticket.last_message_at,
                "last_activity_at": ticket.last_activity_at,
                "closed_at": ticket.closed_at,
                "stitch_reason": ticket.stitch_reason,
                "stitch_confidence": ticket.stitch_confidence.value,
                "sort_ts": row_sort_ts,
            }
        )

    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = _encode_cursor(
            sort_ts=last["sort_ts"],
            row_id=last["id"],
        )
    for item in items:
        item.pop("sort_ts", None)

    return TicketListPage(items=items, next_cursor=next_cursor)


def get_ticket_detail(
    *,
    session: Session,
    organization_id: UUID,
    ticket_id: UUID,
) -> TicketDetailView:
    ticket = (
        session.execute(
            select(Ticket).where(
                Ticket.organization_id == organization_id,
                Ticket.id == ticket_id,
            )
        )
        .scalars()
        .first()
    )
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    messages_rows = (
        session.execute(
            text(
                """
                SELECT
                  tm.id AS ticket_message_id,
                  tm.message_id,
                  tm.stitched_at,
                  tm.stitch_reason,
                  tm.stitch_confidence,
                  m.direction,
                  m.rfc_message_id,
                  mc.date_header,
                  mc.subject,
                  mc.from_email,
                  mc.to_emails,
                  mc.cc_emails,
                  mc.snippet,
                  mc.body_text,
                  mc.body_html_sanitized
                FROM ticket_messages tm
                JOIN messages m
                  ON m.id = tm.message_id
                 AND m.organization_id = tm.organization_id
                LEFT JOIN LATERAL (
                  SELECT
                    date_header,
                    subject,
                    from_email,
                    to_emails,
                    cc_emails,
                    snippet,
                    body_text,
                    body_html_sanitized
                  FROM message_contents
                  WHERE organization_id = tm.organization_id
                    AND message_id = tm.message_id
                  ORDER BY content_version DESC
                  LIMIT 1
                ) mc ON TRUE
                WHERE tm.organization_id = :organization_id
                  AND tm.ticket_id = :ticket_id
                ORDER BY COALESCE(mc.date_header, tm.stitched_at) ASC, tm.stitched_at ASC, tm.id ASC
                """
            ),
            {"organization_id": str(organization_id), "ticket_id": str(ticket_id)},
        )
        .mappings()
        .all()
    )

    attachment_rows = (
        session.execute(
            text(
                """
                SELECT
                  ma.id,
                  ma.message_id,
                  ma.filename,
                  ma.content_type,
                  ma.size_bytes,
                  ma.is_inline,
                  ma.content_id
                FROM message_attachments ma
                JOIN ticket_messages tm
                  ON tm.organization_id = ma.organization_id
                 AND tm.message_id = ma.message_id
                WHERE ma.organization_id = :organization_id
                  AND tm.ticket_id = :ticket_id
                ORDER BY ma.message_id ASC, ma.id ASC
                """
            ),
            {"organization_id": str(organization_id), "ticket_id": str(ticket_id)},
        )
        .mappings()
        .all()
    )
    attachments_by_message: dict[UUID, list[dict]] = {}
    for row in attachment_rows:
        message_id = UUID(str(row["message_id"]))
        attachments_by_message.setdefault(message_id, []).append(
            {
                "id": row["id"],
                "filename": row["filename"],
                "content_type": row["content_type"],
                "size_bytes": row["size_bytes"],
                "is_inline": row["is_inline"],
                "content_id": row["content_id"],
            }
        )

    occurrence_rows = (
        session.execute(
            text(
                """
                SELECT
                  id,
                  message_id,
                  mailbox_id,
                  gmail_message_id,
                  state,
                  original_recipient,
                  original_recipient_source,
                  original_recipient_confidence,
                  original_recipient_evidence,
                  routed_at,
                  parse_error,
                  stitch_error,
                  route_error
                FROM message_occurrences
                WHERE organization_id = :organization_id
                  AND ticket_id = :ticket_id
                  AND message_id IS NOT NULL
                ORDER BY message_id ASC, created_at ASC, id ASC
                """
            ),
            {"organization_id": str(organization_id), "ticket_id": str(ticket_id)},
        )
        .mappings()
        .all()
    )
    occurrences_by_message: dict[UUID, list[dict]] = {}
    for row in occurrence_rows:
        message_id = UUID(str(row["message_id"]))
        occurrences_by_message.setdefault(message_id, []).append(
            {
                "id": row["id"],
                "mailbox_id": row["mailbox_id"],
                "gmail_message_id": row["gmail_message_id"],
                "state": row["state"],
                "original_recipient": row["original_recipient"],
                "original_recipient_source": row["original_recipient_source"],
                "original_recipient_confidence": row["original_recipient_confidence"],
                "original_recipient_evidence": row["original_recipient_evidence"] or {},
                "routed_at": row["routed_at"],
                "parse_error": row["parse_error"],
                "stitch_error": row["stitch_error"],
                "route_error": row["route_error"],
            }
        )

    messages = []
    for row in messages_rows:
        message_id = UUID(str(row["message_id"]))
        messages.append(
            {
                "message_id": message_id,
                "stitched_at": row["stitched_at"],
                "stitch_reason": row["stitch_reason"],
                "stitch_confidence": row["stitch_confidence"],
                "direction": row["direction"],
                "rfc_message_id": row["rfc_message_id"],
                "date_header": row["date_header"],
                "subject": row["subject"],
                "from_email": row["from_email"],
                "to_emails": _coerce_text_array(row["to_emails"]),
                "cc_emails": _coerce_text_array(row["cc_emails"]),
                "snippet": row["snippet"],
                "body_text": row["body_text"],
                "body_html_sanitized": row["body_html_sanitized"],
                "attachments": attachments_by_message.get(message_id, []),
                "occurrences": occurrences_by_message.get(message_id, []),
            }
        )

    events = (
        session.execute(
            text(
                """
                SELECT id, actor_user_id, event_type, created_at, event_data
                FROM ticket_events
                WHERE organization_id = :organization_id
                  AND ticket_id = :ticket_id
                ORDER BY created_at ASC, id ASC
                """
            ),
            {"organization_id": str(organization_id), "ticket_id": str(ticket_id)},
        )
        .mappings()
        .all()
    )
    notes = (
        session.execute(
            text(
                """
                SELECT
                  id,
                  author_user_id,
                  body_markdown,
                  body_html_sanitized,
                  created_at,
                  updated_at
                FROM ticket_notes
                WHERE organization_id = :organization_id
                  AND ticket_id = :ticket_id
                ORDER BY created_at ASC, id ASC
                """
            ),
            {"organization_id": str(organization_id), "ticket_id": str(ticket_id)},
        )
        .mappings()
        .all()
    )

    return TicketDetailView(
        ticket={
            "id": ticket.id,
            "ticket_code": ticket.ticket_code,
            "status": ticket.status.value,
            "priority": ticket.priority.value,
            "subject": ticket.subject,
            "requester_email": ticket.requester_email,
            "requester_name": ticket.requester_name,
            "assignee_user_id": ticket.assignee_user_id,
            "assignee_queue_id": ticket.assignee_queue_id,
            "created_at": ticket.created_at,
            "updated_at": ticket.updated_at,
            "first_message_at": ticket.first_message_at,
            "last_message_at": ticket.last_message_at,
            "last_activity_at": ticket.last_activity_at,
            "closed_at": ticket.closed_at,
            "stitch_reason": ticket.stitch_reason,
            "stitch_confidence": ticket.stitch_confidence.value,
        },
        messages=messages,
        events=[
            {
                "id": row["id"],
                "actor_user_id": row["actor_user_id"],
                "event_type": row["event_type"],
                "created_at": row["created_at"],
                "event_data": row["event_data"] or {},
            }
            for row in events
        ],
        notes=[
            {
                "id": row["id"],
                "author_user_id": row["author_user_id"],
                "body_markdown": row["body_markdown"],
                "body_html_sanitized": row["body_html_sanitized"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in notes
        ],
    )


def get_ticket_attachment_download(
    *,
    session: Session,
    organization_id: UUID,
    ticket_id: UUID,
    attachment_id: UUID,
) -> TicketAttachmentDownload:
    row = (
        session.execute(
            text(
                """
                SELECT
                  ma.filename,
                  ma.content_type AS attachment_content_type,
                  b.content_type AS blob_content_type,
                  b.storage_key
                FROM message_attachments ma
                JOIN blobs b
                  ON b.id = ma.blob_id
                 AND b.organization_id = ma.organization_id
                JOIN ticket_messages tm
                  ON tm.organization_id = ma.organization_id
                 AND tm.message_id = ma.message_id
                WHERE ma.organization_id = :organization_id
                  AND tm.ticket_id = :ticket_id
                  AND ma.id = :attachment_id
                LIMIT 1
                """
            ),
            {
                "organization_id": str(organization_id),
                "ticket_id": str(ticket_id),
                "attachment_id": str(attachment_id),
            },
        )
        .mappings()
        .fetchone()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")

    filename = _safe_download_filename(
        raw_filename=row["filename"],
        fallback=f"attachment-{attachment_id}",
    )
    content_type = (
        row["attachment_content_type"]
        or row["blob_content_type"]
        or "application/octet-stream"
    )
    disposition = _build_attachment_disposition(filename)

    blob_store = build_blob_store()
    settings = get_settings()
    signed_url = blob_store.get_download_url(
        key=str(row["storage_key"]),
        expires_in_seconds=settings.ATTACHMENT_DOWNLOAD_URL_TTL_SECONDS,
        filename=filename,
        content_type=content_type,
    )
    if signed_url:
        return TicketAttachmentDownload(
            bytes_data=None,
            content_type=content_type,
            content_disposition=disposition,
            redirect_url=signed_url,
        )

    try:
        payload = blob_store.get_bytes(key=str(row["storage_key"]))
    except BlobStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Attachment blob unavailable",
        ) from exc

    return TicketAttachmentDownload(
        bytes_data=payload,
        content_type=content_type,
        content_disposition=disposition,
        redirect_url=None,
    )


def _encode_cursor(*, sort_ts: datetime, row_id: UUID) -> str:
    payload = {
        "sort_ts": sort_ts.astimezone(UTC).isoformat(),
        "id": str(row_id),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> dict:
    try:
        padded = cursor + ("=" * ((4 - len(cursor) % 4) % 4))
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        sort_ts = datetime.fromisoformat(payload["sort_ts"])
        if sort_ts.tzinfo is None:
            sort_ts = sort_ts.replace(tzinfo=UTC)
        return {"sort_ts": sort_ts, "id": UUID(payload["id"])}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Invalid cursor",
        ) from exc


def _coerce_text_array(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value if str(v)]
    if isinstance(value, str):
        raw = value.strip()
        if raw == "{}":
            return []
        if raw.startswith("{") and raw.endswith("}"):
            inner = raw[1:-1].strip()
            if not inner:
                return []
            return [part.strip().strip('"') for part in inner.split(",") if part.strip()]
        return [raw]
    return [str(value)]


def _safe_download_filename(*, raw_filename: str | None, fallback: str) -> str:
    base = (raw_filename or "").replace("\r", "").replace("\n", "").strip()
    if not base:
        return fallback
    return base


def _build_attachment_disposition(filename: str) -> str:
    ascii_name = (
        filename.encode("ascii", "ignore")
        .decode("ascii")
        .replace("\\", "_")
        .replace('"', "'")
    )
    if not ascii_name:
        ascii_name = "attachment"
    utf8_name = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{utf8_name}"
