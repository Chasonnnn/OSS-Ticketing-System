from __future__ import annotations

from uuid import UUID

import httpx
from sqlalchemy.orm import Session

from app.services.mailbox_sync import sync_mailbox_backfill
from app.worker.errors import PermanentJobError


def mailbox_backfill(*, session: Session, payload: dict) -> None:
    organization_id_raw = payload.get("organization_id")
    mailbox_id_raw = payload.get("mailbox_id")
    if not organization_id_raw or not mailbox_id_raw:
        raise PermanentJobError("mailbox_backfill payload missing organization_id or mailbox_id")

    organization_id = UUID(str(organization_id_raw))
    mailbox_id = UUID(str(mailbox_id_raw))

    with httpx.Client(timeout=20.0) as http_client:
        sync_mailbox_backfill(
            session=session,
            http_client=http_client,
            organization_id=organization_id,
            mailbox_id=mailbox_id,
        )
