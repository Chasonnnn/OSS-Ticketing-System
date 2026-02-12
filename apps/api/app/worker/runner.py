from __future__ import annotations

import socket
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_sessionmaker
from app.models.enums import JobStatus, JobType
from app.worker.errors import PermanentJobError
from app.worker.handlers import handle_job
from app.worker.queue import enqueue_job


@dataclass(frozen=True)
class WorkerConfig:
    poll_interval_seconds: float = 0.5
    history_poll_interval_seconds: float = 30.0
    mailbox_sync_circuit_breaker_attempts: int = 5
    mailbox_sync_pause_seconds: float = 900.0
    worker_id: str = socket.gethostname()


def run_worker_forever(config: WorkerConfig) -> None:
    while True:
        ran = run_one_job(config=config)
        if not ran:
            time.sleep(config.poll_interval_seconds)


def run_one_job(*, config: WorkerConfig) -> bool:
    session = get_sessionmaker()()
    try:
        job = _claim_next_job(session=session, worker_id=config.worker_id)
        if job is None:
            session.commit()
            return False

        job_id = UUID(str(job["id"]))
        mailbox_id = UUID(str(job["mailbox_id"])) if job.get("mailbox_id") is not None else None
        job_type = JobType(job["type"])
        try:
            handle_job(session=session, job_id=job_id, job_type=job_type, payload=job["payload"])
        except PermanentJobError as e:
            _mark_failed(
                session=session,
                config=config,
                job_id=job_id,
                job_type=job_type,
                mailbox_id=mailbox_id,
                error=str(e),
                permanent=True,
            )
        except Exception as e:
            _mark_failed(
                session=session,
                config=config,
                job_id=job_id,
                job_type=job_type,
                mailbox_id=mailbox_id,
                error=str(e),
                permanent=False,
            )
        else:
            _mark_succeeded(session=session, job_id=job_id)
            _schedule_follow_up_jobs(
                session=session,
                config=config,
                job_type=job_type,
                job=job,
            )

        session.commit()
        return True
    finally:
        session.close()


def _claim_next_job(*, session: Session, worker_id: str) -> dict | None:
    sql = text(
        """
        WITH next_job AS (
          SELECT id
          FROM bg_jobs
          WHERE status = 'queued'
            AND run_at <= now()
          ORDER BY run_at ASC
          FOR UPDATE SKIP LOCKED
          LIMIT 1
        )
        UPDATE bg_jobs
        SET status = 'running',
            locked_at = now(),
            locked_by = :worker_id,
            updated_at = now()
        WHERE id IN (SELECT id FROM next_job)
        RETURNING id, organization_id, mailbox_id, type, payload, attempts, max_attempts
        """
    )
    row = session.execute(sql, {"worker_id": worker_id}).mappings().fetchone()
    if row is None:
        return None
    return dict(row)


def _mark_succeeded(*, session: Session, job_id: UUID) -> None:
    session.execute(
        text(
            """
            UPDATE bg_jobs
            SET status = :status,
                updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": str(job_id), "status": JobStatus.succeeded.value},
    )


def _mark_failed(
    *,
    session: Session,
    config: WorkerConfig,
    job_id: UUID,
    job_type: JobType,
    mailbox_id: UUID | None,
    error: str,
    permanent: bool,
) -> None:
    row = (
        session.execute(
            text("SELECT attempts, max_attempts FROM bg_jobs WHERE id = :id FOR UPDATE"),
            {"id": str(job_id)},
        )
        .mappings()
        .fetchone()
    )
    if row is None:
        return
    attempts = int(row["attempts"]) + 1
    max_attempts = int(row["max_attempts"])

    if (
        not permanent
        and mailbox_id is not None
        and job_type in {JobType.mailbox_backfill, JobType.mailbox_history_sync}
        and attempts >= max(1, config.mailbox_sync_circuit_breaker_attempts)
    ):
        _pause_mailbox_ingestion(
            session=session,
            config=config,
            mailbox_id=mailbox_id,
            job_type=job_type,
            attempts=attempts,
            error=error,
        )
        session.execute(
            text(
                """
                UPDATE bg_jobs
                SET status = :status,
                    attempts = :attempts,
                    last_error = :error,
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {
                "id": str(job_id),
                "status": JobStatus.failed.value,
                "attempts": attempts,
                "error": error,
            },
        )
        return

    if permanent or attempts >= max_attempts:
        session.execute(
            text(
                """
                UPDATE bg_jobs
                SET status = :status,
                    attempts = :attempts,
                    last_error = :error,
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {
                "id": str(job_id),
                "status": JobStatus.failed.value,
                "attempts": attempts,
                "error": error,
            },
        )
        return

    backoff_seconds = min(60.0, 0.5 * (2 ** min(attempts, 8)))
    session.execute(
        text(
            """
            UPDATE bg_jobs
            SET status = :status,
                attempts = :attempts,
                last_error = :error,
                run_at = now() + (:backoff_seconds || ' seconds')::interval,
                updated_at = now()
            WHERE id = :id
            """
        ),
        {
            "id": str(job_id),
            "status": JobStatus.queued.value,
            "attempts": attempts,
            "error": error,
            "backoff_seconds": backoff_seconds,
        },
    )


def _pause_mailbox_ingestion(
    *,
    session: Session,
    config: WorkerConfig,
    mailbox_id: UUID,
    job_type: JobType,
    attempts: int,
    error: str,
) -> None:
    pause_until = datetime.now(UTC) + timedelta(seconds=max(1.0, config.mailbox_sync_pause_seconds))
    reason = (
        f"Auto-paused by sync circuit breaker after {attempts} failed {job_type.value} attempts"
    )
    session.execute(
        text(
            """
            UPDATE mailboxes
            SET ingestion_paused_until = :pause_until,
                ingestion_pause_reason = :reason,
                last_sync_error = :error,
                updated_at = now()
            WHERE id = :id
            """
        ),
        {
            "id": str(mailbox_id),
            "pause_until": pause_until,
            "reason": reason,
            "error": error,
        },
    )


def _schedule_follow_up_jobs(
    *,
    session: Session,
    config: WorkerConfig,
    job_type: JobType,
    job: dict,
) -> None:
    if job_type != JobType.mailbox_history_sync:
        return

    org_id_raw = job.get("organization_id")
    mailbox_id_raw = job.get("mailbox_id")
    if org_id_raw is None or mailbox_id_raw is None:
        return

    organization_id = UUID(str(org_id_raw))
    mailbox_id = UUID(str(mailbox_id_raw))

    run_at = datetime.now(UTC) + timedelta(seconds=max(1.0, config.history_poll_interval_seconds))
    enqueue_job(
        session=session,
        job_type=JobType.mailbox_history_sync,
        organization_id=organization_id,
        mailbox_id=mailbox_id,
        payload={
            "organization_id": str(organization_id),
            "mailbox_id": str(mailbox_id),
            "reason": "poll_loop",
        },
        dedupe_key=f"mailbox_history_sync:{mailbox_id}",
        run_at=run_at,
    )
