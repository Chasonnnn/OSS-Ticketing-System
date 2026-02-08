from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import decrypt_bytes, encrypt_bytes
from app.core.security import new_random_token
from app.models.enums import MailboxProvider, MailboxPurpose
from app.models.mail import Mailbox, OAuthCredential
from app.models.oauth import OAuthState
from app.services.audit import log_event
from app.services.google.gmail import get_profile
from app.services.google.oauth import (
    build_authorization_url,
    exchange_code_for_tokens,
    refresh_access_token,
)

REQUIRED_GMAIL_SCOPES = [
    # Needed for journal ingestion (read-only access, including RFC822/raw).
    "https://www.googleapis.com/auth/gmail.readonly",
]


def _oauth_credential_aad(*, organization_id: UUID, subject: str) -> bytes:
    return f"oauth_credentials:{organization_id}:google:{subject}".encode()


@dataclass(frozen=True)
class ConnectivityCheck:
    status: str  # connected|degraded|paused|disabled
    profile_email: str | None
    scopes: list[str]
    error: str | None


def start_gmail_journal_oauth(
    *,
    session: Session,
    organization_id: UUID,
    user_id: UUID,
) -> str:
    settings = get_settings()
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google OAuth is not configured",
        )

    now = datetime.now(UTC)
    state = new_random_token()
    row = OAuthState(
        organization_id=organization_id,
        user_id=user_id,
        provider="google",
        purpose="gmail_journal",
        state=state,
        expires_at=now + timedelta(minutes=10),
    )
    session.add(row)
    session.flush()

    redirect_uri = f"{settings.API_BASE_URL}/mailboxes/gmail/oauth/callback"
    return build_authorization_url(
        client_id=settings.GOOGLE_CLIENT_ID,
        redirect_uri=redirect_uri,
        scopes=REQUIRED_GMAIL_SCOPES,
        state=state,
    )


def complete_gmail_journal_oauth(
    *,
    session: Session,
    http_client: httpx.Client,
    organization_id: UUID,
    user_id: UUID,
    state: str,
    code: str,
) -> Mailbox:
    settings = get_settings()
    now = datetime.now(UTC)

    oauth_state = (
        session.execute(
            select(OAuthState)
            .where(
                OAuthState.state == state,
                OAuthState.provider == "google",
                OAuthState.purpose == "gmail_journal",
            )
            .with_for_update()
        )
        .scalars()
        .first()
    )
    if oauth_state is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OAuth state")
    if oauth_state.used_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OAuth state already used",
        )
    if oauth_state.expires_at <= now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth state expired")
    if oauth_state.organization_id != organization_id or oauth_state.user_id != user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OAuth state mismatch")

    # One-time use (even if the upstream token exchange fails, force a new connect attempt).
    oauth_state.used_at = now
    session.add(oauth_state)
    session.flush()

    redirect_uri = f"{settings.API_BASE_URL}/mailboxes/gmail/oauth/callback"
    token = exchange_code_for_tokens(
        http_client,
        code=code,
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        redirect_uri=redirect_uri,
    )

    if not token.refresh_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Google did not return a refresh token. "
                "Try disconnecting/revoking access and reconnecting "
                "(prompt=consent, access_type=offline)."
            ),
        )

    scopes = sorted(set(token.scopes))
    missing = [s for s in REQUIRED_GMAIL_SCOPES if s not in scopes]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Missing required scopes: {', '.join(missing)}",
        )

    profile = get_profile(http_client, access_token=token.access_token)
    subject = profile.email_address.strip().lower()
    if not subject or "@" not in subject:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Gmail profile returned an invalid email address",
        )

    aad = _oauth_credential_aad(organization_id=organization_id, subject=subject)
    enc_refresh = encrypt_bytes(plaintext=token.refresh_token.encode("utf-8"), aad=aad)
    enc_access = encrypt_bytes(plaintext=token.access_token.encode("utf-8"), aad=aad)
    expires_at = now + timedelta(seconds=max(1, token.expires_in))

    cred = (
        session.execute(
            select(OAuthCredential).where(
                OAuthCredential.organization_id == organization_id,
                OAuthCredential.provider == "google",
                OAuthCredential.subject == subject,
            )
        )
        .scalars()
        .first()
    )
    if cred is None:
        cred = OAuthCredential(
            organization_id=organization_id,
            provider="google",
            subject=subject,
            scopes=scopes,
            encrypted_refresh_token=enc_refresh,
            encrypted_access_token=enc_access,
            access_token_expires_at=expires_at,
        )
        session.add(cred)
        session.flush()
    else:
        cred.scopes = scopes
        cred.encrypted_refresh_token = enc_refresh
        cred.encrypted_access_token = enc_access
        cred.access_token_expires_at = expires_at
        session.add(cred)
        session.flush()

    existing_journal = (
        session.execute(
            select(Mailbox).where(
                Mailbox.organization_id == organization_id,
                Mailbox.provider == MailboxProvider.gmail,
                Mailbox.purpose == MailboxPurpose.journal,
            )
        )
        .scalars()
        .first()
    )
    if existing_journal is not None and existing_journal.email_address != subject:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A journal mailbox is already connected for this organization",
        )

    mailbox = (
        session.execute(
            select(Mailbox).where(
                Mailbox.organization_id == organization_id,
                Mailbox.email_address == subject,
            )
        )
        .scalars()
        .first()
    )
    if mailbox is None:
        mailbox = Mailbox(
            organization_id=organization_id,
            purpose=MailboxPurpose.journal,
            provider=MailboxProvider.gmail,
            email_address=subject,
            display_name=None,
            oauth_credential_id=cred.id,
            is_enabled=True,
            gmail_profile_email=subject,
            gmail_history_id=profile.history_id,
            last_sync_error=None,
        )
        session.add(mailbox)
        session.flush()
    else:
        mailbox.purpose = MailboxPurpose.journal
        mailbox.provider = MailboxProvider.gmail
        mailbox.oauth_credential_id = cred.id
        mailbox.is_enabled = True
        mailbox.gmail_profile_email = subject
        mailbox.gmail_history_id = profile.history_id
        mailbox.last_sync_error = None
        session.add(mailbox)
        session.flush()

    log_event(
        session=session,
        organization_id=organization_id,
        actor_user_id=user_id,
        event_type="mailboxes.gmail_journal.connected",
        event_data={"mailbox_id": str(mailbox.id)},
    )

    return mailbox


def check_gmail_connectivity(
    *,
    session: Session,
    http_client: httpx.Client,
    organization_id: UUID,
    mailbox_id: UUID,
) -> ConnectivityCheck:
    mailbox = (
        session.execute(
            select(Mailbox).where(
                Mailbox.organization_id == organization_id,
                Mailbox.id == mailbox_id,
            )
        )
        .scalars()
        .first()
    )
    if mailbox is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mailbox not found")

    if not mailbox.is_enabled:
        return ConnectivityCheck(
            status="disabled",
            profile_email=mailbox.gmail_profile_email,
            scopes=[],
            error=None,
        )

    now = datetime.now(UTC)
    if mailbox.ingestion_paused_until and mailbox.ingestion_paused_until > now:
        return ConnectivityCheck(
            status="paused",
            profile_email=mailbox.gmail_profile_email,
            scopes=[],
            error=None,
        )

    cred = (
        session.execute(
            select(OAuthCredential).where(
                OAuthCredential.organization_id == organization_id,
                OAuthCredential.id == mailbox.oauth_credential_id,
            )
        )
        .scalars()
        .first()
    )
    if cred is None:
        return ConnectivityCheck(
            status="degraded",
            profile_email=mailbox.gmail_profile_email,
            scopes=[],
            error="Missing OAuth credential",
        )

    aad = _oauth_credential_aad(organization_id=organization_id, subject=cred.subject)
    scopes = sorted(set(cred.scopes))

    try:
        refresh_token = decrypt_bytes(blob=cred.encrypted_refresh_token, aad=aad).decode("utf-8")
    except Exception:  # noqa: BLE001
        return ConnectivityCheck(
            status="degraded",
            profile_email=mailbox.gmail_profile_email,
            scopes=scopes,
            error="Could not decrypt refresh token (check ENCRYPTION_KEY_BASE64)",
        )

    access_token: str | None = None
    if (
        cred.encrypted_access_token
        and cred.access_token_expires_at
        and cred.access_token_expires_at > now
    ):
        try:
            access_token = decrypt_bytes(blob=cred.encrypted_access_token, aad=aad).decode("utf-8")
        except Exception:  # noqa: BLE001
            access_token = None

    if not access_token:
        settings = get_settings()
        token = refresh_access_token(
            http_client,
            refresh_token=refresh_token,
            client_id=settings.GOOGLE_CLIENT_ID,
            client_secret=settings.GOOGLE_CLIENT_SECRET,
        )
        access_token = token.access_token
        cred.encrypted_access_token = encrypt_bytes(plaintext=access_token.encode("utf-8"), aad=aad)
        cred.access_token_expires_at = now + timedelta(seconds=max(1, token.expires_in))
        session.add(cred)
        session.flush()

    try:
        profile = get_profile(http_client, access_token=access_token)
    except HTTPException as e:
        mailbox.last_sync_error = e.detail
        session.add(mailbox)
        session.flush()
        return ConnectivityCheck(
            status="degraded",
            profile_email=mailbox.gmail_profile_email,
            scopes=scopes,
            error=str(e.detail),
        )

    mailbox.gmail_profile_email = profile.email_address.strip().lower()
    mailbox.gmail_history_id = profile.history_id
    mailbox.last_sync_error = None
    session.add(mailbox)
    session.flush()

    return ConnectivityCheck(
        status="connected",
        profile_email=mailbox.gmail_profile_email,
        scopes=scopes,
        error=None,
    )
