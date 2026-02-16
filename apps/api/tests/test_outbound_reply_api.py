from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.main import create_app
from app.models.enums import (
    JobStatus,
    JobType,
    MailboxProvider,
    MailboxPurpose,
    MessageDirection,
    OccurrenceState,
    RoutingConfidence,
    SendIdentityStatus,
    TicketPriority,
    TicketStatus,
)
from app.models.identity import Organization, User
from app.models.jobs import BgJob
from app.models.mail import (
    Mailbox,
    Message,
    MessageContent,
    MessageOccurrence,
    MessageOssId,
    OAuthCredential,
    SendIdentity,
)
from app.models.tickets import Ticket, TicketEvent, TicketMessage
from app.services.ticket_views import _coerce_text_array
from app.worker.jobs.occurrence_fetch_raw import occurrence_fetch_raw
from app.worker.jobs.occurrence_parse import occurrence_parse


@pytest.fixture(autouse=True)
def _local_blob_store(tmp_path, monkeypatch) -> None:
    blob_dir = tmp_path / "blobs"
    monkeypatch.setenv("BLOB_STORE", "local")
    monkeypatch.setenv("LOCAL_BLOB_DIR", str(blob_dir))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


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


def _load_org_and_user(db_session: Session, *, login_payload: dict) -> tuple[Organization, User]:
    org = db_session.get(Organization, UUID(login_payload["organization"]["id"]))
    user = db_session.get(User, UUID(login_payload["user"]["id"]))
    assert org is not None
    assert user is not None
    return org, user


def _seed_mailbox_and_send_identity(
    db_session: Session,
    *,
    org_id: UUID,
    from_email: str,
    status: SendIdentityStatus = SendIdentityStatus.verified,
) -> tuple[Mailbox, SendIdentity]:
    now = datetime.now(UTC)
    cred = OAuthCredential(
        organization_id=org_id,
        provider="google",
        subject="journal-reply@example.com",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        encrypted_refresh_token=b"refresh",
        encrypted_access_token=b"access",
        access_token_expires_at=now + timedelta(hours=1),
    )
    db_session.add(cred)
    db_session.flush()

    mailbox = Mailbox(
        organization_id=org_id,
        purpose=MailboxPurpose.journal,
        provider=MailboxProvider.gmail,
        email_address="journal-reply@example.com",
        oauth_credential_id=cred.id,
        is_enabled=True,
    )
    db_session.add(mailbox)
    db_session.flush()

    identity = SendIdentity(
        organization_id=org_id,
        mailbox_id=mailbox.id,
        from_email=from_email,
        from_name="Support Team",
        gmail_send_as_id=from_email,
        status=status,
        is_enabled=True,
    )
    db_session.add(identity)
    db_session.flush()
    return mailbox, identity


def _seed_ticket(db_session: Session, *, org_id: UUID) -> Ticket:
    now = datetime.now(UTC)
    ticket = Ticket(
        organization_id=org_id,
        ticket_code="tkt-reply",
        status=TicketStatus.open,
        priority=TicketPriority.normal,
        subject="Need help with refund",
        subject_norm="need help with refund",
        requester_email="customer@example.com",
        requester_name="Customer",
        first_message_at=now - timedelta(hours=2),
        last_message_at=now - timedelta(hours=1),
        last_activity_at=now - timedelta(hours=1),
    )
    db_session.add(ticket)
    db_session.flush()
    return ticket


def test_ticket_reply_queues_outbound_send_and_persists_canonical_message(
    db_session: Session,
) -> None:
    app = create_app()
    client = TestClient(app)

    login = _dev_login(
        client,
        email="reply-admin@example.com",
        organization_name="Org Outbound Reply",
    )
    csrf = login["csrf_token"]
    org, _user = _load_org_and_user(db_session, login_payload=login)

    _mailbox, identity = _seed_mailbox_and_send_identity(
        db_session,
        org_id=org.id,
        from_email="support@example.com",
    )
    ticket = _seed_ticket(db_session, org_id=org.id)
    db_session.commit()

    res = client.post(
        f"/tickets/{ticket.id}/reply",
        json={
            "send_identity_id": str(identity.id),
            "to_emails": ["customer@example.com"],
            "subject": "Re: Need help with refund",
            "body_text": "Thanks for reaching out. We are on it.",
        },
        headers={"x-csrf-token": csrf},
    )
    assert res.status_code == 202
    payload = res.json()
    assert payload["status"] == "queued"
    assert payload["job_id"]
    assert payload["message_id"]
    assert payload["oss_message_id"]

    message_id = UUID(payload["message_id"])
    oss_message_id = UUID(payload["oss_message_id"])

    msg = db_session.get(Message, message_id)
    assert msg is not None
    assert msg.organization_id == org.id
    assert msg.direction == MessageDirection.outbound
    assert msg.oss_message_id == oss_message_id

    mapping = (
        db_session.execute(
            select(MessageOssId).where(
                MessageOssId.organization_id == org.id,
                MessageOssId.oss_message_id == oss_message_id,
            )
        )
        .scalars()
        .first()
    )
    assert mapping is not None
    assert mapping.message_id == message_id

    content = (
        db_session.execute(
            select(MessageContent).where(
                MessageContent.organization_id == org.id,
                MessageContent.message_id == message_id,
            )
        )
        .scalars()
        .first()
    )
    assert content is not None
    assert content.subject == "Re: Need help with refund"
    assert content.from_email == "support@example.com"
    to_emails = _coerce_text_array(content.to_emails)
    assert "customer@example.com" in to_emails
    assert content.body_text == "Thanks for reaching out. We are on it."

    link = (
        db_session.execute(
            select(TicketMessage).where(
                TicketMessage.organization_id == org.id,
                TicketMessage.ticket_id == ticket.id,
                TicketMessage.message_id == message_id,
            )
        )
        .scalars()
        .first()
    )
    assert link is not None
    assert link.stitch_reason == "outbound_send"
    assert link.stitch_confidence == RoutingConfidence.high

    job = (
        db_session.execute(
            select(BgJob).where(
                BgJob.organization_id == org.id,
                BgJob.type == JobType.outbound_send,
                BgJob.id == UUID(payload["job_id"]),
            )
        )
        .scalars()
        .first()
    )
    assert job is not None
    assert job.status == JobStatus.queued
    assert job.dedupe_key == f"outbound_send:{message_id}"

    queued_evt = (
        db_session.execute(
            select(TicketEvent).where(
                TicketEvent.organization_id == org.id,
                TicketEvent.ticket_id == ticket.id,
                TicketEvent.event_type == "outbound_queued",
            )
        )
        .scalars()
        .first()
    )
    assert queued_evt is not None


def test_ticket_reply_rejects_non_verified_send_identity(db_session: Session) -> None:
    app = create_app()
    client = TestClient(app)

    login = _dev_login(
        client,
        email="reply-admin-2@example.com",
        organization_name="Org Outbound Reply 2",
    )
    csrf = login["csrf_token"]
    org, _user = _load_org_and_user(db_session, login_payload=login)

    _mailbox, identity = _seed_mailbox_and_send_identity(
        db_session,
        org_id=org.id,
        from_email="support@example.com",
        status=SendIdentityStatus.pending,
    )
    ticket = _seed_ticket(db_session, org_id=org.id)
    db_session.commit()

    res = client.post(
        f"/tickets/{ticket.id}/reply",
        json={
            "send_identity_id": str(identity.id),
            "to_emails": ["customer@example.com"],
            "subject": "Re: Need help with refund",
            "body_text": "This should fail.",
        },
        headers={"x-csrf-token": csrf},
    )
    assert res.status_code == 422
    assert "verified" in res.json()["detail"].lower()


def test_journal_mirror_dedupes_to_occurrence_only_via_x_oss_message_id(
    db_session: Session,
) -> None:
    app = create_app()
    client = TestClient(app)

    login = _dev_login(
        client,
        email="reply-admin-3@example.com",
        organization_name="Org Outbound Reply 3",
    )
    csrf = login["csrf_token"]
    org, _user = _load_org_and_user(db_session, login_payload=login)

    mailbox, identity = _seed_mailbox_and_send_identity(
        db_session,
        org_id=org.id,
        from_email="support@example.com",
    )
    ticket = _seed_ticket(db_session, org_id=org.id)
    db_session.commit()

    reply = client.post(
        f"/tickets/{ticket.id}/reply",
        json={
            "send_identity_id": str(identity.id),
            "to_emails": ["customer@example.com"],
            "subject": "Re: Need help with refund",
            "body_text": "Outbound canonical body.",
        },
        headers={"x-csrf-token": csrf},
    )
    assert reply.status_code == 202
    payload = reply.json()
    outbound_message_id = UUID(payload["message_id"])
    oss_message_id = payload["oss_message_id"]

    occurrence = MessageOccurrence(
        organization_id=org.id,
        mailbox_id=mailbox.id,
        gmail_message_id="gmail-outbound-mirror-1",
        gmail_thread_id="thread-1",
        gmail_history_id=1,
        state=OccurrenceState.discovered,
        label_ids=["SENT"],
    )
    db_session.add(occurrence)
    db_session.commit()

    raw = (
        "From: Support <support@example.com>\r\n"
        "To: customer@example.com\r\n"
        "Subject: Re: Need help with refund\r\n"
        "Date: Tue, 11 Feb 2026 10:00:00 +0000\r\n"
        "Message-ID: <mirror-1@example.com>\r\n"
        f"X-OSS-Message-ID: {oss_message_id}\r\n"
        "\r\n"
        "Outbound canonical body.\r\n"
    ).encode()
    occurrence_fetch_raw(
        session=db_session,
        payload={
            "occurrence_id": str(occurrence.id),
            "raw_eml_base64": base64.b64encode(raw).decode("ascii"),
        },
    )
    occurrence_parse(session=db_session, payload={"occurrence_id": str(occurrence.id)})
    db_session.commit()

    db_session.refresh(occurrence)
    assert occurrence.message_id == outbound_message_id

    messages = (
        db_session.execute(select(Message).where(Message.organization_id == org.id)).scalars().all()
    )
    assert len(messages) == 1
