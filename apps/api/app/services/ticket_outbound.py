from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.enums import JobType, MessageDirection, RoutingConfidence, SendIdentityStatus
from app.models.mail import Message, MessageContent, MessageOssId, SendIdentity
from app.models.tickets import Ticket, TicketEvent, TicketMessage
from app.services.ingest.normalize import normalize_subject
from app.worker.queue import enqueue_job


def list_send_identities(*, session: Session, organization_id: UUID) -> list[dict]:
    rows = (
        session.execute(
            select(SendIdentity)
            .where(
                SendIdentity.organization_id == organization_id,
                SendIdentity.is_enabled.is_(True),
            )
            .order_by(SendIdentity.created_at.asc())
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": row.id,
            "mailbox_id": row.mailbox_id,
            "from_email": row.from_email,
            "from_name": row.from_name,
            "status": row.status.value,
            "is_enabled": row.is_enabled,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        for row in rows
    ]


def queue_ticket_reply(
    *,
    session: Session,
    organization_id: UUID,
    actor_user_id: UUID,
    ticket_id: UUID,
    send_identity_id: UUID,
    to_emails: list[str],
    cc_emails: list[str],
    subject: str,
    body_text: str,
) -> dict:
    ticket = (
        session.execute(
            select(Ticket)
            .where(Ticket.organization_id == organization_id, Ticket.id == ticket_id)
            .with_for_update()
        )
        .scalars()
        .first()
    )
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    identity = (
        session.execute(
            select(SendIdentity)
            .where(
                SendIdentity.organization_id == organization_id,
                SendIdentity.id == send_identity_id,
                SendIdentity.is_enabled.is_(True),
            )
            .with_for_update()
        )
        .scalars()
        .first()
    )
    if identity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Send identity not found")
    if identity.status != SendIdentityStatus.verified:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Send identity must be verified before sending",
        )

    to_normalized = _normalize_email_list(to_emails, label="to_emails")
    cc_normalized = _normalize_email_list(cc_emails, label="cc_emails")
    subject_norm = normalize_subject(subject)
    body = body_text.strip()
    if not body:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="body_text cannot be empty",
        )
    if subject_norm is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="subject cannot be empty",
        )

    now = datetime.now(UTC)
    oss_message_id = uuid4()
    rfc_message_id = f"<oss-{oss_message_id}@outbound.oss-ticketing.local>"
    reply_to = f"ticket+{ticket.ticket_code}@reply.oss-ticketing.local"

    fingerprint_v1 = _sha256_json(
        {
            "ticket_id": str(ticket.id),
            "subject_norm": subject_norm,
            "from": identity.from_email.lower(),
            "to": sorted(to_normalized),
            "cc": sorted(cc_normalized),
        }
    )
    signature_v1 = _sha256_json(
        {
            "ticket_id": str(ticket.id),
            "oss_message_id": str(oss_message_id),
            "subject": subject,
            "from": identity.from_email.lower(),
            "to": to_normalized,
            "cc": cc_normalized,
            "body_text": body,
        }
    )

    msg = Message(
        organization_id=organization_id,
        direction=MessageDirection.outbound,
        oss_message_id=oss_message_id,
        rfc_message_id=rfc_message_id,
        fingerprint_v1=fingerprint_v1,
        signature_v1=signature_v1,
        first_seen_at=now,
    )
    session.add(msg)
    session.flush()

    session.add(
        MessageOssId(
            organization_id=organization_id,
            oss_message_id=oss_message_id,
            message_id=msg.id,
        )
    )

    from_header = identity.from_email
    if identity.from_name:
        from_header = f"{identity.from_name} <{identity.from_email}>"
    headers_json = {
        "From": [from_header],
        "To": [", ".join(to_normalized)],
        "Cc": [", ".join(cc_normalized)] if cc_normalized else [],
        "Subject": [subject],
        "Message-ID": [rfc_message_id],
        "Reply-To": [reply_to],
        "X-OSS-Ticket-ID": [str(ticket.id)],
        "X-OSS-Message-ID": [str(oss_message_id)],
    }
    session.add(
        MessageContent(
            organization_id=organization_id,
            message_id=msg.id,
            content_version=1,
            parser_version=1,
            date_header=now,
            subject=subject,
            subject_norm=subject_norm,
            from_email=identity.from_email.lower(),
            from_name=identity.from_name,
            reply_to_emails=[reply_to],
            to_emails=to_normalized,
            cc_emails=cc_normalized,
            headers_json=headers_json,
            body_text=body,
            body_html_sanitized=None,
            has_attachments=False,
            attachment_count=0,
            snippet=body[:280] or subject[:280],
        )
    )

    session.add(
        TicketMessage(
            organization_id=organization_id,
            ticket_id=ticket.id,
            message_id=msg.id,
            stitch_reason="outbound_send",
            stitch_confidence=RoutingConfidence.high,
        )
    )

    ticket.last_message_at = now
    ticket.last_activity_at = now
    ticket.updated_at = now
    session.add(ticket)

    session.add(
        TicketEvent(
            organization_id=organization_id,
            ticket_id=ticket.id,
            actor_user_id=actor_user_id,
            event_type="outbound_queued",
            event_data={
                "message_id": str(msg.id),
                "oss_message_id": str(oss_message_id),
                "send_identity_id": str(identity.id),
                "to_emails": to_normalized,
                "cc_emails": cc_normalized,
            },
        )
    )
    session.flush()

    job_id = enqueue_job(
        session=session,
        job_type=JobType.outbound_send,
        organization_id=organization_id,
        mailbox_id=identity.mailbox_id,
        payload={
            "organization_id": str(organization_id),
            "ticket_id": str(ticket.id),
            "message_id": str(msg.id),
            "send_identity_id": str(identity.id),
            "to_emails": to_normalized,
            "cc_emails": cc_normalized,
            "subject": subject,
            "body_text": body,
        },
        dedupe_key=f"outbound_send:{msg.id}",
    )
    if job_id is None:
        existing = (
            session.execute(
                text(
                    """
                    SELECT id
                    FROM bg_jobs
                    WHERE organization_id = :organization_id
                      AND type = 'outbound_send'
                      AND dedupe_key = :dedupe_key
                    LIMIT 1
                    """
                ),
                {
                    "organization_id": str(organization_id),
                    "dedupe_key": f"outbound_send:{msg.id}",
                },
            )
            .mappings()
            .first()
        )
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to enqueue outbound send",
            )
        job_id = UUID(str(existing["id"]))

    return {
        "status": "queued",
        "job_id": job_id,
        "message_id": msg.id,
        "oss_message_id": oss_message_id,
    }


def _normalize_email_list(values: list[str], *, label: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        email = (value or "").strip().lower()
        if not email:
            continue
        if "@" not in email or " " in email:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Invalid email in {label}: {value!r}",
            )
        if email in seen:
            continue
        seen.add(email)
        out.append(email)
    if label == "to_emails" and not out:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="to_emails must contain at least one valid email",
        )
    return out


def _sha256_json(payload: dict) -> bytes:
    return hashlib.sha256(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).digest()
