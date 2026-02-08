from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_session_token
from app.db.session import get_session
from app.models.auth import AuthSession
from app.models.enums import MembershipRole
from app.models.identity import Membership, Organization, User

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass(frozen=True)
class OrgContext:
    organization: Organization
    membership: Membership
    user: User
    session: AuthSession

    @property
    def organization_id(self):
        return self.organization.id

    @property
    def role(self) -> MembershipRole:
        return self.membership.role


def require_csrf_header(request: Request) -> None:
    if request.method in SAFE_METHODS:
        return

    settings = get_settings()
    cookie_token = request.cookies.get(settings.CSRF_COOKIE_NAME)
    header_token = request.headers.get(settings.CSRF_HEADER_NAME)

    if not cookie_token or not header_token or cookie_token != header_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="CSRF token missing or invalid",
        )


def require_session(
    request: Request,
    session: Session = Depends(get_session),
) -> tuple[AuthSession, User]:
    settings = get_settings()
    raw = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not raw:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    token_hash = hash_session_token(raw)
    now = datetime.now(UTC)

    auth_session = (
        session.execute(
            select(AuthSession).where(
                AuthSession.token_hash == token_hash,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now,
            )
        )
        .scalars()
        .first()
    )
    if auth_session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid session")

    user = session.get(User, auth_session.user_id)
    if user is None or user.is_disabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User disabled or missing"
        )

    return auth_session, user


def require_org(
    auth: tuple[AuthSession, User] = Depends(require_session),
    session: Session = Depends(get_session),
) -> OrgContext:
    auth_session, user = auth

    org = session.get(Organization, auth_session.active_organization_id)
    if org is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization missing")

    membership = (
        session.execute(
            select(Membership).where(
                Membership.organization_id == org.id,
                Membership.user_id == user.id,
            )
        )
        .scalars()
        .first()
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this organization"
        )

    return OrgContext(organization=org, membership=membership, user=user, session=auth_session)


def require_roles(roles: list[MembershipRole]):
    allowed = set(roles)

    def _dep(org: OrgContext = Depends(require_org)) -> OrgContext:
        if org.membership.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role")
        return org

    return _dep
