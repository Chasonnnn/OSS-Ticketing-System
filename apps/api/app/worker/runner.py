from __future__ import annotations

import socket
import time
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.enums import JobStatus, JobType
from app.worker.errors import PermanentJobError
from app.worker.handlers import handle_job


@dataclass(frozen=True)
class WorkerConfig:
    poll_interval_seconds: float = 0.5
    worker_id: str = socket.gethostname()


def run_worker_forever(config: WorkerConfig) -> None:
    while True:
        ran = run_one_job(config=config)
        if not ran:
            time.sleep(config.poll_interval_seconds)


def run_one_job(*, config: WorkerConfig) -> bool:
    session = SessionLocal()
    try:
        job = _claim_next_job(session=session, worker_id=config.worker_id)
        if job is None:
            session.commit()
            return False

        job_id = UUID(str(job["id"]))
        job_type = JobType(job["type"])
        try:
            handle_job(session=session, job_id=job_id, job_type=job_type, payload=job["payload"])
        except PermanentJobError as e:
            _mark_failed(session=session, job_id=job_id, error=str(e), permanent=True)
        except Exception as e:
            _mark_failed(session=session, job_id=job_id, error=str(e), permanent=False)
        else:
            _mark_succeeded(session=session, job_id=job_id)

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
        RETURNING id, type, payload, attempts, max_attempts
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


def _mark_failed(*, session: Session, job_id: UUID, error: str, permanent: bool) -> None:
    row = session.execute(
        text("SELECT attempts, max_attempts FROM bg_jobs WHERE id = :id FOR UPDATE"),
        {"id": str(job_id)},
    ).mappings().fetchone()
    if row is None:
        return
    attempts = int(row["attempts"]) + 1
    max_attempts = int(row["max_attempts"])

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

