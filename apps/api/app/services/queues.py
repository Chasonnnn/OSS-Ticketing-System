from __future__ import annotations

import re
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.identity import Queue
from app.services.audit import log_event

_slug_re = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    value = value.strip().lower()
    value = _slug_re.sub("-", value).strip("-")
    return value


def list_queues(*, session: Session, organization_id: UUID) -> list[Queue]:
    return (
        session.execute(
            select(Queue)
            .where(Queue.organization_id == organization_id)
            .order_by(Queue.created_at.asc())
        )
        .scalars()
        .all()
    )


def create_queue(
    *,
    session: Session,
    organization_id: UUID,
    actor_user_id: UUID,
    name: str,
    slug: str | None,
) -> Queue:
    name = name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Queue name is required"
        )

    slug_final = _slugify(slug or name)
    if not slug_final:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Queue slug is required"
        )

    q = Queue(organization_id=organization_id, name=name, slug=slug_final)
    session.add(q)
    try:
        session.flush()
    except IntegrityError as e:
        # Unique(org, slug) is enforced at the DB level.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Queue slug already exists"
        ) from e

    log_event(
        session=session,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        event_type="queues.created",
        event_data={"queue_id": str(q.id), "slug": slug_final},
    )

    return q
