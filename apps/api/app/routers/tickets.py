from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.deps import OrgContext, require_csrf_header, require_roles
from app.db.session import get_session
from app.models.enums import MembershipRole, TicketStatus
from app.schemas.tickets import (
    RecipientAllowlistCreateRequest,
    RecipientAllowlistOut,
    RecipientAllowlistUpdateRequest,
    RoutingRuleCreateRequest,
    RoutingRuleOut,
    RoutingRuleUpdateRequest,
    RoutingSimulationAppliedActions,
    RoutingSimulationMatchedRule,
    RoutingSimulationRequest,
    RoutingSimulationResponse,
    SendIdentityOut,
    TicketDetailResponse,
    TicketListResponse,
    TicketNoteCreateRequest,
    TicketNoteOut,
    TicketOut,
    TicketReplyRequest,
    TicketReplyResponse,
    TicketSavedViewCreateRequest,
    TicketSavedViewOut,
    TicketUpdateRequest,
)
from app.services.routing_simulator import simulate_routing
from app.services.ticket_commands import create_ticket_note, update_ticket
from app.services.ticket_outbound import list_send_identities, queue_ticket_reply
from app.services.ticket_routing_admin import (
    create_allowlist_entry,
    create_routing_rule,
    delete_allowlist_entry,
    delete_routing_rule,
    list_allowlist,
    list_routing_rules,
    update_allowlist_entry,
    update_routing_rule,
)
from app.services.ticket_saved_views import create_saved_view, delete_saved_view, list_saved_views
from app.services.ticket_views import (
    get_ticket_attachment_download,
    get_ticket_detail,
    list_tickets,
)

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


@router.get("/send-identities", response_model=list[SendIdentityOut])
def ticket_send_identities(
    org: OrgContext = Depends(require_roles([MembershipRole.admin, MembershipRole.agent])),
    session: Session = Depends(get_session),
) -> list[SendIdentityOut]:
    rows = list_send_identities(session=session, organization_id=org.organization.id)
    return [SendIdentityOut(**row) for row in rows]


@router.post(
    "/saved-views",
    response_model=TicketSavedViewOut,
    status_code=status.HTTP_201_CREATED,
)
def ticket_saved_view_create(
    payload: TicketSavedViewCreateRequest,
    org: OrgContext = Depends(require_roles([MembershipRole.admin, MembershipRole.agent])),
    session: Session = Depends(get_session),
) -> TicketSavedViewOut:
    row = create_saved_view(
        session=session,
        organization_id=org.organization.id,
        actor_user_id=org.user.id,
        name=payload.name,
        filters=payload.filters,
    )
    session.commit()
    return TicketSavedViewOut(**row)


@router.get("/saved-views", response_model=list[TicketSavedViewOut])
def ticket_saved_views_list(
    org: OrgContext = Depends(
        require_roles([MembershipRole.admin, MembershipRole.agent, MembershipRole.viewer])
    ),
    session: Session = Depends(get_session),
) -> list[TicketSavedViewOut]:
    rows = list_saved_views(session=session, organization_id=org.organization.id)
    return [TicketSavedViewOut(**row) for row in rows]


@router.delete("/saved-views/{saved_view_id}", status_code=status.HTTP_204_NO_CONTENT)
def ticket_saved_view_delete(
    saved_view_id: UUID,
    org: OrgContext = Depends(require_roles([MembershipRole.admin, MembershipRole.agent])),
    session: Session = Depends(get_session),
) -> None:
    delete_saved_view(
        session=session,
        organization_id=org.organization.id,
        actor_user_id=org.user.id,
        saved_view_id=saved_view_id,
    )
    session.commit()
    return None


@router.post("/routing/simulate", response_model=RoutingSimulationResponse)
def ticket_routing_simulate(
    payload: RoutingSimulationRequest,
    org: OrgContext = Depends(require_roles([MembershipRole.admin, MembershipRole.agent])),
    session: Session = Depends(get_session),
) -> RoutingSimulationResponse:
    simulated = simulate_routing(
        session=session,
        organization_id=org.organization.id,
        recipient=payload.recipient,
        sender_email=payload.sender_email,
        direction=payload.direction,
    )
    return RoutingSimulationResponse(
        allowlisted=simulated.allowlisted,
        would_mark_spam=simulated.would_mark_spam,
        matched_rule=(
            RoutingSimulationMatchedRule(**simulated.matched_rule)
            if simulated.matched_rule is not None
            else None
        ),
        applied_actions=RoutingSimulationAppliedActions(**simulated.applied_actions),
        explanation=simulated.explanation,
    )


@router.get("/routing/allowlist", response_model=list[RecipientAllowlistOut])
def routing_allowlist_list(
    org: OrgContext = Depends(require_roles([MembershipRole.admin])),
    session: Session = Depends(get_session),
) -> list[RecipientAllowlistOut]:
    rows = list_allowlist(session=session, organization_id=org.organization.id)
    return [RecipientAllowlistOut(**row) for row in rows]


@router.post(
    "/routing/allowlist",
    response_model=RecipientAllowlistOut,
    status_code=status.HTTP_201_CREATED,
)
def routing_allowlist_create(
    payload: RecipientAllowlistCreateRequest,
    org: OrgContext = Depends(require_roles([MembershipRole.admin])),
    session: Session = Depends(get_session),
) -> RecipientAllowlistOut:
    row = create_allowlist_entry(
        session=session,
        organization_id=org.organization.id,
        actor_user_id=org.user.id,
        pattern=payload.pattern,
        is_enabled=payload.is_enabled,
    )
    session.commit()
    return RecipientAllowlistOut(**row)


@router.patch("/routing/allowlist/{allowlist_id}", response_model=RecipientAllowlistOut)
def routing_allowlist_update(
    allowlist_id: UUID,
    payload: RecipientAllowlistUpdateRequest,
    org: OrgContext = Depends(require_roles([MembershipRole.admin])),
    session: Session = Depends(get_session),
) -> RecipientAllowlistOut:
    row = update_allowlist_entry(
        session=session,
        organization_id=org.organization.id,
        actor_user_id=org.user.id,
        allowlist_id=allowlist_id,
        updates=payload.model_dump(exclude_unset=True),
    )
    session.commit()
    return RecipientAllowlistOut(**row)


@router.delete("/routing/allowlist/{allowlist_id}", status_code=status.HTTP_204_NO_CONTENT)
def routing_allowlist_delete(
    allowlist_id: UUID,
    org: OrgContext = Depends(require_roles([MembershipRole.admin])),
    session: Session = Depends(get_session),
) -> None:
    delete_allowlist_entry(
        session=session,
        organization_id=org.organization.id,
        actor_user_id=org.user.id,
        allowlist_id=allowlist_id,
    )
    session.commit()
    return None


@router.get("/routing/rules", response_model=list[RoutingRuleOut])
def routing_rules_list(
    org: OrgContext = Depends(require_roles([MembershipRole.admin])),
    session: Session = Depends(get_session),
) -> list[RoutingRuleOut]:
    rows = list_routing_rules(session=session, organization_id=org.organization.id)
    return [RoutingRuleOut(**row) for row in rows]


@router.post(
    "/routing/rules",
    response_model=RoutingRuleOut,
    status_code=status.HTTP_201_CREATED,
)
def routing_rules_create(
    payload: RoutingRuleCreateRequest,
    org: OrgContext = Depends(require_roles([MembershipRole.admin])),
    session: Session = Depends(get_session),
) -> RoutingRuleOut:
    row = create_routing_rule(
        session=session,
        organization_id=org.organization.id,
        actor_user_id=org.user.id,
        payload=payload.model_dump(exclude_unset=True),
    )
    session.commit()
    return RoutingRuleOut(**row)


@router.patch("/routing/rules/{rule_id}", response_model=RoutingRuleOut)
def routing_rules_update(
    rule_id: UUID,
    payload: RoutingRuleUpdateRequest,
    org: OrgContext = Depends(require_roles([MembershipRole.admin])),
    session: Session = Depends(get_session),
) -> RoutingRuleOut:
    row = update_routing_rule(
        session=session,
        organization_id=org.organization.id,
        actor_user_id=org.user.id,
        rule_id=rule_id,
        updates=payload.model_dump(exclude_unset=True),
    )
    session.commit()
    return RoutingRuleOut(**row)


@router.delete("/routing/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def routing_rules_delete(
    rule_id: UUID,
    org: OrgContext = Depends(require_roles([MembershipRole.admin])),
    session: Session = Depends(get_session),
) -> None:
    delete_routing_rule(
        session=session,
        organization_id=org.organization.id,
        actor_user_id=org.user.id,
        rule_id=rule_id,
    )
    session.commit()
    return None


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


@router.get("/{ticket_id}/attachments/{attachment_id}/download")
def ticket_attachment_download(
    ticket_id: UUID,
    attachment_id: UUID,
    org: OrgContext = Depends(
        require_roles([MembershipRole.admin, MembershipRole.agent, MembershipRole.viewer])
    ),
    session: Session = Depends(get_session),
) -> Response:
    download = get_ticket_attachment_download(
        session=session,
        organization_id=org.organization.id,
        ticket_id=ticket_id,
        attachment_id=attachment_id,
    )
    if download.redirect_url:
        return RedirectResponse(
            url=download.redirect_url,
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
        )
    assert download.bytes_data is not None
    return Response(
        content=download.bytes_data,
        media_type=download.content_type,
        headers={"content-disposition": download.content_disposition},
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
    "/{ticket_id}/reply",
    response_model=TicketReplyResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def ticket_reply(
    ticket_id: UUID,
    payload: TicketReplyRequest,
    org: OrgContext = Depends(require_roles([MembershipRole.admin, MembershipRole.agent])),
    session: Session = Depends(get_session),
) -> TicketReplyResponse:
    queued = queue_ticket_reply(
        session=session,
        organization_id=org.organization.id,
        actor_user_id=org.user.id,
        ticket_id=ticket_id,
        send_identity_id=payload.send_identity_id,
        to_emails=payload.to_emails,
        cc_emails=payload.cc_emails,
        subject=payload.subject,
        body_text=payload.body_text,
    )
    session.commit()
    return TicketReplyResponse(**queued)


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
