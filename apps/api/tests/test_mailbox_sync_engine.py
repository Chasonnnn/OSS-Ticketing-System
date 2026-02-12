from __future__ import annotations

import base64
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import encrypt_bytes
from app.main import create_app
from app.models.enums import JobStatus, JobType, MailboxProvider, MailboxPurpose
from app.models.identity import Organization
from app.models.jobs import BgJob
from app.models.mail import Mailbox, MessageOccurrence, OAuthCredential
from app.services.mailbox_sync import sync_mailbox_backfill, sync_mailbox_history


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


def _oauth_aad(*, organization_id: UUID, subject: str) -> bytes:
    return f"oauth_credentials:{organization_id}:google:{subject}".encode()


def _seed_mailbox(db_session: Session, *, email: str, history_id: int | None = 1) -> Mailbox:
    org = Organization(name=f"Org {email}")
    db_session.add(org)
    db_session.flush()

    subject = email.strip().lower()
    aad = _oauth_aad(organization_id=org.id, subject=subject)

    access_token = "access-token-seeded"
    refresh_token = "refresh-token-seeded"

    cred = OAuthCredential(
        organization_id=org.id,
        provider="google",
        subject=subject,
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        encrypted_refresh_token=encrypt_bytes(
            plaintext=refresh_token.encode("utf-8"),
            aad=aad,
        ),
        encrypted_access_token=encrypt_bytes(
            plaintext=access_token.encode("utf-8"),
            aad=aad,
        ),
        access_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(cred)
    db_session.flush()

    mailbox = Mailbox(
        organization_id=org.id,
        purpose=MailboxPurpose.journal,
        provider=MailboxProvider.gmail,
        email_address=subject,
        display_name="Journal",
        oauth_credential_id=cred.id,
        is_enabled=True,
        gmail_profile_email=subject,
        gmail_history_id=history_id,
        last_sync_error=None,
    )
    db_session.add(mailbox)
    db_session.flush()
    return mailbox


def _raw_b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def test_oauth_callback_enqueues_mailbox_backfill_job(db_session: Session) -> None:
    app = create_app()
    client = TestClient(app)

    login = _dev_login(
        client,
        email="sync-admin@gmail.test",
        organization_name="Org Sync Enqueue",
    )
    csrf = login["csrf_token"]

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://oauth2.googleapis.com/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "access-token-sync",
                    "expires_in": 3600,
                    "refresh_token": "refresh-token-sync",
                    "scope": "https://www.googleapis.com/auth/gmail.readonly",
                    "token_type": "Bearer",
                },
            )
        if str(request.url) == "https://gmail.googleapis.com/gmail/v1/users/me/profile":
            return httpx.Response(
                200,
                json={"emailAddress": "journal-sync@example.com", "historyId": "200"},
            )
        return httpx.Response(404, json={"error": "not_found"})

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, timeout=10.0)

    from app.core.http import get_http_client

    def override_http_client() -> Generator[httpx.Client, None, None]:
        yield http_client

    app.dependency_overrides[get_http_client] = override_http_client

    start = client.post("/mailboxes/gmail/journal/oauth/start", headers={"x-csrf-token": csrf})
    assert start.status_code == 200
    state = parse_qs(urlsplit(start.json()["authorization_url"]).query)["state"][0]

    callback = client.get(f"/mailboxes/gmail/oauth/callback?state={state}&code=test-code")
    assert callback.status_code == 200
    mailbox_id = UUID(callback.json()["mailbox_id"])

    jobs = (
        db_session.execute(
            select(BgJob).where(
                BgJob.type == JobType.mailbox_backfill,
                BgJob.mailbox_id == mailbox_id,
            )
        )
        .scalars()
        .all()
    )
    assert len(jobs) == 1
    assert jobs[0].status == JobStatus.queued
    assert jobs[0].dedupe_key == f"mailbox_backfill:{mailbox_id}"

    app.dependency_overrides.clear()
    http_client.close()


def test_mailbox_backfill_is_idempotent_and_enqueues_raw_fetch_jobs(db_session: Session) -> None:
    mailbox = _seed_mailbox(
        db_session,
        email="journal-backfill@example.com",
        history_id=100,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer access-token-seeded"
        url = request.url
        path = url.path
        params = dict(url.params)

        if path == "/gmail/v1/users/me/messages":
            if params.get("pageToken") is None:
                return httpx.Response(
                    200,
                    json={
                        "messages": [
                            {"id": "m-1", "threadId": "t-1"},
                        ],
                        "nextPageToken": "page-2",
                    },
                )
            assert params.get("pageToken") == "page-2"
            return httpx.Response(
                200,
                json={"messages": [{"id": "m-2", "threadId": "t-2"}]},
            )

        if path == "/gmail/v1/users/me/messages/m-1":
            assert params.get("format") == "raw"
            return httpx.Response(
                200,
                json={
                    "id": "m-1",
                    "threadId": "t-1",
                    "historyId": "201",
                    "internalDate": "1700000000000",
                    "labelIds": ["INBOX"],
                    "raw": _raw_b64url(b"raw-eml-1"),
                },
            )

        if path == "/gmail/v1/users/me/messages/m-2":
            assert params.get("format") == "raw"
            return httpx.Response(
                200,
                json={
                    "id": "m-2",
                    "threadId": "t-2",
                    "historyId": "250",
                    "internalDate": "1700000001000",
                    "labelIds": ["INBOX"],
                    "raw": _raw_b64url(b"raw-eml-2"),
                },
            )

        return httpx.Response(404, json={"error": "not_found"})

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, timeout=10.0)

    sync_mailbox_backfill(
        session=db_session,
        http_client=http_client,
        organization_id=mailbox.organization_id,
        mailbox_id=mailbox.id,
    )
    sync_mailbox_backfill(
        session=db_session,
        http_client=http_client,
        organization_id=mailbox.organization_id,
        mailbox_id=mailbox.id,
    )

    occs = (
        db_session.execute(
            select(MessageOccurrence).where(
                MessageOccurrence.organization_id == mailbox.organization_id,
                MessageOccurrence.mailbox_id == mailbox.id,
            )
        )
        .scalars()
        .all()
    )
    assert sorted(o.gmail_message_id for o in occs) == ["m-1", "m-2"]

    fetch_jobs = (
        db_session.execute(
            select(BgJob).where(
                BgJob.organization_id == mailbox.organization_id,
                BgJob.mailbox_id == mailbox.id,
                BgJob.type == JobType.occurrence_fetch_raw,
            )
        )
        .scalars()
        .all()
    )
    assert len(fetch_jobs) == 2
    for job in fetch_jobs:
        assert job.status == JobStatus.queued
        assert "occurrence_id" in job.payload
        assert "raw_eml_base64" in job.payload

    db_session.refresh(mailbox)
    assert mailbox.last_full_sync_at is not None
    assert mailbox.gmail_history_id == 250
    assert mailbox.last_sync_error is None

    http_client.close()


def test_incremental_history_invalid_enqueues_backfill_recovery(db_session: Session) -> None:
    mailbox = _seed_mailbox(
        db_session,
        email="journal-history@example.com",
        history_id=9001,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("Authorization") == "Bearer access-token-seeded"
        path = request.url.path
        params = dict(request.url.params)
        if path == "/gmail/v1/users/me/history":
            assert params.get("startHistoryId") == "9001"
            return httpx.Response(
                404,
                json={
                    "error": {
                        "code": 404,
                        "message": "History not found",
                        "status": "NOT_FOUND",
                    }
                },
            )
        return httpx.Response(404, json={"error": "not_found"})

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, timeout=10.0)

    sync_mailbox_history(
        session=db_session,
        http_client=http_client,
        organization_id=mailbox.organization_id,
        mailbox_id=mailbox.id,
    )
    sync_mailbox_history(
        session=db_session,
        http_client=http_client,
        organization_id=mailbox.organization_id,
        mailbox_id=mailbox.id,
    )

    backfill_jobs = (
        db_session.execute(
            select(BgJob).where(
                BgJob.organization_id == mailbox.organization_id,
                BgJob.mailbox_id == mailbox.id,
                BgJob.type == JobType.mailbox_backfill,
            )
        )
        .scalars()
        .all()
    )
    assert len(backfill_jobs) == 1
    assert backfill_jobs[0].status == JobStatus.queued
    assert backfill_jobs[0].dedupe_key == f"mailbox_backfill:{mailbox.id}"

    db_session.refresh(mailbox)
    assert mailbox.last_sync_error is not None
    assert "history" in mailbox.last_sync_error.lower()

    http_client.close()


def test_manual_history_sync_enqueue_endpoint(db_session: Session) -> None:
    app = create_app()
    client = TestClient(app)

    login = _dev_login(
        client,
        email="sync-admin-manual@gmail.test",
        organization_name="Org Manual History Sync",
    )
    csrf = login["csrf_token"]

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://oauth2.googleapis.com/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "access-token-manual",
                    "expires_in": 3600,
                    "refresh_token": "refresh-token-manual",
                    "scope": "https://www.googleapis.com/auth/gmail.readonly",
                    "token_type": "Bearer",
                },
            )
        if str(request.url) == "https://gmail.googleapis.com/gmail/v1/users/me/profile":
            return httpx.Response(
                200,
                json={"emailAddress": "journal-manual@example.com", "historyId": "777"},
            )
        return httpx.Response(404, json={"error": "not_found"})

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, timeout=10.0)

    from app.core.http import get_http_client

    def override_http_client() -> Generator[httpx.Client, None, None]:
        yield http_client

    app.dependency_overrides[get_http_client] = override_http_client

    start = client.post("/mailboxes/gmail/journal/oauth/start", headers={"x-csrf-token": csrf})
    state = parse_qs(urlsplit(start.json()["authorization_url"]).query)["state"][0]
    callback = client.get(f"/mailboxes/gmail/oauth/callback?state={state}&code=test-code")
    mailbox_id = UUID(callback.json()["mailbox_id"])

    res = client.post(
        f"/mailboxes/{mailbox_id}/sync/history",
        headers={"x-csrf-token": csrf},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["job_type"] == "mailbox_history_sync"

    jobs = (
        db_session.execute(
            select(BgJob).where(
                BgJob.mailbox_id == mailbox_id,
                BgJob.type == JobType.mailbox_history_sync,
            )
        )
        .scalars()
        .all()
    )
    assert len(jobs) == 1
    assert jobs[0].status == JobStatus.queued

    app.dependency_overrides.clear()
    http_client.close()
