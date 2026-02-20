from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.mail import Mailbox


@dataclass(frozen=True)
class OpsMailboxSyncView:
    mailbox_id: UUID
    email_address: str
    provider: str
    purpose: str
    is_enabled: bool
    paused_until: datetime | None
    pause_reason: str | None
    gmail_history_id: int | None
    last_full_sync_at: datetime | None
    last_incremental_sync_at: datetime | None
    last_sync_error: str | None
    sync_lag_seconds: int | None
    queued_jobs_by_type: dict[str, int]
    running_jobs_by_type: dict[str, int]
    failed_jobs_last_24h: int


@dataclass(frozen=True)
class OpsCollisionGroupView:
    collision_group_id: UUID
    message_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    sample_message_ids: list[UUID]


@dataclass(frozen=True)
class OpsMetricsOverviewView:
    queued_jobs: int
    running_jobs: int
    failed_jobs_24h: int
    mailbox_count: int
    paused_mailbox_count: int
    avg_sync_lag_seconds: int | None


def list_mailboxes_sync(
    *,
    session: Session,
    organization_id: UUID,
) -> list[OpsMailboxSyncView]:
    mailboxes = (
        session.execute(
            select(Mailbox)
            .where(Mailbox.organization_id == organization_id)
            .order_by(Mailbox.updated_at.desc(), Mailbox.id.desc())
        )
        .scalars()
        .all()
    )
    if not mailboxes:
        return []

    running_queued_rows = (
        session.execute(
            text(
                """
                SELECT mailbox_id, type, status, COUNT(*) AS c
                FROM bg_jobs
                WHERE organization_id = :organization_id
                  AND mailbox_id IS NOT NULL
                  AND status IN ('queued', 'running')
                GROUP BY mailbox_id, type, status
                """
            ),
            {"organization_id": str(organization_id)},
        )
        .mappings()
        .all()
    )

    failed_rows = (
        session.execute(
            text(
                """
                SELECT mailbox_id, COUNT(*) AS c
                FROM bg_jobs
                WHERE organization_id = :organization_id
                  AND mailbox_id IS NOT NULL
                  AND status = 'failed'
                  AND updated_at >= now() - interval '24 hours'
                GROUP BY mailbox_id
                """
            ),
            {"organization_id": str(organization_id)},
        )
        .mappings()
        .all()
    )

    queued_by_mailbox: dict[UUID, dict[str, int]] = {}
    running_by_mailbox: dict[UUID, dict[str, int]] = {}
    for row in running_queued_rows:
        mailbox_id = UUID(str(row["mailbox_id"]))
        job_type = str(row["type"])
        count = int(row["c"])
        if row["status"] == "queued":
            queued_by_mailbox.setdefault(mailbox_id, {})[job_type] = count
        elif row["status"] == "running":
            running_by_mailbox.setdefault(mailbox_id, {})[job_type] = count

    failed_by_mailbox = {
        UUID(str(row["mailbox_id"])): int(row["c"])
        for row in failed_rows
        if row["mailbox_id"] is not None
    }

    now = datetime.now(UTC)
    out: list[OpsMailboxSyncView] = []
    for mailbox in mailboxes:
        lag_seconds: int | None = None
        if mailbox.last_incremental_sync_at is not None:
            lag_seconds = max(0, int((now - mailbox.last_incremental_sync_at).total_seconds()))

        out.append(
            OpsMailboxSyncView(
                mailbox_id=mailbox.id,
                email_address=mailbox.email_address,
                provider=mailbox.provider.value,
                purpose=mailbox.purpose.value,
                is_enabled=mailbox.is_enabled,
                paused_until=mailbox.ingestion_paused_until,
                pause_reason=mailbox.ingestion_pause_reason,
                gmail_history_id=mailbox.gmail_history_id,
                last_full_sync_at=mailbox.last_full_sync_at,
                last_incremental_sync_at=mailbox.last_incremental_sync_at,
                last_sync_error=mailbox.last_sync_error,
                sync_lag_seconds=lag_seconds,
                queued_jobs_by_type=queued_by_mailbox.get(mailbox.id, {}),
                running_jobs_by_type=running_by_mailbox.get(mailbox.id, {}),
                failed_jobs_last_24h=failed_by_mailbox.get(mailbox.id, 0),
            )
        )

    return out


def list_collision_groups(
    *,
    session: Session,
    organization_id: UUID,
    limit: int,
) -> list[OpsCollisionGroupView]:
    rows = (
        session.execute(
            text(
                """
                SELECT
                  collision_group_id,
                  COUNT(*) AS message_count,
                  MIN(first_seen_at) AS first_seen_at,
                  MAX(first_seen_at) AS last_seen_at,
                  COALESCE(
                    (ARRAY_AGG(id ORDER BY first_seen_at ASC, id ASC))[1:3],
                    ARRAY[]::uuid[]
                  ) AS sample_message_ids
                FROM messages
                WHERE organization_id = :organization_id
                  AND collision_group_id IS NOT NULL
                GROUP BY collision_group_id
                ORDER BY MAX(first_seen_at) DESC, collision_group_id ASC
                LIMIT :limit
                """
            ),
            {"organization_id": str(organization_id), "limit": limit},
        )
        .mappings()
        .all()
    )

    out: list[OpsCollisionGroupView] = []
    for row in rows:
        sample_ids = [UUID(str(v)) for v in (row["sample_message_ids"] or [])]
        out.append(
            OpsCollisionGroupView(
                collision_group_id=UUID(str(row["collision_group_id"])),
                message_count=int(row["message_count"]),
                first_seen_at=row["first_seen_at"],
                last_seen_at=row["last_seen_at"],
                sample_message_ids=sample_ids,
            )
        )
    return out


def get_metrics_overview(
    *,
    session: Session,
    organization_id: UUID,
) -> OpsMetricsOverviewView:
    status_rows = (
        session.execute(
            text(
                """
                SELECT status, COUNT(*) AS c
                FROM bg_jobs
                WHERE organization_id = :organization_id
                GROUP BY status
                """
            ),
            {"organization_id": str(organization_id)},
        )
        .mappings()
        .all()
    )
    counts_by_status = {str(row["status"]): int(row["c"]) for row in status_rows}

    failed_24h_row = (
        session.execute(
            text(
                """
                SELECT COUNT(*) AS c
                FROM bg_jobs
                WHERE organization_id = :organization_id
                  AND status = 'failed'
                  AND updated_at >= now() - interval '24 hours'
                """
            ),
            {"organization_id": str(organization_id)},
        )
        .mappings()
        .one()
    )

    mailbox_row = (
        session.execute(
            text(
                """
                SELECT
                  COUNT(*) AS mailbox_count,
                  COUNT(*) FILTER (
                    WHERE ingestion_paused_until IS NOT NULL
                      AND ingestion_paused_until > now()
                  ) AS paused_mailbox_count,
                  AVG(EXTRACT(EPOCH FROM (now() - last_incremental_sync_at)))
                    FILTER (WHERE last_incremental_sync_at IS NOT NULL) AS avg_sync_lag_seconds
                FROM mailboxes
                WHERE organization_id = :organization_id
                """
            ),
            {"organization_id": str(organization_id)},
        )
        .mappings()
        .one()
    )

    avg_lag_raw = mailbox_row["avg_sync_lag_seconds"]
    avg_lag = int(avg_lag_raw) if avg_lag_raw is not None else None

    return OpsMetricsOverviewView(
        queued_jobs=counts_by_status.get("queued", 0),
        running_jobs=counts_by_status.get("running", 0),
        failed_jobs_24h=int(failed_24h_row["c"]),
        mailbox_count=int(mailbox_row["mailbox_count"]),
        paused_mailbox_count=int(mailbox_row["paused_mailbox_count"]),
        avg_sync_lag_seconds=avg_lag,
    )
