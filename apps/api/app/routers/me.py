from __future__ import annotations

from fastapi import APIRouter, Depends

from app.core.deps import OrgContext, require_org
from app.schemas.me import MeResponse

router = APIRouter(tags=["me"])


@router.get("/me", response_model=MeResponse)
def me(org: OrgContext = Depends(require_org)) -> MeResponse:
    return MeResponse(
        user=org.user,
        organization=org.organization,
        role=org.membership.role.value,
    )
