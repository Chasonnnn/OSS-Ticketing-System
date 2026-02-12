from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from app.models.enums import JobType
from app.worker.jobs.mailbox_backfill import mailbox_backfill
from app.worker.jobs.mailbox_history_sync import mailbox_history_sync
from app.worker.jobs.occurrence_fetch_raw import occurrence_fetch_raw
from app.worker.jobs.occurrence_parse import occurrence_parse
from app.worker.jobs.occurrence_stitch import occurrence_stitch
from app.worker.jobs.ticket_apply_routing import ticket_apply_routing


def handle_job(*, session: Session, job_id: UUID, job_type: JobType, payload: dict) -> None:
    _ = job_id
    if job_type == JobType.mailbox_backfill:
        mailbox_backfill(session=session, payload=payload)
        return
    if job_type == JobType.mailbox_history_sync:
        mailbox_history_sync(session=session, payload=payload)
        return
    if job_type == JobType.occurrence_fetch_raw:
        occurrence_fetch_raw(session=session, payload=payload)
        return
    if job_type == JobType.occurrence_parse:
        occurrence_parse(session=session, payload=payload)
        return
    if job_type == JobType.occurrence_stitch:
        occurrence_stitch(session=session, payload=payload)
        return
    if job_type == JobType.ticket_apply_routing:
        ticket_apply_routing(session=session, payload=payload)
        return

    raise NotImplementedError(f"Job type not implemented: {job_type.value}")
