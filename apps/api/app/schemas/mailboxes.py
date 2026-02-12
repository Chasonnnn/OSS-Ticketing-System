from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MailboxOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    purpose: str
    provider: str
    email_address: str
    gmail_profile_email: str | None
    is_enabled: bool
    created_at: datetime
    updated_at: datetime


class GmailOAuthStartResponse(BaseModel):
    authorization_url: str


class GmailOAuthCallbackResponse(BaseModel):
    status: str
    mailbox_id: UUID


class ConnectivityResponse(BaseModel):
    status: str
    profile_email: str | None
    scopes: list[str]
    error: str | None


class MailboxSyncEnqueueResponse(BaseModel):
    job_type: str
    job_id: UUID | None
