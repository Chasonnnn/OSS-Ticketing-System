from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.tickets import TicketSavedView
from app.services.audit import log_event

_ALLOWED_FILTER_KEYS = {"q", "status", "assignee_user_id", "assignee_queue_id", "limit"}


def list_saved_views(*, session: Session, organization_id: UUID) -> list[dict]:
    rows = (
        session.execute(
            select(TicketSavedView)
            .where(TicketSavedView.organization_id == organization_id)
            .order_by(TicketSavedView.created_at.asc(), TicketSavedView.id.asc())
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": row.id,
            "name": row.name,
            "filters": row.filters_json or {},
            "is_default": row.is_default,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
        for row in rows
    ]


def create_saved_view(
    *,
    session: Session,
    organization_id: UUID,
    actor_user_id: UUID,
    name: str,
    filters: dict,
) -> dict:
    name = name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="name is required",
        )

    validated_filters = _validate_filters(filters=filters)
    row = TicketSavedView(
        organization_id=organization_id,
        name=name,
        filters_json=validated_filters,
        is_default=False,
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Saved view name already exists",
        ) from exc

    log_event(
        session=session,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        event_type="tickets.saved_view.created",
        event_data={"saved_view_id": str(row.id), "name": row.name},
    )
    return {
        "id": row.id,
        "name": row.name,
        "filters": row.filters_json or {},
        "is_default": row.is_default,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def delete_saved_view(
    *,
    session: Session,
    organization_id: UUID,
    actor_user_id: UUID,
    saved_view_id: UUID,
) -> None:
    row = (
        session.execute(
            select(TicketSavedView)
            .where(
                TicketSavedView.organization_id == organization_id,
                TicketSavedView.id == saved_view_id,
            )
            .with_for_update()
        )
        .scalars()
        .first()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Saved view not found")

    session.delete(row)
    session.flush()
    log_event(
        session=session,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        event_type="tickets.saved_view.deleted",
        event_data={"saved_view_id": str(saved_view_id)},
    )


def _validate_filters(*, filters: dict) -> dict:
    if not isinstance(filters, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="filters must be an object",
        )

    out: dict[str, object] = {}
    for key, value in filters.items():
        if key not in _ALLOWED_FILTER_KEYS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Unsupported filter key: {key}",
            )

        if value is None:
            continue

        if key == "limit":
            try:
                parsed = int(value)
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="limit must be an integer",
                ) from exc
            out[key] = max(1, min(parsed, 100))
            continue

        if not isinstance(value, str):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{key} must be a string",
            )
        text_value = value.strip()
        if not text_value:
            continue
        out[key] = text_value

    return out
