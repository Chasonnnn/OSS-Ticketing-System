from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.enums import (
    BlobKind,
    JobStatus,
    JobType,
    MailboxProvider,
    MailboxPurpose,
    OccurrenceState,
    RoutingConfidence,
    RoutingRecipientSource,
    TicketStatus,
)
from app.models.identity import Organization
from app.models.jobs import BgJob
from app.models.mail import Blob, Mailbox, MessageOccurrence, OAuthCredential
from app.models.tickets import RecipientAllowlist, Ticket, TicketEvent, TicketMessage
from app.worker.jobs.occurrence_fetch_raw import occurrence_fetch_raw
from app.worker.jobs.occurrence_parse import occurrence_parse
from app.worker.runner import WorkerConfig, run_one_job


@pytest.fixture(autouse=True)
def _local_blob_store(tmp_path, monkeypatch) -> None:
    blob_dir = tmp_path / "blobs"
    monkeypatch.setenv("BLOB_STORE", "local")
    monkeypatch.setenv("LOCAL_BLOB_DIR", str(blob_dir))
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _seed_occurrence(db_session: Session, *, suffix: str) -> tuple[UUID, UUID, UUID]:
    db_session.execute(text("DELETE FROM bg_jobs"))
    db_session.commit()

    org = Organization(name=f"Org Occurrence {suffix}")
    db_session.add(org)
    db_session.flush()

    cred = OAuthCredential(
        organization_id=org.id,
        provider="google",
        subject=f"journal-{suffix}@example.com",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        encrypted_refresh_token=b"refresh-token",
        encrypted_access_token=b"access-token",
        access_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(cred)
    db_session.flush()

    mailbox = Mailbox(
        organization_id=org.id,
        purpose=MailboxPurpose.journal,
        provider=MailboxProvider.gmail,
        email_address=f"journal-{suffix}@example.com",
        oauth_credential_id=cred.id,
        is_enabled=True,
    )
    db_session.add(mailbox)
    db_session.flush()

    occurrence = MessageOccurrence(
        organization_id=org.id,
        mailbox_id=mailbox.id,
        gmail_message_id=f"gmail-{suffix}",
        gmail_thread_id=f"thread-{suffix}",
        gmail_history_id=1,
        state=OccurrenceState.discovered,
        label_ids=["INBOX"],
    )
    db_session.add(occurrence)
    db_session.commit()
    return org.id, mailbox.id, occurrence.id


def _raw_email(*, headers: list[str], body: str = "Hello from test pipeline.") -> bytes:
    return ("\r\n".join(headers) + "\r\n\r\n" + body).encode("utf-8")


def _store_raw_for_occurrence(db_session: Session, *, occurrence_id: UUID, raw: bytes) -> None:
    occurrence_fetch_raw(
        session=db_session,
        payload={
            "occurrence_id": str(occurrence_id),
            "raw_eml_base64": base64.b64encode(raw).decode("ascii"),
        },
    )
    db_session.commit()


def _enqueue_fetch_raw_job(
    db_session: Session,
    *,
    org_id: UUID,
    mailbox_id: UUID,
    occurrence_id: UUID,
    raw: bytes,
) -> UUID:
    job = BgJob(
        organization_id=org_id,
        mailbox_id=mailbox_id,
        type=JobType.occurrence_fetch_raw,
        status=JobStatus.queued,
        dedupe_key=f"occurrence_fetch_raw:{occurrence_id}",
        payload={
            "occurrence_id": str(occurrence_id),
            "raw_eml_base64": base64.b64encode(raw).decode("ascii"),
        },
    )
    db_session.add(job)
    db_session.commit()
    return job.id


def _run_worker_until_idle(*, max_jobs: int = 25) -> None:
    for _ in range(max_jobs):
        ran = run_one_job(config=WorkerConfig(worker_id=f"worker-{uuid4()}"))
        if not ran:
            return
    raise AssertionError("Worker did not go idle in expected number of jobs")


def test_occurrence_parse_enqueues_stitch_job_once(db_session: Session) -> None:
    org_id, mailbox_id, occurrence_id = _seed_occurrence(db_session, suffix="parse-enqueue")
    raw = _raw_email(
        headers=[
            "From: Alice <alice@example.com>",
            "To: queue@acme.test",
            "Subject: Pipeline test",
            "Date: Tue, 11 Feb 2026 10:00:00 +0000",
            "Message-ID: <parse-enqueue@acme.test>",
        ]
    )
    _store_raw_for_occurrence(db_session, occurrence_id=occurrence_id, raw=raw)

    occurrence_parse(session=db_session, payload={"occurrence_id": str(occurrence_id)})
    occurrence_parse(session=db_session, payload={"occurrence_id": str(occurrence_id)})
    db_session.commit()

    stitch_jobs = (
        db_session.execute(
            select(BgJob).where(
                BgJob.organization_id == org_id,
                BgJob.mailbox_id == mailbox_id,
                BgJob.type == JobType.occurrence_stitch,
            )
        )
        .scalars()
        .all()
    )
    assert len(stitch_jobs) == 1
    assert stitch_jobs[0].status == JobStatus.queued
    assert stitch_jobs[0].dedupe_key == f"occurrence_stitch:{occurrence_id}"


def test_occurrence_parse_persists_workspace_header_recipient_with_precedence(
    db_session: Session,
) -> None:
    _org_id, _mailbox_id, occurrence_id = _seed_occurrence(db_session, suffix="header-precedence")
    raw = _raw_email(
        headers=[
            "From: Alice <alice@example.com>",
            "To: ignored@acme.test",
            "Delivered-To: delivered@acme.test",
            "X-Original-To: x-original@acme.test",
            "X-Gm-Original-To: workspace@acme.test",
            "Subject: Header precedence",
            "Date: Tue, 11 Feb 2026 10:00:00 +0000",
            "Message-ID: <header-precedence@acme.test>",
        ]
    )
    _store_raw_for_occurrence(db_session, occurrence_id=occurrence_id, raw=raw)
    occurrence_parse(session=db_session, payload={"occurrence_id": str(occurrence_id)})
    db_session.commit()

    occurrence = db_session.get(MessageOccurrence, occurrence_id)
    assert occurrence is not None
    assert occurrence.original_recipient == "workspace@acme.test"
    assert occurrence.original_recipient_source == RoutingRecipientSource.workspace_header
    assert occurrence.original_recipient_confidence == RoutingConfidence.high
    assert occurrence.original_recipient_evidence["selected_from"] == "X-Gm-Original-To"
    assert occurrence.original_recipient_evidence["selected_value"] == "workspace@acme.test"


def test_occurrence_parse_falls_back_to_to_then_cc_recipients(db_session: Session) -> None:
    _org_id, _mailbox_id, occurrence_id = _seed_occurrence(db_session, suffix="to-cc-fallback")
    raw = _raw_email(
        headers=[
            "From: Alice <alice@example.com>",
            "Cc: queue@acme.test, other@acme.test",
            "Subject: Fallback recipient",
            "Date: Tue, 11 Feb 2026 10:00:00 +0000",
            "Message-ID: <to-cc-fallback@acme.test>",
        ]
    )
    _store_raw_for_occurrence(db_session, occurrence_id=occurrence_id, raw=raw)
    occurrence_parse(session=db_session, payload={"occurrence_id": str(occurrence_id)})
    db_session.commit()

    occurrence = db_session.get(MessageOccurrence, occurrence_id)
    assert occurrence is not None
    assert occurrence.original_recipient == "queue@acme.test"
    assert occurrence.original_recipient_source == RoutingRecipientSource.to_cc_scan
    assert occurrence.original_recipient_confidence == RoutingConfidence.low
    assert occurrence.original_recipient_evidence["selected_from"] == "cc"


def test_worker_chain_creates_ticket_and_routes_for_allowlisted_recipient(
    db_session: Session,
) -> None:
    org_id, mailbox_id, occurrence_id = _seed_occurrence(db_session, suffix="full-chain")
    db_session.add(
        RecipientAllowlist(
            organization_id=org_id,
            pattern="queue@acme.test",
            is_enabled=True,
        )
    )
    db_session.commit()

    raw = _raw_email(
        headers=[
            "From: Customer <customer@example.com>",
            "To: queue@acme.test",
            "Subject: Need help with order",
            "Date: Tue, 11 Feb 2026 10:00:00 +0000",
            "Message-ID: <full-chain@acme.test>",
        ]
    )
    _enqueue_fetch_raw_job(
        db_session,
        org_id=org_id,
        mailbox_id=mailbox_id,
        occurrence_id=occurrence_id,
        raw=raw,
    )

    _run_worker_until_idle()
    db_session.expire_all()

    occurrence = db_session.get(MessageOccurrence, occurrence_id)
    assert occurrence is not None
    assert occurrence.state == OccurrenceState.routed
    assert occurrence.ticket_id is not None
    assert occurrence.original_recipient == "queue@acme.test"
    assert occurrence.original_recipient_source == RoutingRecipientSource.to_cc_scan

    ticket = db_session.get(Ticket, occurrence.ticket_id)
    assert ticket is not None
    assert ticket.status == TicketStatus.new

    link = (
        db_session.execute(
            select(TicketMessage).where(
                TicketMessage.organization_id == org_id,
                TicketMessage.ticket_id == occurrence.ticket_id,
            )
        )
        .scalars()
        .all()
    )
    assert len(link) == 1

    raw_blobs = (
        db_session.execute(
            select(Blob).where(
                Blob.organization_id == org_id,
                Blob.kind == BlobKind.raw_eml,
            )
        )
        .scalars()
        .all()
    )
    assert len(raw_blobs) == 1


def test_worker_chain_marks_unknown_recipient_as_spam(db_session: Session) -> None:
    org_id, mailbox_id, occurrence_id = _seed_occurrence(db_session, suffix="unknown-spam")
    raw = _raw_email(
        headers=[
            "From: Customer <customer@example.com>",
            "Subject: Missing recipient evidence",
            "Date: Tue, 11 Feb 2026 10:00:00 +0000",
            "Message-ID: <unknown-spam@acme.test>",
        ]
    )
    _enqueue_fetch_raw_job(
        db_session,
        org_id=org_id,
        mailbox_id=mailbox_id,
        occurrence_id=occurrence_id,
        raw=raw,
    )

    _run_worker_until_idle()
    db_session.expire_all()

    occurrence = db_session.get(MessageOccurrence, occurrence_id)
    assert occurrence is not None
    assert occurrence.state == OccurrenceState.routed
    assert occurrence.ticket_id is not None
    assert occurrence.original_recipient is None
    assert occurrence.original_recipient_source == RoutingRecipientSource.unknown
    assert occurrence.original_recipient_confidence == RoutingConfidence.low

    ticket = db_session.get(Ticket, occurrence.ticket_id)
    assert ticket is not None
    assert ticket.status == TicketStatus.spam

    spam_events = (
        db_session.execute(
            select(TicketEvent).where(
                TicketEvent.organization_id == org_id,
                TicketEvent.ticket_id == ticket.id,
                TicketEvent.event_type == "auto_spam",
            )
        )
        .scalars()
        .all()
    )
    assert len(spam_events) == 1
