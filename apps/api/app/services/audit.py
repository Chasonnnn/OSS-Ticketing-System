from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.models.audit import AuditEvent


def log_event(
    *,
    session: Session,
    organization_id: UUID,
    actor_user_id: UUID | None,
    event_type: str,
    event_data: dict,
) -> AuditEvent:
    evt = AuditEvent(
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        event_type=event_type,
        event_data=event_data,
    )
    session.add(evt)
    session.flush()
    return evt
