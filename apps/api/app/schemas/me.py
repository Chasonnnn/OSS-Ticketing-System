from __future__ import annotations

from pydantic import BaseModel

from app.schemas.auth import OrganizationOut, UserOut


class MeResponse(BaseModel):
    user: UserOut
    organization: OrganizationOut
    role: str
