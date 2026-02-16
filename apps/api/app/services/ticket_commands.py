from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.enums import TicketPriority, TicketStatus
from app.models.identity import Membership, Queue
from app.models.tickets import Ticket, TicketNote


def update_ticket(
    *,
    session: Session,
    organization_id: UUID,
    ticket_id: UUID,
    actor_user_id: UUID,
    updates: dict,
) -> dict:
    ticket = _load_ticket_for_update(
        session=session,
        organization_id=organization_id,
        ticket_id=ticket_id,
    )
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    if "status" in updates and updates["status"] is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="status cannot be null",
        )
    if "priority" in updates and updates["priority"] is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="priority cannot be null",
        )

    assignment_keys = [key for key in ("assignee_user_id", "assignee_queue_id") if key in updates]
    if len(assignment_keys) > 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Provide only one assignee target",
        )

    now = datetime.now(UTC)
    changes: dict[str, dict[str, object | None]] = {}

    if "status" in updates:
        next_status = updates["status"]
        if not isinstance(next_status, TicketStatus):
            next_status = TicketStatus(str(next_status))
        if ticket.status != next_status:
            changes["status"] = {"before": ticket.status.value, "after": next_status.value}
            ticket.status = next_status
            if next_status in {TicketStatus.closed, TicketStatus.spam}:
                ticket.closed_at = now
            else:
                ticket.closed_at = None

    if "priority" in updates:
        next_priority = updates["priority"]
        if not isinstance(next_priority, TicketPriority):
            next_priority = TicketPriority(str(next_priority))
        if ticket.priority != next_priority:
            changes["priority"] = {"before": ticket.priority.value, "after": next_priority.value}
            ticket.priority = next_priority

    if assignment_keys:
        assignment_key = assignment_keys[0]
        assignment_value = updates[assignment_key]
        before_user = ticket.assignee_user_id
        before_queue = ticket.assignee_queue_id

        if assignment_value is None:
            ticket.assignee_user_id = None
            ticket.assignee_queue_id = None
        elif assignment_key == "assignee_user_id":
            _ensure_org_membership(
                session=session,
                organization_id=organization_id,
                user_id=assignment_value,
            )
            ticket.assignee_user_id = assignment_value
            ticket.assignee_queue_id = None
        else:
            _ensure_org_queue(
                session=session,
                organization_id=organization_id,
                queue_id=assignment_value,
            )
            ticket.assignee_queue_id = assignment_value
            ticket.assignee_user_id = None

        if before_user != ticket.assignee_user_id or before_queue != ticket.assignee_queue_id:
            changes["assignee_user_id"] = {
                "before": str(before_user) if before_user else None,
                "after": str(ticket.assignee_user_id) if ticket.assignee_user_id else None,
            }
            changes["assignee_queue_id"] = {
                "before": str(before_queue) if before_queue else None,
                "after": str(ticket.assignee_queue_id) if ticket.assignee_queue_id else None,
            }

    if changes:
        ticket.updated_at = now
        ticket.last_activity_at = now
        session.add(ticket)
        session.flush()
        session.execute(
            text(
                """
                INSERT INTO ticket_events (
                  organization_id,
                  ticket_id,
                  actor_user_id,
                  event_type,
                  created_at,
                  event_data
                )
                VALUES (
                  :organization_id,
                  :ticket_id,
                  :actor_user_id,
                  'ticket_updated',
                  now(),
                  CAST(:event_data AS jsonb)
                )
                """
            ),
            {
                "organization_id": str(organization_id),
                "ticket_id": str(ticket.id),
                "actor_user_id": str(actor_user_id),
                "event_data": _json_dumps({"changes": changes}),
            },
        )

    return _ticket_to_dict(ticket)


def create_ticket_note(
    *,
    session: Session,
    organization_id: UUID,
    ticket_id: UUID,
    actor_user_id: UUID,
    body_markdown: str,
) -> dict:
    ticket = _load_ticket_for_update(
        session=session,
        organization_id=organization_id,
        ticket_id=ticket_id,
    )
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    body = body_markdown.strip()
    if not body:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="body_markdown cannot be empty",
        )

    now = datetime.now(UTC)
    note = TicketNote(
        organization_id=organization_id,
        ticket_id=ticket.id,
        author_user_id=actor_user_id,
        body_markdown=body,
        body_html_sanitized=None,
    )
    session.add(note)

    ticket.updated_at = now
    ticket.last_activity_at = now
    session.add(ticket)
    session.flush()

    session.execute(
        text(
            """
            INSERT INTO ticket_events (
              organization_id,
              ticket_id,
              actor_user_id,
              event_type,
              created_at,
              event_data
            )
            VALUES (
              :organization_id,
              :ticket_id,
              :actor_user_id,
              'note_added',
              now(),
              CAST(:event_data AS jsonb)
            )
            """
        ),
        {
            "organization_id": str(organization_id),
            "ticket_id": str(ticket.id),
            "actor_user_id": str(actor_user_id),
            "event_data": _json_dumps({"note_id": str(note.id), "body_length": len(body)}),
        },
    )

    return {
        "id": note.id,
        "author_user_id": note.author_user_id,
        "body_markdown": note.body_markdown,
        "body_html_sanitized": note.body_html_sanitized,
        "created_at": note.created_at,
        "updated_at": note.updated_at,
    }


def _load_ticket_for_update(
    *,
    session: Session,
    organization_id: UUID,
    ticket_id: UUID,
) -> Ticket | None:
    return (
        session.execute(
            select(Ticket)
            .where(
                Ticket.organization_id == organization_id,
                Ticket.id == ticket_id,
            )
            .with_for_update()
        )
        .scalars()
        .first()
    )


def _ensure_org_membership(
    *,
    session: Session,
    organization_id: UUID,
    user_id: UUID,
) -> None:
    found = (
        session.execute(
            select(Membership.id).where(
                Membership.organization_id == organization_id,
                Membership.user_id == user_id,
            )
        )
        .scalars()
        .first()
    )
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="assignee_user_id is not a member of this organization",
        )


def _ensure_org_queue(
    *,
    session: Session,
    organization_id: UUID,
    queue_id: UUID,
) -> None:
    found = (
        session.execute(
            select(Queue.id).where(
                Queue.organization_id == organization_id,
                Queue.id == queue_id,
            )
        )
        .scalars()
        .first()
    )
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="assignee_queue_id is not in this organization",
        )


def _ticket_to_dict(ticket: Ticket) -> dict:
    return {
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
    }


def _json_dumps(payload: dict) -> str:
    import json

    return json.dumps(payload, separators=(",", ":"), sort_keys=True)
