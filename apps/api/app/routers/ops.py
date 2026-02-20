from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.deps import OrgContext, require_csrf_header, require_roles
from app.db.session import get_session
from app.models.enums import MembershipRole
from app.schemas.ops import (
    DlqJobsResponse,
    DlqReplayResponse,
    OpsCollisionGroupItem,
    OpsCollisionGroupsResponse,
    OpsMailboxSyncItem,
    OpsMailboxSyncResponse,
    OpsMetricsOverviewResponse,
)
from app.services.ops_dashboard import (
    get_metrics_overview,
    list_collision_groups,
    list_mailboxes_sync,
)

router = APIRouter(prefix="/ops", tags=["ops"], dependencies=[Depends(require_csrf_header)])


@router.get("/jobs/dlq", response_model=DlqJobsResponse)
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


@router.post("/jobs/{job_id}/replay", response_model=DlqReplayResponse)
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


@router.get("/mailboxes/sync", response_model=OpsMailboxSyncResponse)
def ops_mailboxes_sync(
    org: OrgContext = Depends(require_roles([MembershipRole.admin])),
    session: Session = Depends(get_session),
) -> OpsMailboxSyncResponse:
    rows = list_mailboxes_sync(session=session, organization_id=org.organization.id)
    return OpsMailboxSyncResponse(
        items=[
            OpsMailboxSyncItem(
                mailbox_id=row.mailbox_id,
                email_address=row.email_address,
                provider=row.provider,
                purpose=row.purpose,
                is_enabled=row.is_enabled,
                paused_until=row.paused_until,
                pause_reason=row.pause_reason,
                gmail_history_id=row.gmail_history_id,
                last_full_sync_at=row.last_full_sync_at,
                last_incremental_sync_at=row.last_incremental_sync_at,
                last_sync_error=row.last_sync_error,
                sync_lag_seconds=row.sync_lag_seconds,
                queued_jobs_by_type=row.queued_jobs_by_type,
                running_jobs_by_type=row.running_jobs_by_type,
                failed_jobs_last_24h=row.failed_jobs_last_24h,
            )
            for row in rows
        ]
    )


@router.get("/messages/collisions", response_model=OpsCollisionGroupsResponse)
def ops_collision_groups(
    limit: int = Query(default=50, ge=1, le=200),
    org: OrgContext = Depends(require_roles([MembershipRole.admin])),
    session: Session = Depends(get_session),
) -> OpsCollisionGroupsResponse:
    rows = list_collision_groups(
        session=session,
        organization_id=org.organization.id,
        limit=limit,
    )
    return OpsCollisionGroupsResponse(
        items=[
            OpsCollisionGroupItem(
                collision_group_id=row.collision_group_id,
                message_count=row.message_count,
                first_seen_at=row.first_seen_at,
                last_seen_at=row.last_seen_at,
                sample_message_ids=row.sample_message_ids,
            )
            for row in rows
        ]
    )


@router.get("/metrics/overview", response_model=OpsMetricsOverviewResponse)
def ops_metrics_overview(
    org: OrgContext = Depends(require_roles([MembershipRole.admin])),
    session: Session = Depends(get_session),
) -> OpsMetricsOverviewResponse:
    metrics = get_metrics_overview(session=session, organization_id=org.organization.id)
    return OpsMetricsOverviewResponse(
        queued_jobs=metrics.queued_jobs,
        running_jobs=metrics.running_jobs,
        failed_jobs_24h=metrics.failed_jobs_24h,
        mailbox_count=metrics.mailbox_count,
        paused_mailbox_count=metrics.paused_mailbox_count,
        avg_sync_lag_seconds=metrics.avg_sync_lag_seconds,
    )
