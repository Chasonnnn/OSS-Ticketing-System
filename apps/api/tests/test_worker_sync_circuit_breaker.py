from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.enums import JobStatus, JobType, MailboxProvider, MailboxPurpose
from app.models.identity import Organization
from app.models.jobs import BgJob
from app.models.mail import Mailbox, OAuthCredential
from app.worker.runner import WorkerConfig, run_one_job


def _seed_mailbox_context(db_session: Session) -> tuple[UUID, UUID]:
    # Worker claims jobs globally; isolate from unrelated queued jobs.
    db_session.execute(text("DELETE FROM bg_jobs"))
    db_session.commit()

    org = Organization(name="Org Worker Circuit")
    db_session.add(org)
    db_session.flush()

    cred = OAuthCredential(
        organization_id=org.id,
        provider="google",
        subject="circuit@example.com",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        encrypted_refresh_token=b"refresh",
        encrypted_access_token=b"access",
        access_token_expires_at=datetime.now(UTC),
    )
    db_session.add(cred)
    db_session.flush()

    mailbox = Mailbox(
        organization_id=org.id,
        purpose=MailboxPurpose.journal,
        provider=MailboxProvider.gmail,
        email_address="circuit@example.com",
        oauth_credential_id=cred.id,
        is_enabled=True,
    )
    db_session.add(mailbox)
    db_session.commit()

    return org.id, mailbox.id


def test_mailbox_history_failure_trips_circuit_breaker(db_session: Session, monkeypatch) -> None:
    org_id, mailbox_id = _seed_mailbox_context(db_session)

    job = BgJob(
        organization_id=org_id,
        mailbox_id=mailbox_id,
        type=JobType.mailbox_history_sync,
        status=JobStatus.queued,
        attempts=4,
        payload={
            "organization_id": str(org_id),
            "mailbox_id": str(mailbox_id),
            "reason": "test",
        },
        dedupe_key=f"mailbox_history_sync:{mailbox_id}",
    )
    db_session.add(job)
    db_session.commit()

    def fake_handle_job(*, session, job_id, job_type, payload):  # noqa: ANN001
        _ = session, job_id, job_type, payload
        raise RuntimeError("gmail sync failed")

    monkeypatch.setattr("app.worker.runner.handle_job", fake_handle_job)

    ran = run_one_job(config=WorkerConfig(worker_id=f"w-{uuid4()}"))
    assert ran is True

    db_session.expire_all()
    refreshed_job = db_session.get(BgJob, job.id)
    assert refreshed_job is not None
    assert refreshed_job.status == JobStatus.failed
    assert refreshed_job.attempts == 5

    mailbox = db_session.get(Mailbox, mailbox_id)
    assert mailbox is not None
    assert mailbox.ingestion_paused_until is not None
    assert mailbox.ingestion_paused_until > datetime.now(UTC)
    assert mailbox.ingestion_pause_reason is not None
    assert "circuit breaker" in mailbox.ingestion_pause_reason.lower()
    assert mailbox.last_sync_error is not None


def test_non_mailbox_failure_keeps_retry_backoff(db_session: Session, monkeypatch) -> None:
    org_id, mailbox_id = _seed_mailbox_context(db_session)

    job = BgJob(
        organization_id=org_id,
        mailbox_id=mailbox_id,
        type=JobType.occurrence_parse,
        status=JobStatus.queued,
        payload={"occurrence_id": str(uuid4())},
        dedupe_key=f"occurrence_parse:{uuid4()}",
    )
    db_session.add(job)
    db_session.commit()

    def fake_handle_job(*, session, job_id, job_type, payload):  # noqa: ANN001
        _ = session, job_id, job_type, payload
        raise RuntimeError("parse failed")

    monkeypatch.setattr("app.worker.runner.handle_job", fake_handle_job)

    ran = run_one_job(config=WorkerConfig(worker_id=f"w-{uuid4()}"))
    assert ran is True

    db_session.expire_all()
    refreshed_job = db_session.get(BgJob, job.id)
    assert refreshed_job is not None
    assert refreshed_job.status == JobStatus.queued
    assert refreshed_job.attempts == 1
    assert refreshed_job.run_at > datetime.now(UTC)

    mailbox = db_session.get(Mailbox, mailbox_id)
    assert mailbox is not None
    assert mailbox.ingestion_paused_until is None
