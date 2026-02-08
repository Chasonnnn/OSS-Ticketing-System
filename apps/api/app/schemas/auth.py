from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CsrfTokenResponse(BaseModel):
    csrf_token: str


class DevLoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    organization_name: str = Field(min_length=1, max_length=200)


class SwitchOrgRequest(BaseModel):
    organization_id: UUID


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    display_name: str | None


class OrganizationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    primary_domain: str | None


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    created_at: datetime
    expires_at: datetime


class LoginResponse(BaseModel):
    user: UserOut
    organization: OrganizationOut
    role: str
    session: SessionOut
    csrf_token: str
