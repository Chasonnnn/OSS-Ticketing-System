from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.enums import JobStatus, JobType, MailboxProvider, MailboxPurpose
from app.models.identity import Organization
from app.models.jobs import BgJob
from app.models.mail import Mailbox, OAuthCredential
from app.worker.runner import WorkerConfig, run_one_job


def _seed_org_and_mailbox(db_session: Session) -> tuple[UUID, UUID]:
    # Worker runner claims globally from bg_jobs; isolate these tests from other queued jobs.
    db_session.execute(text("DELETE FROM bg_jobs"))
    db_session.commit()

    org = Organization(name="Org Worker Polling")
    db_session.add(org)
    db_session.flush()

    cred = OAuthCredential(
        organization_id=org.id,
        provider="google",
        subject="polling@example.com",
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
        email_address="polling@example.com",
        oauth_credential_id=cred.id,
        is_enabled=True,
    )
    db_session.add(mailbox)
    db_session.commit()

    return org.id, mailbox.id


def test_history_sync_success_schedules_next_poll(db_session: Session, monkeypatch) -> None:
    org_id, mailbox_id = _seed_org_and_mailbox(db_session)

    job = BgJob(
        organization_id=org_id,
        mailbox_id=mailbox_id,
        type=JobType.mailbox_history_sync,
        status=JobStatus.queued,
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
        _ = session, job_id, payload
        assert job_type == JobType.mailbox_history_sync

    monkeypatch.setattr("app.worker.runner.handle_job", fake_handle_job)

    ran = run_one_job(config=WorkerConfig(worker_id=f"w-{uuid4()}"))
    assert ran is True

    db_session.expire_all()
    jobs = (
        db_session.execute(
            select(BgJob).where(BgJob.organization_id == org_id).order_by(BgJob.created_at.asc())
        )
        .scalars()
        .all()
    )
    assert len(jobs) == 2
    assert jobs[0].status == JobStatus.succeeded
    assert jobs[1].type == JobType.mailbox_history_sync
    assert jobs[1].status == JobStatus.queued
    assert jobs[1].dedupe_key == f"mailbox_history_sync:{mailbox_id}"
    assert jobs[1].run_at > datetime.now(UTC)


def test_non_history_job_does_not_schedule_followup(db_session: Session, monkeypatch) -> None:
    org_id, mailbox_id = _seed_org_and_mailbox(db_session)

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
        _ = session, job_id, payload
        assert job_type == JobType.occurrence_parse

    monkeypatch.setattr("app.worker.runner.handle_job", fake_handle_job)

    ran = run_one_job(config=WorkerConfig(worker_id=f"w-{uuid4()}"))
    assert ran is True

    db_session.expire_all()
    jobs = (
        db_session.execute(
            select(BgJob).where(BgJob.organization_id == org_id).order_by(BgJob.created_at.asc())
        )
        .scalars()
        .all()
    )
    assert len(jobs) == 1
    assert jobs[0].status == JobStatus.succeeded
