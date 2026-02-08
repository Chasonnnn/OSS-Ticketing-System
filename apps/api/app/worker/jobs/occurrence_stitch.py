from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.enums import JobType, OccurrenceState, RoutingConfidence
from app.services.ingest.dedupe import extract_uuid_header
from app.services.tickets.code import new_ticket_code
from app.worker.queue import enqueue_job

_REPLY_TO_TOKEN_RE = re.compile(r"^ticket\+([a-z0-9\-]+)@")


def occurrence_stitch(*, session: Session, payload: dict) -> None:
    occurrence_id = UUID(payload["occurrence_id"])

    occ = (
        session.execute(
            text(
                """
            SELECT id, organization_id, mailbox_id, state, message_id, ticket_id
            FROM message_occurrences
            WHERE id = :id
            FOR UPDATE
            """
            ),
            {"id": str(occurrence_id)},
        )
        .mappings()
        .fetchone()
    )
    if occ is None:
        return
    if occ["ticket_id"] is not None and occ["state"] in (
        OccurrenceState.stitched.value,
        OccurrenceState.routed.value,
    ):
        return
    if occ["message_id"] is None:
        _fail(session=session, occurrence_id=occurrence_id, err="missing message_id")
        return

    org_id = UUID(str(occ["organization_id"]))
    message_id = UUID(str(occ["message_id"]))

    existing_link = (
        session.execute(
            text(
                """
            SELECT ticket_id
            FROM ticket_messages
            WHERE organization_id = :org_id
              AND message_id = :message_id
            """
            ),
            {"org_id": str(org_id), "message_id": str(message_id)},
        )
        .mappings()
        .fetchone()
    )
    if existing_link is not None:
        ticket_id = UUID(str(existing_link["ticket_id"]))
        _mark_stitched(session=session, occurrence_id=occurrence_id, ticket_id=ticket_id)
        _enqueue_routing(
            session=session,
            org_id=org_id,
            mailbox_id=UUID(str(occ["mailbox_id"])),
            occurrence_id=occurrence_id,
        )
        return

    content = (
        session.execute(
            text(
                """
            SELECT subject, subject_norm, from_email, from_name, reply_to_emails, date_header, headers_json
            FROM message_contents
            WHERE organization_id = :org_id
              AND message_id = :message_id
            ORDER BY content_version DESC
            LIMIT 1
            """
            ),
            {"org_id": str(org_id), "message_id": str(message_id)},
        )
        .mappings()
        .fetchone()
    )
    if content is None:
        _fail(session=session, occurrence_id=occurrence_id, err="missing message content")
        return

    headers_json = content["headers_json"] or {}
    oss_ticket_id = extract_uuid_header(headers_json, "X-OSS-Ticket-ID")
    if oss_ticket_id is not None:
        ticket_id = _get_or_create_ticket_with_id(
            session=session,
            org_id=org_id,
            ticket_id=oss_ticket_id,
            subject=content["subject"],
            subject_norm=content["subject_norm"],
            requester_email=content["from_email"],
            requester_name=content["from_name"],
            first_message_at=content["date_header"],
        )
        _link_message(
            session=session,
            org_id=org_id,
            ticket_id=ticket_id,
            message_id=message_id,
            reason="x_oss_ticket_id",
            confidence=RoutingConfidence.high.value,
        )
        _mark_stitched(session=session, occurrence_id=occurrence_id, ticket_id=ticket_id)
        _enqueue_routing(
            session=session,
            org_id=org_id,
            mailbox_id=UUID(str(occ["mailbox_id"])),
            occurrence_id=occurrence_id,
        )
        return

    ticket_id = _try_reply_to_token(
        session=session,
        org_id=org_id,
        reply_to_emails=content["reply_to_emails"] or [],
    )
    if ticket_id is not None:
        _link_message(
            session=session,
            org_id=org_id,
            ticket_id=ticket_id,
            message_id=message_id,
            reason="reply_to_token",
            confidence=RoutingConfidence.high.value,
        )
        _mark_stitched(session=session, occurrence_id=occurrence_id, ticket_id=ticket_id)
        _enqueue_routing(
            session=session,
            org_id=org_id,
            mailbox_id=UUID(str(occ["mailbox_id"])),
            occurrence_id=occurrence_id,
        )
        return

    resolved_ticket = _try_threading_stitch(session=session, org_id=org_id, message_id=message_id)
    if resolved_ticket is not None:
        _link_message(
            session=session,
            org_id=org_id,
            ticket_id=resolved_ticket,
            message_id=message_id,
            reason="threading",
            confidence=RoutingConfidence.medium.value,
        )
        _mark_stitched(session=session, occurrence_id=occurrence_id, ticket_id=resolved_ticket)
        _enqueue_routing(
            session=session,
            org_id=org_id,
            mailbox_id=UUID(str(occ["mailbox_id"])),
            occurrence_id=occurrence_id,
        )
        return

    ticket_id = _create_ticket(
        session=session,
        org_id=org_id,
        subject=content["subject"],
        subject_norm=content["subject_norm"],
        requester_email=content["from_email"],
        requester_name=content["from_name"],
        first_message_at=content["date_header"],
        stitch_reason="new_message",
        stitch_confidence=RoutingConfidence.low.value,
    )
    _link_message(
        session=session,
        org_id=org_id,
        ticket_id=ticket_id,
        message_id=message_id,
        reason="new_ticket",
        confidence=RoutingConfidence.low.value,
    )
    _mark_stitched(session=session, occurrence_id=occurrence_id, ticket_id=ticket_id)
    _enqueue_routing(
        session=session,
        org_id=org_id,
        mailbox_id=UUID(str(occ["mailbox_id"])),
        occurrence_id=occurrence_id,
    )


def _try_reply_to_token(
    *, session: Session, org_id: UUID, reply_to_emails: list[str]
) -> UUID | None:
    for email in reply_to_emails:
        m = _REPLY_TO_TOKEN_RE.match((email or "").lower())
        if not m:
            continue
        code = m.group(1)
        row = (
            session.execute(
                text(
                    """
                SELECT id
                FROM tickets
                WHERE organization_id = :org_id
                  AND ticket_code = :code
                """
                ),
                {"org_id": str(org_id), "code": code},
            )
            .mappings()
            .fetchone()
        )
        if row is not None:
            return UUID(str(row["id"]))
    return None


def _try_threading_stitch(*, session: Session, org_id: UUID, message_id: UUID) -> UUID | None:
    refs = (
        session.execute(
            text(
                """
            SELECT ref_type, ref_rfc_message_id
            FROM message_thread_refs
            WHERE organization_id = :org_id
              AND message_id = :message_id
            ORDER BY CASE ref_type WHEN 'in_reply_to' THEN 0 ELSE 1 END, id ASC
            """
            ),
            {"org_id": str(org_id), "message_id": str(message_id)},
        )
        .mappings()
        .all()
    )

    for ref in refs:
        ref_rfc = ref["ref_rfc_message_id"]
        ref_msg = (
            session.execute(
                text(
                    """
                SELECT message_id
                FROM message_rfc_ids
                WHERE organization_id = :org_id
                  AND rfc_message_id = :rfc
                LIMIT 1
                """
                ),
                {"org_id": str(org_id), "rfc": ref_rfc},
            )
            .mappings()
            .fetchone()
        )
        if ref_msg is None:
            continue
        tm = (
            session.execute(
                text(
                    """
                SELECT ticket_id
                FROM ticket_messages
                WHERE organization_id = :org_id
                  AND message_id = :message_id
                """
                ),
                {"org_id": str(org_id), "message_id": str(ref_msg["message_id"])},
            )
            .mappings()
            .fetchone()
        )
        if tm is not None:
            return UUID(str(tm["ticket_id"]))

    return None


def _get_or_create_ticket_with_id(
    *,
    session: Session,
    org_id: UUID,
    ticket_id: UUID,
    subject: str | None,
    subject_norm: str | None,
    requester_email: str | None,
    requester_name: str | None,
    first_message_at,
) -> UUID:
    row = (
        session.execute(
            text("SELECT id FROM tickets WHERE organization_id = :org_id AND id = :id"),
            {"org_id": str(org_id), "id": str(ticket_id)},
        )
        .mappings()
        .fetchone()
    )
    if row is not None:
        return ticket_id
    session.execute(
        text(
            """
            INSERT INTO tickets (
              id,
              organization_id,
              ticket_code,
              status,
              priority,
              subject,
              subject_norm,
              requester_email,
              requester_name,
              created_at,
              updated_at,
              first_message_at,
              last_message_at,
              last_activity_at,
              stitch_reason,
              stitch_confidence
            )
            VALUES (
              :id,
              :org_id,
              :ticket_code,
              'new',
              'normal',
              :subject,
              :subject_norm,
              :requester_email,
              :requester_name,
              now(),
              now(),
              :first_message_at,
              :first_message_at,
              :first_message_at,
              'x_oss_ticket_id',
              'high'
            )
            """
        ),
        {
            "id": str(ticket_id),
            "org_id": str(org_id),
            "ticket_code": new_ticket_code(),
            "subject": subject,
            "subject_norm": subject_norm,
            "requester_email": requester_email,
            "requester_name": requester_name,
            "first_message_at": first_message_at,
        },
    )
    return ticket_id


def _create_ticket(
    *,
    session: Session,
    org_id: UUID,
    subject: str | None,
    subject_norm: str | None,
    requester_email: str | None,
    requester_name: str | None,
    first_message_at,
    stitch_reason: str,
    stitch_confidence: str,
) -> UUID:
    row = (
        session.execute(
            text(
                """
            INSERT INTO tickets (
              organization_id,
              ticket_code,
              status,
              priority,
              subject,
              subject_norm,
              requester_email,
              requester_name,
              created_at,
              updated_at,
              first_message_at,
              last_message_at,
              last_activity_at,
              stitch_reason,
              stitch_confidence
            )
            VALUES (
              :org_id,
              :ticket_code,
              'new',
              'normal',
              :subject,
              :subject_norm,
              :requester_email,
              :requester_name,
              now(),
              now(),
              :first_message_at,
              :first_message_at,
              :first_message_at,
              :stitch_reason,
              :stitch_confidence
            )
            RETURNING id
            """
            ),
            {
                "org_id": str(org_id),
                "ticket_code": new_ticket_code(),
                "subject": subject,
                "subject_norm": subject_norm,
                "requester_email": requester_email,
                "requester_name": requester_name,
                "first_message_at": first_message_at,
                "stitch_reason": stitch_reason,
                "stitch_confidence": stitch_confidence,
            },
        )
        .mappings()
        .fetchone()
    )
    assert row is not None
    return UUID(str(row["id"]))


def _link_message(
    *,
    session: Session,
    org_id: UUID,
    ticket_id: UUID,
    message_id: UUID,
    reason: str,
    confidence: str,
) -> None:
    session.execute(
        text(
            """
            INSERT INTO ticket_messages (
              organization_id,
              ticket_id,
              message_id,
              stitched_at,
              stitch_reason,
              stitch_confidence
            )
            VALUES (:org_id, :ticket_id, :message_id, now(), :reason, :confidence)
            ON CONFLICT (organization_id, message_id) DO NOTHING
            """
        ),
        {
            "org_id": str(org_id),
            "ticket_id": str(ticket_id),
            "message_id": str(message_id),
            "reason": reason,
            "confidence": confidence,
        },
    )


def _mark_stitched(*, session: Session, occurrence_id: UUID, ticket_id: UUID) -> None:
    session.execute(
        text(
            """
            UPDATE message_occurrences
            SET ticket_id = :ticket_id,
                stitched_at = now(),
                stitch_error = NULL,
                state = :state,
                updated_at = now()
            WHERE id = :id
            """
        ),
        {
            "id": str(occurrence_id),
            "ticket_id": str(ticket_id),
            "state": OccurrenceState.stitched.value,
        },
    )


def _enqueue_routing(
    *, session: Session, org_id: UUID, mailbox_id: UUID, occurrence_id: UUID
) -> None:
    enqueue_job(
        session=session,
        job_type=JobType.ticket_apply_routing,
        organization_id=org_id,
        mailbox_id=mailbox_id,
        payload={"occurrence_id": str(occurrence_id)},
        dedupe_key=f"ticket_apply_routing:{occurrence_id}",
    )


def _fail(*, session: Session, occurrence_id: UUID, err: str) -> None:
    session.execute(
        text(
            """
            UPDATE message_occurrences
            SET state = 'failed',
                stitch_error = :err,
                updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": str(occurrence_id), "err": err},
    )
