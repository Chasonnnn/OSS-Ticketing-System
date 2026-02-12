from __future__ import annotations

from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import OrgContext, require_csrf_header, require_roles
from app.core.http import get_http_client
from app.db.session import get_session
from app.models.enums import MembershipRole
from app.models.mail import Mailbox
from app.schemas.mailboxes import (
    ConnectivityResponse,
    GmailOAuthCallbackResponse,
    GmailOAuthStartResponse,
    MailboxOut,
    MailboxSyncEnqueueResponse,
)
from app.services.mailbox_sync import enqueue_mailbox_backfill, enqueue_mailbox_history_sync
from app.services.mailboxes import (
    check_gmail_connectivity,
    complete_gmail_journal_oauth,
    start_gmail_journal_oauth,
)

router = APIRouter(
    prefix="/mailboxes",
    tags=["mailboxes"],
    dependencies=[Depends(require_csrf_header)],
)


@router.get("", response_model=list[MailboxOut])
def mailboxes_list(
    org: OrgContext = Depends(require_roles([MembershipRole.admin])),
    session: Session = Depends(get_session),
) -> list[MailboxOut]:
    return (
        session.execute(select(Mailbox).where(Mailbox.organization_id == org.organization.id))
        .scalars()
        .all()
    )


@router.post("/gmail/journal/oauth/start", response_model=GmailOAuthStartResponse)
def gmail_journal_oauth_start(
    org: OrgContext = Depends(require_roles([MembershipRole.admin])),
    session: Session = Depends(get_session),
) -> GmailOAuthStartResponse:
    url = start_gmail_journal_oauth(
        session=session,
        organization_id=org.organization.id,
        user_id=org.user.id,
    )
    session.commit()
    return GmailOAuthStartResponse(authorization_url=url)


@router.get("/gmail/oauth/callback", response_model=GmailOAuthCallbackResponse)
def gmail_oauth_callback(
    state: str,
    request: Request,
    response: Response,
    code: str | None = None,
    error: str | None = None,
    org: OrgContext = Depends(require_roles([MembershipRole.admin])),
    session: Session = Depends(get_session),
    http_client: httpx.Client = Depends(get_http_client),
) -> GmailOAuthCallbackResponse:
    if error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"OAuth error: {error}")
    if not code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing OAuth code")

    mailbox = complete_gmail_journal_oauth(
        session=session,
        http_client=http_client,
        organization_id=org.organization.id,
        user_id=org.user.id,
        state=state,
        code=code,
    )
    session.commit()

    response.headers["Cache-Control"] = "no-store"

    accept = request.headers.get("accept") or ""
    if "text/html" in accept:
        settings = get_settings()
        url = f"{settings.FRONTEND_URL}/mailboxes/connected?mailbox_id={mailbox.id}"
        return RedirectResponse(
            url=url,
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Cache-Control": "no-store"},
        )

    return GmailOAuthCallbackResponse(status="connected", mailbox_id=mailbox.id)


@router.get("/{mailbox_id}/connectivity", response_model=ConnectivityResponse)
def mailbox_connectivity(
    mailbox_id: UUID,
    org: OrgContext = Depends(require_roles([MembershipRole.admin])),
    session: Session = Depends(get_session),
    http_client: httpx.Client = Depends(get_http_client),
) -> ConnectivityResponse:
    chk = check_gmail_connectivity(
        session=session,
        http_client=http_client,
        organization_id=org.organization.id,
        mailbox_id=mailbox_id,
    )
    session.commit()
    return ConnectivityResponse(
        status=chk.status,
        profile_email=chk.profile_email,
        scopes=chk.scopes,
        error=chk.error,
    )


@router.post("/{mailbox_id}/sync/backfill", response_model=MailboxSyncEnqueueResponse)
def mailbox_sync_backfill_enqueue(
    mailbox_id: UUID,
    org: OrgContext = Depends(require_roles([MembershipRole.admin])),
    session: Session = Depends(get_session),
) -> MailboxSyncEnqueueResponse:
    _ensure_mailbox_exists(
        session=session, organization_id=org.organization.id, mailbox_id=mailbox_id
    )
    job_id = enqueue_mailbox_backfill(
        session=session,
        organization_id=org.organization.id,
        mailbox_id=mailbox_id,
        reason="manual_admin_backfill",
    )
    session.commit()
    return MailboxSyncEnqueueResponse(job_type="mailbox_backfill", job_id=job_id)


@router.post("/{mailbox_id}/sync/history", response_model=MailboxSyncEnqueueResponse)
def mailbox_sync_history_enqueue(
    mailbox_id: UUID,
    org: OrgContext = Depends(require_roles([MembershipRole.admin])),
    session: Session = Depends(get_session),
) -> MailboxSyncEnqueueResponse:
    _ensure_mailbox_exists(
        session=session, organization_id=org.organization.id, mailbox_id=mailbox_id
    )
    job_id = enqueue_mailbox_history_sync(
        session=session,
        organization_id=org.organization.id,
        mailbox_id=mailbox_id,
        reason="manual_admin_history",
    )
    session.commit()
    return MailboxSyncEnqueueResponse(job_type="mailbox_history_sync", job_id=job_id)


def _ensure_mailbox_exists(*, session: Session, organization_id: UUID, mailbox_id: UUID) -> None:
    row = (
        session.execute(
            select(Mailbox.id).where(
                Mailbox.organization_id == organization_id,
                Mailbox.id == mailbox_id,
            )
        )
        .scalars()
        .first()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mailbox not found")
