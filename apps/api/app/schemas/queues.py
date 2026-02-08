from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class QueueCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=200)


class QueueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    slug: str
    created_at: datetime
