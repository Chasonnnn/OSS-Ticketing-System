from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.main import create_app
from app.models.enums import (
    BlobKind,
    MailboxProvider,
    MailboxPurpose,
    MembershipRole,
    MessageDirection,
    OccurrenceState,
    RoutingConfidence,
    RoutingRecipientSource,
    TicketPriority,
    TicketStatus,
)
from app.models.identity import Membership, Organization, Queue, User
from app.models.mail import (
    Blob,
    Mailbox,
    Message,
    MessageAttachment,
    MessageContent,
    MessageOccurrence,
    OAuthCredential,
)
from app.models.tickets import Ticket, TicketEvent, TicketMessage, TicketNote
from app.storage.factory import build_blob_store


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


def test_tickets_list_supports_cursor_filters_and_search(db_session: Session) -> None:
    app = create_app()
    client = TestClient(app)

    login = _dev_login(
        client,
        email="tickets-admin@example.com",
        organization_name="Org Tickets List",
    )
    org, user = _load_org_and_user(db_session, login_payload=login)

    queue = Queue(organization_id=org.id, name="Support", slug="support")
    db_session.add(queue)
    db_session.flush()

    base = datetime.now(UTC)
    t1 = Ticket(
        organization_id=org.id,
        ticket_code="tkt-a",
        status=TicketStatus.new,
        priority=TicketPriority.normal,
        subject="Need refund for duplicate charge",
        subject_norm="need refund for duplicate charge",
        requester_email="buyer@example.com",
        requester_name="Buyer",
        assignee_user_id=user.id,
        assignee_queue_id=queue.id,
        first_message_at=base - timedelta(days=2),
        last_message_at=base - timedelta(days=1),
        last_activity_at=base - timedelta(hours=1),
    )
    t2 = Ticket(
        organization_id=org.id,
        ticket_code="tkt-b",
        status=TicketStatus.spam,
        priority=TicketPriority.low,
        subject="Marketing blast",
        subject_norm="marketing blast",
        requester_email="spammy@example.com",
        requester_name="Spammer",
        first_message_at=base - timedelta(days=3),
        last_message_at=base - timedelta(days=3),
        last_activity_at=base - timedelta(hours=2),
    )
    t3 = Ticket(
        organization_id=org.id,
        ticket_code="tkt-c",
        status=TicketStatus.open,
        priority=TicketPriority.high,
        subject="Cannot login",
        subject_norm="cannot login",
        requester_email="customer@example.com",
        requester_name="Customer",
        first_message_at=base - timedelta(days=4),
        last_message_at=base - timedelta(days=4),
        last_activity_at=base - timedelta(hours=3),
    )
    db_session.add_all([t1, t2, t3])
    db_session.flush()

    # Create another org ticket to prove scoping.
    other_org = Organization(name="Other Org")
    db_session.add(other_org)
    db_session.flush()
    db_session.add(
        Ticket(
            organization_id=other_org.id,
            ticket_code="tkt-other",
            status=TicketStatus.new,
            priority=TicketPriority.normal,
            subject="Should be invisible",
            requester_email="other@example.com",
            last_activity_at=base,
        )
    )
    db_session.commit()

    first = client.get("/tickets", params={"limit": 2})
    assert first.status_code == 200
    first_payload = first.json()
    assert [item["ticket_code"] for item in first_payload["items"]] == ["tkt-a", "tkt-b"]
    assert first_payload["next_cursor"]

    second = client.get("/tickets", params={"limit": 2, "cursor": first_payload["next_cursor"]})
    assert second.status_code == 200
    second_payload = second.json()
    assert [item["ticket_code"] for item in second_payload["items"]] == ["tkt-c"]
    assert second_payload["next_cursor"] is None

    spam_only = client.get("/tickets", params={"status": "spam"})
    assert spam_only.status_code == 200
    assert [item["ticket_code"] for item in spam_only.json()["items"]] == ["tkt-b"]

    assigned_to_user = client.get("/tickets", params={"assignee_user_id": str(user.id)})
    assert assigned_to_user.status_code == 200
    assert [item["ticket_code"] for item in assigned_to_user.json()["items"]] == ["tkt-a"]

    search_refund = client.get("/tickets", params={"q": "refund"})
    assert search_refund.status_code == 200
    assert [item["ticket_code"] for item in search_refund.json()["items"]] == ["tkt-a"]

    invalid_cursor = client.get("/tickets", params={"cursor": "not-valid"})
    assert invalid_cursor.status_code == 422
    assert "Invalid cursor" in invalid_cursor.json()["detail"]


def test_ticket_detail_returns_thread_events_notes_and_is_org_scoped(db_session: Session) -> None:
    app = create_app()
    client_one = TestClient(app)
    client_two = TestClient(app)

    login_one = _dev_login(
        client_one,
        email="agent-one@example.com",
        organization_name="Org Ticket Detail One",
    )
    _dev_login(
        client_two,
        email="agent-two@example.com",
        organization_name="Org Ticket Detail Two",
    )

    org_one, user_one = _load_org_and_user(db_session, login_payload=login_one)
    now = datetime.now(UTC)

    ticket = Ticket(
        organization_id=org_one.id,
        ticket_code="tkt-detail",
        status=TicketStatus.open,
        priority=TicketPriority.urgent,
        subject="Cannot access account",
        subject_norm="cannot access account",
        requester_email="requester@example.com",
        requester_name="Requester",
        first_message_at=now - timedelta(hours=6),
        last_message_at=now - timedelta(hours=1),
        last_activity_at=now - timedelta(hours=1),
    )
    db_session.add(ticket)
    db_session.flush()

    message = Message(
        organization_id=org_one.id,
        direction=MessageDirection.inbound,
        rfc_message_id="<detail@acme.test>",
        fingerprint_v1=b"f" * 32,
        signature_v1=b"s" * 32,
    )
    db_session.add(message)
    db_session.flush()

    db_session.add(
        MessageContent(
            organization_id=org_one.id,
            message_id=message.id,
            content_version=1,
            parser_version=1,
            date_header=now - timedelta(hours=2),
            subject="Cannot access account",
            subject_norm="cannot access account",
            from_email="requester@example.com",
            from_name="Requester",
            reply_to_emails=["requester@example.com"],
            to_emails=["support@example.com"],
            cc_emails=[],
            headers_json={"Message-ID": ["<detail@acme.test>"]},
            body_text="My account is locked",
            body_html_sanitized="<p>My account is locked</p>",
            has_attachments=True,
            attachment_count=1,
            snippet="My account is locked",
        )
    )
    db_session.flush()

    blob = Blob(
        organization_id=org_one.id,
        kind=BlobKind.attachment,
        sha256=b"b" * 32,
        size_bytes=1234,
        storage_key=f"{org_one.id}/attachments/test.png",
        content_type="image/png",
    )
    db_session.add(blob)
    db_session.flush()

    db_session.add(
        MessageAttachment(
            organization_id=org_one.id,
            message_id=message.id,
            blob_id=blob.id,
            filename="screenshot.png",
            content_type="image/png",
            size_bytes=1234,
            sha256=b"a" * 32,
            is_inline=False,
            content_id=None,
        )
    )
    db_session.add(
        TicketMessage(
            organization_id=org_one.id,
            ticket_id=ticket.id,
            message_id=message.id,
            stitch_reason="new_ticket",
            stitch_confidence=RoutingConfidence.low,
        )
    )

    oauth = OAuthCredential(
        organization_id=org_one.id,
        provider="google",
        subject="journal-detail@example.com",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        encrypted_refresh_token=b"refresh-token",
        encrypted_access_token=b"access-token",
        access_token_expires_at=now + timedelta(hours=1),
    )
    db_session.add(oauth)
    db_session.flush()
    mailbox = Mailbox(
        organization_id=org_one.id,
        purpose=MailboxPurpose.journal,
        provider=MailboxProvider.gmail,
        email_address="journal-detail@example.com",
        oauth_credential_id=oauth.id,
        is_enabled=True,
    )
    db_session.add(mailbox)
    db_session.flush()
    db_session.add(
        MessageOccurrence(
            organization_id=org_one.id,
            mailbox_id=mailbox.id,
            message_id=message.id,
            ticket_id=ticket.id,
            gmail_message_id="gmail-detail-1",
            state=OccurrenceState.routed,
            original_recipient="support@example.com",
            original_recipient_source=RoutingRecipientSource.to_cc_scan,
            original_recipient_confidence=RoutingConfidence.low,
            original_recipient_evidence={
                "selected_from": "to",
                "selected_value": "support@example.com",
            },
        )
    )

    db_session.add(
        TicketEvent(
            organization_id=org_one.id,
            ticket_id=ticket.id,
            actor_user_id=user_one.id,
            event_type="status_changed",
            event_data={"from": "new", "to": "open"},
        )
    )
    db_session.add(
        TicketNote(
            organization_id=org_one.id,
            ticket_id=ticket.id,
            author_user_id=user_one.id,
            body_markdown="Investigating account lockout",
            body_html_sanitized="<p>Investigating account lockout</p>",
        )
    )
    db_session.commit()

    detail = client_one.get(f"/tickets/{ticket.id}")
    assert detail.status_code == 200
    payload = detail.json()

    assert payload["ticket"]["id"] == str(ticket.id)
    assert payload["ticket"]["ticket_code"] == "tkt-detail"
    assert payload["messages"]
    assert payload["messages"][0]["message_id"] == str(message.id)
    assert payload["messages"][0]["subject"] == "Cannot access account"
    assert payload["messages"][0]["attachments"][0]["filename"] == "screenshot.png"
    assert payload["messages"][0]["occurrences"][0]["original_recipient"] == "support@example.com"
    assert payload["messages"][0]["occurrences"][0]["original_recipient_source"] == "to_cc_scan"
    assert (
        payload["messages"][0]["occurrences"][0]["original_recipient_evidence"]["selected_from"]
        == "to"
    )
    assert payload["events"][0]["event_type"] == "status_changed"
    assert payload["notes"][0]["body_markdown"] == "Investigating account lockout"

    hidden = client_two.get(f"/tickets/{ticket.id}")
    assert hidden.status_code == 404


def test_ticket_attachment_download_is_org_scoped(
    db_session: Session,
    tmp_path,
    monkeypatch,
) -> None:
    blob_dir = tmp_path / "blobs"
    monkeypatch.setenv("BLOB_STORE", "local")
    monkeypatch.setenv("LOCAL_BLOB_DIR", str(blob_dir))
    get_settings.cache_clear()

    try:
        app = create_app()
        client_one = TestClient(app)
        client_two = TestClient(app)

        login_one = _dev_login(
            client_one,
            email="agent-attach-one@example.com",
            organization_name="Org Ticket Attach One",
        )
        _dev_login(
            client_two,
            email="agent-attach-two@example.com",
            organization_name="Org Ticket Attach Two",
        )

        org_one, _user_one = _load_org_and_user(db_session, login_payload=login_one)
        now = datetime.now(UTC)
        blob_bytes = b"attachment-bytes-123"
        storage_key = f"{org_one.id}/attachments/report.pdf"
        build_blob_store().put_bytes(
            key=storage_key,
            data=blob_bytes,
            content_type="application/pdf",
        )

        ticket = Ticket(
            organization_id=org_one.id,
            ticket_code="tkt-attachment",
            status=TicketStatus.open,
            priority=TicketPriority.normal,
            subject="Attachment access",
            requester_email="requester@example.com",
            first_message_at=now,
            last_message_at=now,
            last_activity_at=now,
        )
        db_session.add(ticket)
        db_session.flush()

        message = Message(
            organization_id=org_one.id,
            direction=MessageDirection.inbound,
            rfc_message_id="<attachment@acme.test>",
            fingerprint_v1=b"f" * 32,
            signature_v1=b"s" * 32,
        )
        db_session.add(message)
        db_session.flush()

        blob = Blob(
            organization_id=org_one.id,
            kind=BlobKind.attachment,
            sha256=b"b" * 32,
            size_bytes=len(blob_bytes),
            storage_key=storage_key,
            content_type="application/pdf",
        )
        db_session.add(blob)
        db_session.flush()

        attachment = MessageAttachment(
            organization_id=org_one.id,
            message_id=message.id,
            blob_id=blob.id,
            filename="report.pdf",
            content_type="application/pdf",
            size_bytes=len(blob_bytes),
            sha256=b"a" * 32,
            is_inline=False,
            content_id=None,
        )
        db_session.add(attachment)
        db_session.add(
            TicketMessage(
                organization_id=org_one.id,
                ticket_id=ticket.id,
                message_id=message.id,
                stitch_reason="new_ticket",
                stitch_confidence=RoutingConfidence.low,
            )
        )
        db_session.commit()

        allowed = client_one.get(
            f"/tickets/{ticket.id}/attachments/{attachment.id}/download",
        )
        assert allowed.status_code == 200
        assert allowed.content == blob_bytes
        assert allowed.headers["content-type"] == "application/pdf"
        assert "report.pdf" in allowed.headers["content-disposition"]

        denied = client_two.get(
            f"/tickets/{ticket.id}/attachments/{attachment.id}/download",
        )
        assert denied.status_code == 404
    finally:
        get_settings.cache_clear()


def test_ticket_attachment_download_redirects_to_signed_url_when_supported(
    db_session: Session,
    monkeypatch,
) -> None:
    app = create_app()
    client = TestClient(app)

    login = _dev_login(
        client,
        email="agent-attach-signed@example.com",
        organization_name="Org Ticket Attach Signed",
    )
    org, _user = _load_org_and_user(db_session, login_payload=login)
    now = datetime.now(UTC)

    ticket = Ticket(
        organization_id=org.id,
        ticket_code="tkt-attachment-signed",
        status=TicketStatus.open,
        priority=TicketPriority.normal,
        subject="Attachment signed link",
        requester_email="requester@example.com",
        first_message_at=now,
        last_message_at=now,
        last_activity_at=now,
    )
    db_session.add(ticket)
    db_session.flush()

    message = Message(
        organization_id=org.id,
        direction=MessageDirection.inbound,
        rfc_message_id="<attachment-signed@acme.test>",
        fingerprint_v1=b"f" * 32,
        signature_v1=b"s" * 32,
    )
    db_session.add(message)
    db_session.flush()

    blob = Blob(
        organization_id=org.id,
        kind=BlobKind.attachment,
        sha256=b"b" * 32,
        size_bytes=10,
        storage_key=f"{org.id}/attachments/report-signed.pdf",
        content_type="application/pdf",
    )
    db_session.add(blob)
    db_session.flush()

    attachment = MessageAttachment(
        organization_id=org.id,
        message_id=message.id,
        blob_id=blob.id,
        filename="report-signed.pdf",
        content_type="application/pdf",
        size_bytes=10,
        sha256=b"a" * 32,
        is_inline=False,
        content_id=None,
    )
    db_session.add(attachment)
    db_session.add(
        TicketMessage(
            organization_id=org.id,
            ticket_id=ticket.id,
            message_id=message.id,
            stitch_reason="new_ticket",
            stitch_confidence=RoutingConfidence.low,
        )
    )
    db_session.commit()

    class _SignedStore:
        def get_download_url(
            self,
            *,
            key: str,
            expires_in_seconds: int,
            filename: str | None,
            content_type: str | None,
        ) -> str | None:
            _ = key, expires_in_seconds, filename, content_type
            return "https://files.example.test/download/presigned-token"

        def get_bytes(self, *, key: str) -> bytes:
            raise AssertionError(f"get_bytes should not be called for signed redirects ({key})")

    monkeypatch.setattr("app.services.ticket_views.build_blob_store", lambda: _SignedStore())

    res = client.get(
        f"/tickets/{ticket.id}/attachments/{attachment.id}/download",
        follow_redirects=False,
    )
    assert res.status_code == 307
    assert res.headers["location"] == "https://files.example.test/download/presigned-token"


def test_ticket_update_and_note_create(db_session: Session) -> None:
    app = create_app()
    client = TestClient(app)

    login = _dev_login(
        client,
        email="agent-update@example.com",
        organization_name="Org Ticket Updates",
    )
    csrf = login["csrf_token"]
    org, user = _load_org_and_user(db_session, login_payload=login)

    queue = Queue(organization_id=org.id, name="Ops", slug="ops")
    ticket = Ticket(
        organization_id=org.id,
        ticket_code="tkt-update",
        status=TicketStatus.new,
        priority=TicketPriority.normal,
        subject="Update me",
        requester_email="customer@example.com",
        last_activity_at=datetime.now(UTC) - timedelta(hours=2),
    )
    db_session.add_all([queue, ticket])
    db_session.commit()

    update = client.patch(
        f"/tickets/{ticket.id}",
        json={
            "status": "pending",
            "priority": "high",
            "assignee_queue_id": str(queue.id),
        },
        headers={"x-csrf-token": csrf},
    )
    assert update.status_code == 200
    payload = update.json()
    assert payload["status"] == "pending"
    assert payload["priority"] == "high"
    assert payload["assignee_queue_id"] == str(queue.id)
    assert payload["assignee_user_id"] is None

    note = client.post(
        f"/tickets/{ticket.id}/notes",
        json={"body_markdown": "Investigating escalation path"},
        headers={"x-csrf-token": csrf},
    )
    assert note.status_code == 201
    note_payload = note.json()
    assert note_payload["body_markdown"] == "Investigating escalation path"
    assert note_payload["author_user_id"] == str(user.id)

    detail = client.get(f"/tickets/{ticket.id}")
    assert detail.status_code == 200
    detail_payload = detail.json()
    assert detail_payload["ticket"]["status"] == "pending"
    assert detail_payload["ticket"]["priority"] == "high"
    assert detail_payload["ticket"]["assignee_queue_id"] == str(queue.id)
    assert any(event["event_type"] == "ticket_updated" for event in detail_payload["events"])
    assert any(event["event_type"] == "note_added" for event in detail_payload["events"])
    assert detail_payload["notes"][-1]["body_markdown"] == "Investigating escalation path"


def test_ticket_mutation_permissions_and_assignment_validation(db_session: Session) -> None:
    app = create_app()
    client = TestClient(app)

    login = _dev_login(
        client,
        email="viewer-update@example.com",
        organization_name="Org Ticket Guardrails",
    )
    csrf = login["csrf_token"]
    org, user = _load_org_and_user(db_session, login_payload=login)

    membership = (
        db_session.execute(
            select(Membership).where(
                Membership.organization_id == org.id,
                Membership.user_id == user.id,
            )
        )
        .scalars()
        .one()
    )
    membership.role = MembershipRole.viewer
    db_session.flush()

    ticket = Ticket(
        organization_id=org.id,
        ticket_code="tkt-guard",
        status=TicketStatus.new,
        priority=TicketPriority.normal,
        subject="Guardrails",
        requester_email="customer@example.com",
        last_activity_at=datetime.now(UTC),
    )
    db_session.add(ticket)
    db_session.commit()

    forbidden = client.patch(
        f"/tickets/{ticket.id}",
        json={"status": "open"},
        headers={"x-csrf-token": csrf},
    )
    assert forbidden.status_code == 403

    # Elevate back to admin and verify validation.
    membership.role = MembershipRole.admin
    db_session.commit()

    invalid_assignee = client.patch(
        f"/tickets/{ticket.id}",
        json={
            "assignee_user_id": str(user.id),
            "assignee_queue_id": str(uuid4()),
        },
        headers={"x-csrf-token": csrf},
    )
    assert invalid_assignee.status_code == 422
    assert "Provide only one" in invalid_assignee.json()["detail"]
