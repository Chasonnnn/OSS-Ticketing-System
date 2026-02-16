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
