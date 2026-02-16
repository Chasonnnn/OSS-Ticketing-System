from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.enums import MessageDirection
from app.worker.errors import PermanentJobError


def outbound_send(*, session: Session, payload: dict) -> None:
    organization_id = UUID(payload["organization_id"])
    message_id = UUID(payload["message_id"])
    ticket_id = UUID(payload["ticket_id"])

    msg = (
        session.execute(
            text(
                """
            SELECT id, direction
            FROM messages
            WHERE organization_id = :organization_id
              AND id = :message_id
            FOR UPDATE
            """
            ),
            {
                "organization_id": str(organization_id),
                "message_id": str(message_id),
            },
        )
        .mappings()
        .first()
    )
    if msg is None:
        raise PermanentJobError("outbound message is missing")
    if msg["direction"] != MessageDirection.outbound.value:
        raise PermanentJobError("message direction must be outbound")

    # Idempotency: replaying the job should not generate duplicate send events.
    existing = (
        session.execute(
            text(
                """
            SELECT id
            FROM ticket_events
            WHERE organization_id = :organization_id
              AND ticket_id = :ticket_id
              AND event_type = 'outbound_sent'
              AND event_data ->> 'message_id' = :message_id
            LIMIT 1
            """
            ),
            {
                "organization_id": str(organization_id),
                "ticket_id": str(ticket_id),
                "message_id": str(message_id),
            },
        )
        .mappings()
        .first()
    )
    if existing is not None:
        return

    session.execute(
        text(
            """
            INSERT INTO ticket_events (
              organization_id,
              ticket_id,
              actor_user_id,
              event_type,
              created_at,
              event_data
            )
            VALUES (
              :organization_id,
              :ticket_id,
              NULL,
              'outbound_sent',
              now(),
              CAST(:event_data AS jsonb)
            )
            """
        ),
        {
            "organization_id": str(organization_id),
            "ticket_id": str(ticket_id),
            "event_data": _json_dumps(
                {
                    "message_id": str(message_id),
                    "send_identity_id": payload.get("send_identity_id"),
                    "to_emails": payload.get("to_emails") or [],
                    "cc_emails": payload.get("cc_emails") or [],
                }
            ),
        },
    )


def _json_dumps(payload: dict) -> str:
    import json

    return json.dumps(payload, separators=(",", ":"), sort_keys=True)
