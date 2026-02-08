from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.deps import require_csrf_header, require_session
from app.core.security import (
    clear_csrf_cookie,
    clear_session_cookie,
    new_random_token,
    set_csrf_cookie,
    set_session_cookie,
)
from app.db.session import get_session
from app.models.auth import AuthSession
from app.models.identity import User
from app.schemas.auth import CsrfTokenResponse, DevLoginRequest, LoginResponse, SwitchOrgRequest
from app.services.audit import log_event
from app.services.auth.sessions import create_dev_session, revoke_session, switch_org

router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(require_csrf_header)])


@router.get("/csrf", response_model=CsrfTokenResponse)
def issue_csrf(response: Response) -> CsrfTokenResponse:
    token = new_random_token()
    set_csrf_cookie(response, token)
    response.headers["Cache-Control"] = "no-store"
    return CsrfTokenResponse(csrf_token=token)


@router.post("/dev/login", response_model=LoginResponse)
def dev_login(
    payload: DevLoginRequest, response: Response, session: Session = Depends(get_session)
) -> LoginResponse:
    token, auth_session, org, membership, user = create_dev_session(
        session=session,
        email=payload.email,
        organization_name=payload.organization_name,
    )

    # Rotate CSRF on login to ensure we always have a token paired with a session.
    csrf = new_random_token()
    set_session_cookie(response, token)
    set_csrf_cookie(response, csrf)

    session.commit()
    response.headers["Cache-Control"] = "no-store"

    return LoginResponse(
        user=user,
        organization=org,
        role=membership.role.value,
        session=auth_session,
        csrf_token=csrf,
    )


@router.post("/logout")
def logout(
    response: Response,
    auth: tuple[AuthSession, User] = Depends(require_session),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    auth_session, user = auth
    revoke_session(session=session, auth_session=auth_session, reason="logout")
    log_event(
        session=session,
        organization_id=auth_session.active_organization_id,
        actor_user_id=user.id,
        event_type="auth.logout",
        event_data={},
    )
    session.commit()

    clear_session_cookie(response)
    clear_csrf_cookie(response)
    response.headers["Cache-Control"] = "no-store"
    return {"status": "ok"}


@router.post("/switch-org")
def switch_active_org(
    payload: SwitchOrgRequest,
    auth: tuple[AuthSession, User] = Depends(require_session),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    auth_session, user = auth
    membership = switch_org(
        session=session,
        auth_session=auth_session,
        user_id=user.id,
        organization_id=payload.organization_id,
    )
    log_event(
        session=session,
        organization_id=payload.organization_id,
        actor_user_id=user.id,
        event_type="auth.switch_org",
        event_data={"role": membership.role.value},
    )
    session.commit()
    return {"status": "ok"}
