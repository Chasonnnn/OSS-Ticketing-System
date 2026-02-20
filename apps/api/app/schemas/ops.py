from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class DlqJobItem(BaseModel):
    id: UUID
    type: str
    status: str
    attempts: int
    max_attempts: int
    last_error: str | None
    run_at: datetime
    updated_at: datetime
    payload: dict[str, Any]


class DlqJobsResponse(BaseModel):
    items: list[DlqJobItem]


class DlqReplayResponse(BaseModel):
    status: str
    job_id: UUID


class OpsMailboxSyncItem(BaseModel):
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


class OpsMailboxSyncResponse(BaseModel):
    items: list[OpsMailboxSyncItem]


class OpsCollisionGroupItem(BaseModel):
    collision_group_id: UUID
    message_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    sample_message_ids: list[UUID]


class OpsCollisionGroupsResponse(BaseModel):
    items: list[OpsCollisionGroupItem]


class OpsMetricsOverviewResponse(BaseModel):
    queued_jobs: int
    running_jobs: int
    failed_jobs_24h: int
    mailbox_count: int
    paused_mailbox_count: int
    avg_sync_lag_seconds: int | None
