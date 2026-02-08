from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.deps import OrgContext, require_csrf_header, require_org, require_roles
from app.db.session import get_session
from app.models.enums import MembershipRole
from app.schemas.queues import QueueCreateRequest, QueueOut
from app.services.queues import create_queue, list_queues

router = APIRouter(prefix="/queues", tags=["queues"], dependencies=[Depends(require_csrf_header)])


@router.get("", response_model=list[QueueOut])
def queues_list(
    org: OrgContext = Depends(require_org), session: Session = Depends(get_session)
) -> list[QueueOut]:
    return list_queues(session=session, organization_id=org.organization.id)


@router.post("", response_model=QueueOut, status_code=status.HTTP_201_CREATED)
def queues_create(
    payload: QueueCreateRequest,
    org: OrgContext = Depends(require_roles([MembershipRole.admin])),
    session: Session = Depends(get_session),
) -> QueueOut:
    q = create_queue(
        session=session,
        organization_id=org.organization.id,
        actor_user_id=org.user.id,
        name=payload.name,
        slug=payload.slug,
    )
    session.commit()
    return q
