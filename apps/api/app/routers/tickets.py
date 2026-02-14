from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.deps import OrgContext, require_csrf_header, require_roles
from app.db.session import get_session
from app.models.enums import MembershipRole, TicketStatus
from app.schemas.tickets import (
    TicketDetailResponse,
    TicketListResponse,
    TicketNoteCreateRequest,
    TicketNoteOut,
    TicketOut,
    TicketUpdateRequest,
)
from app.services.ticket_commands import create_ticket_note, update_ticket
from app.services.ticket_views import get_ticket_detail, list_tickets

router = APIRouter(prefix="/tickets", tags=["tickets"], dependencies=[Depends(require_csrf_header)])


@router.get("", response_model=TicketListResponse)
def tickets_list(
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = Query(default=None),
    status: TicketStatus | None = Query(default=None),
    q: str | None = Query(default=None, max_length=200),
    assignee_user_id: UUID | None = Query(default=None),
    assignee_queue_id: UUID | None = Query(default=None),
    org: OrgContext = Depends(
        require_roles([MembershipRole.admin, MembershipRole.agent, MembershipRole.viewer])
    ),
    session: Session = Depends(get_session),
) -> TicketListResponse:
    page = list_tickets(
        session=session,
        organization_id=org.organization.id,
        limit=limit,
        cursor=cursor,
        status_filter=status.value if status else None,
        q=q,
        assignee_user_id=assignee_user_id,
        assignee_queue_id=assignee_queue_id,
    )
    return TicketListResponse(items=page.items, next_cursor=page.next_cursor)


@router.get("/{ticket_id}", response_model=TicketDetailResponse)
def ticket_detail(
    ticket_id: UUID,
    org: OrgContext = Depends(
        require_roles([MembershipRole.admin, MembershipRole.agent, MembershipRole.viewer])
    ),
    session: Session = Depends(get_session),
) -> TicketDetailResponse:
    detail = get_ticket_detail(
        session=session,
        organization_id=org.organization.id,
        ticket_id=ticket_id,
    )
    return TicketDetailResponse(
        ticket=detail.ticket,
        messages=detail.messages,
        events=detail.events,
        notes=detail.notes,
    )


@router.patch("/{ticket_id}", response_model=TicketOut)
def ticket_update(
    ticket_id: UUID,
    payload: TicketUpdateRequest,
    org: OrgContext = Depends(require_roles([MembershipRole.admin, MembershipRole.agent])),
    session: Session = Depends(get_session),
) -> TicketOut:
    updated = update_ticket(
        session=session,
        organization_id=org.organization.id,
        ticket_id=ticket_id,
        actor_user_id=org.user.id,
        updates=payload.model_dump(exclude_unset=True),
    )
    session.commit()
    return TicketOut(**updated)


@router.post(
    "/{ticket_id}/notes",
    response_model=TicketNoteOut,
    status_code=status.HTTP_201_CREATED,
)
def ticket_note_create(
    ticket_id: UUID,
    payload: TicketNoteCreateRequest,
    org: OrgContext = Depends(require_roles([MembershipRole.admin, MembershipRole.agent])),
    session: Session = Depends(get_session),
) -> TicketNoteOut:
    note = create_ticket_note(
        session=session,
        organization_id=org.organization.id,
        ticket_id=ticket_id,
        actor_user_id=org.user.id,
        body_markdown=payload.body_markdown,
    )
    session.commit()
    return TicketNoteOut(**note)
