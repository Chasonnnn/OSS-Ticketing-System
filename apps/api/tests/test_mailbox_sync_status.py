from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.main import create_app
from app.models.enums import JobStatus, JobType, MailboxProvider, MailboxPurpose
from app.models.jobs import BgJob
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


def test_sync_status_reports_lag_and_job_counts(db_session: Session) -> None:
    app = create_app()
    client = TestClient(app)

    login = _dev_login(
        client,
        email="sync-status-admin@example.com",
        organization_name="Org Sync Status",
    )
    org_id = UUID(login["organization"]["id"])

    cred = OAuthCredential(
        organization_id=org_id,
        provider="google",
        subject="journal-sync-status@example.com",
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
        email_address="journal-sync-status@example.com",
        oauth_credential_id=cred.id,
        is_enabled=True,
        gmail_history_id=321,
        last_full_sync_at=datetime.now(UTC) - timedelta(hours=2),
        last_incremental_sync_at=datetime.now(UTC) - timedelta(minutes=3),
        last_sync_error=None,
    )
    db_session.add(mailbox)
    db_session.flush()

    db_session.add_all(
        [
            BgJob(
                organization_id=org_id,
                mailbox_id=mailbox.id,
                type=JobType.mailbox_backfill,
                status=JobStatus.queued,
                payload={},
                dedupe_key=f"mailbox_backfill:{mailbox.id}",
            ),
            BgJob(
                organization_id=org_id,
                mailbox_id=mailbox.id,
                type=JobType.mailbox_history_sync,
                status=JobStatus.running,
                payload={},
                dedupe_key=f"mailbox_history_sync:{mailbox.id}",
            ),
            BgJob(
                organization_id=org_id,
                mailbox_id=mailbox.id,
                type=JobType.occurrence_fetch_raw,
                status=JobStatus.queued,
                payload={"occurrence_id": str(uuid4())},
                dedupe_key=f"occurrence_fetch_raw:{uuid4()}",
            ),
            BgJob(
                organization_id=org_id,
                mailbox_id=mailbox.id,
                type=JobType.occurrence_fetch_raw,
                status=JobStatus.queued,
                payload={"occurrence_id": str(uuid4())},
                dedupe_key=f"occurrence_fetch_raw:{uuid4()}",
            ),
        ]
    )
    db_session.commit()

    res = client.get(f"/mailboxes/{mailbox.id}/sync/status")
    assert res.status_code == 200
    body = res.json()

    assert body["mailbox_id"] == str(mailbox.id)
    assert body["is_enabled"] is True
    assert body["gmail_history_id"] == 321
    assert body["queued_jobs_by_type"]["mailbox_backfill"] == 1
    assert body["queued_jobs_by_type"]["occurrence_fetch_raw"] == 2
    assert body["running_jobs_by_type"]["mailbox_history_sync"] == 1
    assert body["sync_lag_seconds"] >= 120


def test_sync_status_returns_404_for_unknown_mailbox() -> None:
    app = create_app()
    client = TestClient(app)

    _dev_login(
        client,
        email="sync-status-admin2@example.com",
        organization_name="Org Sync Status 2",
    )

    res = client.get(f"/mailboxes/{uuid4()}/sync/status")
    assert res.status_code == 404
