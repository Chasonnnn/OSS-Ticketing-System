from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import create_app
from app.models.enums import MailboxProvider, MailboxPurpose
from app.models.mail import Mailbox, OAuthCredential


def _get_csrf(client: TestClient) -> str:
    res = client.get("/auth/csrf")
    assert res.status_code == 200
    return res.json()["csrf_token"]


def _dev_login(client: TestClient, *, email: str, organization_name: str) -> dict:
    csrf = _get_csrf(client)
    res = client.post(
        "/auth/dev/login",
        json={"email": email, "organization_name": organization_name},
        headers={"x-csrf-token": csrf},
    )
    assert res.status_code == 200
    return res.json()


def test_manual_pause_sets_pause_window_and_reason(db_session: Session) -> None:
    app = create_app()
    client = TestClient(app)

    login = _dev_login(
        client,
        email="pause-admin@example.com",
        organization_name="Org Pause Sync",
    )
    csrf = login["csrf_token"]
    org_id = UUID(login["organization"]["id"])

    cred = OAuthCredential(
        organization_id=org_id,
        provider="google",
        subject="pause-mailbox@example.com",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        encrypted_refresh_token=b"refresh",
        encrypted_access_token=b"access",
        access_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(cred)
    db_session.flush()

    mailbox = Mailbox(
        organization_id=org_id,
        purpose=MailboxPurpose.journal,
        provider=MailboxProvider.gmail,
        email_address="pause-mailbox@example.com",
        oauth_credential_id=cred.id,
        is_enabled=True,
        ingestion_paused_until=None,
        ingestion_pause_reason=None,
    )
    db_session.add(mailbox)
    db_session.commit()

    res = client.post(
        f"/mailboxes/{mailbox.id}/sync/pause?minutes=45",
        headers={"x-csrf-token": csrf},
    )
    assert res.status_code == 200
    body = res.json()

    assert body["mailbox_id"] == str(mailbox.id)
    assert body["paused"] is True
    assert body["paused_until"] is not None
    assert body["pause_reason"] is not None
    assert "manual pause" in body["pause_reason"].lower()

    db_session.expire_all()
    refreshed_mailbox = db_session.get(Mailbox, mailbox.id)
    assert refreshed_mailbox is not None
    assert refreshed_mailbox.ingestion_paused_until is not None
    assert refreshed_mailbox.ingestion_paused_until > datetime.now(UTC) + timedelta(minutes=44)
    assert refreshed_mailbox.ingestion_pause_reason is not None
    assert "manual pause" in refreshed_mailbox.ingestion_pause_reason.lower()


def test_manual_pause_returns_404_for_unknown_mailbox() -> None:
    app = create_app()
    client = TestClient(app)

    login = _dev_login(
        client,
        email="pause-admin2@example.com",
        organization_name="Org Pause Sync 2",
    )
    csrf = login["csrf_token"]

    res = client.post(
        f"/mailboxes/{uuid4()}/sync/pause",
        headers={"x-csrf-token": csrf},
    )
    assert res.status_code == 404
