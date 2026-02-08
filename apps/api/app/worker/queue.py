from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.enums import JobType


def enqueue_job(
    *,
    session: Session,
    job_type: JobType,
    organization_id: UUID | None,
    mailbox_id: UUID | None,
    payload: dict,
    dedupe_key: str | None,
    run_at: datetime | None = None,
) -> UUID | None:
    sql = text(
        """
        INSERT INTO bg_jobs (
          organization_id,
          mailbox_id,
          type,
          status,
          run_at,
          attempts,
          max_attempts,
          dedupe_key,
          payload,
          created_at,
          updated_at
        )
        VALUES (
          :organization_id,
          :mailbox_id,
          :type,
          'queued',
          COALESCE(:run_at, now()),
          0,
          25,
          :dedupe_key,
          CAST(:payload AS jsonb),
          now(),
          now()
        )
        ON CONFLICT DO NOTHING
        RETURNING id
        """
    )
    res = session.execute(
        sql,
        {
            "organization_id": str(organization_id) if organization_id else None,
            "mailbox_id": str(mailbox_id) if mailbox_id else None,
            "type": job_type.value,
            "run_at": run_at,
            "dedupe_key": dedupe_key,
            "payload": _json_dumps(payload),
        },
    ).fetchone()
    if res is None:
        return None
    return UUID(str(res[0]))


def _json_dumps(payload: dict) -> str:
    import json

    return json.dumps(payload, separators=(",", ":"), sort_keys=True)

