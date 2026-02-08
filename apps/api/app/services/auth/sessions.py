from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_session_token, new_random_token
from app.models.auth import AuthSession
from app.models.enums import MembershipRole
from app.models.identity import Membership, Organization, User
from app.services.audit import log_event


def _normalize_email(email: str) -> str:
    return email.strip().lower()


def create_dev_session(
    *,
    session: Session,
    email: str,
    organization_name: str,
) -> tuple[str, AuthSession, Organization, Membership, User]:
    settings = get_settings()
    if not settings.ALLOW_DEV_LOGIN:
        # Hide route behavior in prod rather than exposing an auth bypass.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    email_norm = _normalize_email(email)
    if "@" not in email_norm or " " in email_norm:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid email"
        )

    org_name = organization_name.strip()
    if not org_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Organization name is required"
        )

    org = (
        session.execute(
            select(Organization)
            .where(Organization.name == org_name)
            .order_by(Organization.created_at.asc())
        )
        .scalars()
        .first()
    )
    if org is None:
        org = Organization(name=org_name)
        session.add(org)
        session.flush()

    user = session.execute(select(User).where(User.email == email_norm)).scalars().first()
    if user is None:
        user = User(email=email_norm)
        session.add(user)
        session.flush()

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
        membership = Membership(organization_id=org.id, user_id=user.id, role=MembershipRole.admin)
        session.add(membership)
        session.flush()

    token = new_random_token()
    token_hash = hash_session_token(token)
    now = datetime.now(UTC)
    expires_at = now + timedelta(seconds=settings.SESSION_TTL_SECONDS)

    auth_session = AuthSession(
        user_id=user.id,
        active_organization_id=org.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    session.add(auth_session)
    session.flush()

    log_event(
        session=session,
        organization_id=org.id,
        actor_user_id=user.id,
        event_type="auth.dev_login",
        event_data={},
    )

    return token, auth_session, org, membership, user


def revoke_session(
    *,
    session: Session,
    auth_session: AuthSession,
    reason: str,
) -> None:
    auth_session.revoked_at = datetime.now(UTC)
    auth_session.revoked_reason = reason
    session.add(auth_session)


def switch_org(
    *,
    session: Session,
    auth_session: AuthSession,
    user_id: UUID,
    organization_id: UUID,
) -> Membership:
    membership = (
        session.execute(
            select(Membership).where(
                Membership.organization_id == organization_id,
                Membership.user_id == user_id,
            )
        )
        .scalars()
        .first()
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this organization"
        )

    auth_session.active_organization_id = organization_id
    session.add(auth_session)
    return membership
