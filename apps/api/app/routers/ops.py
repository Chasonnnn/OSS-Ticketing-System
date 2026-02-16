from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.deps import OrgContext, require_csrf_header, require_roles
from app.db.session import get_session
from app.models.enums import MembershipRole
from app.schemas.ops import DlqJobsResponse, DlqReplayResponse

router = APIRouter(prefix="/ops/jobs", tags=["ops"], dependencies=[Depends(require_csrf_header)])


@router.get("/dlq", response_model=DlqJobsResponse)
def dlq_jobs_list(
    limit: int = Query(default=50, ge=1, le=200),
    org: OrgContext = Depends(require_roles([MembershipRole.admin])),
    session: Session = Depends(get_session),
) -> DlqJobsResponse:
    rows = (
        session.execute(
            text(
                """
            SELECT
              id,
              type,
              status,
              attempts,
              max_attempts,
              last_error,
              run_at,
              updated_at,
              payload
            FROM bg_jobs
            WHERE organization_id = :organization_id
              AND status = 'failed'
            ORDER BY updated_at DESC, id DESC
            LIMIT :limit
            """
            ),
            {"organization_id": str(org.organization.id), "limit": limit},
        )
        .mappings()
        .all()
    )
    return DlqJobsResponse(
        items=[
            {
                "id": row["id"],
                "type": row["type"],
                "status": row["status"],
                "attempts": row["attempts"],
                "max_attempts": row["max_attempts"],
                "last_error": row["last_error"],
                "run_at": row["run_at"],
                "updated_at": row["updated_at"],
                "payload": row["payload"] or {},
            }
            for row in rows
        ]
    )


@router.post("/{job_id}/replay", response_model=DlqReplayResponse)
def dlq_job_replay(
    job_id: UUID,
    org: OrgContext = Depends(require_roles([MembershipRole.admin])),
    session: Session = Depends(get_session),
) -> DlqReplayResponse:
    row = (
        session.execute(
            text(
                """
            SELECT id
            FROM bg_jobs
            WHERE id = :id
              AND organization_id = :organization_id
              AND status = 'failed'
            FOR UPDATE
            """
            ),
            {"id": str(job_id), "organization_id": str(org.organization.id)},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="DLQ job not found")

    session.execute(
        text(
            """
            UPDATE bg_jobs
            SET status = 'queued',
                run_at = now(),
                locked_at = NULL,
                locked_by = NULL,
                last_error = NULL,
                updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": str(job_id)},
    )
    session.commit()
    return DlqReplayResponse(status="queued", job_id=job_id)
