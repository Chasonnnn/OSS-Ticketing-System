from __future__ import annotations

import fnmatch
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.enums import OccurrenceState


def ticket_apply_routing(*, session: Session, payload: dict) -> None:
    occurrence_id = UUID(payload["occurrence_id"])

    occ = session.execute(
        text(
            """
            SELECT id, organization_id, state, ticket_id, original_recipient
            FROM message_occurrences
            WHERE id = :id
            FOR UPDATE
            """
        ),
        {"id": str(occurrence_id)},
    ).mappings().fetchone()
    if occ is None:
        return
    if occ["state"] == OccurrenceState.routed.value:
        return
    if occ["ticket_id"] is None:
        session.execute(
            text(
                """
                UPDATE message_occurrences
                SET state = 'failed',
                    route_error = 'missing ticket_id',
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": str(occurrence_id)},
        )
        return

    org_id = UUID(str(occ["organization_id"]))
    ticket_id = UUID(str(occ["ticket_id"]))
    recipient = (occ["original_recipient"] or "").lower()

    allowlisted = _is_allowlisted(session=session, org_id=org_id, recipient=recipient)
    if not allowlisted:
        _mark_spam(session=session, org_id=org_id, ticket_id=ticket_id, occurrence_id=occurrence_id, recipient=recipient)
        _mark_routed(session=session, occurrence_id=occurrence_id)
        return

    _apply_first_matching_rule(session=session, org_id=org_id, ticket_id=ticket_id, recipient=recipient, occurrence_id=occurrence_id)
    _mark_routed(session=session, occurrence_id=occurrence_id)


def _is_allowlisted(*, session: Session, org_id: UUID, recipient: str) -> bool:
    if not recipient:
        return False
    rows = session.execute(
        text(
            """
            SELECT pattern
            FROM recipient_allowlist
            WHERE organization_id = :org_id
              AND is_enabled = true
            """
        ),
        {"org_id": str(org_id)},
    ).mappings().all()
    for r in rows:
        pattern = (r["pattern"] or "").lower()
        if not pattern:
            continue
        if fnmatch.fnmatch(recipient, pattern):
            return True
    return False


def _apply_first_matching_rule(
    *,
    session: Session,
    org_id: UUID,
    ticket_id: UUID,
    recipient: str,
    occurrence_id: UUID,
) -> None:
    msg_from = session.execute(
        text(
            """
            SELECT mc.from_email, m.direction
            FROM ticket_messages tm
            JOIN messages m ON m.id = tm.message_id
            JOIN message_contents mc ON mc.message_id = m.id AND mc.organization_id = tm.organization_id
            WHERE tm.organization_id = :org_id
              AND tm.ticket_id = :ticket_id
            ORDER BY mc.parsed_at DESC
            LIMIT 1
            """
        ),
        {"org_id": str(org_id), "ticket_id": str(ticket_id)},
    ).mappings().fetchone()
    from_email = (msg_from["from_email"] or "").lower() if msg_from else ""
    sender_domain = from_email.split("@", 1)[1] if "@" in from_email else ""
    direction = msg_from["direction"] if msg_from else None

    rules = session.execute(
        text(
            """
            SELECT id, match_recipient_pattern, match_sender_domain_pattern, match_sender_email_pattern, match_direction,
                   action_assign_queue_id, action_assign_user_id, action_set_status, action_drop, action_auto_close
            FROM routing_rules
            WHERE organization_id = :org_id
              AND is_enabled = true
            ORDER BY priority ASC, id ASC
            """
        ),
        {"org_id": str(org_id)},
    ).mappings().all()

    for rule in rules:
        if not _rule_matches(rule, recipient=recipient, sender_domain=sender_domain, sender_email=from_email, direction=direction):
            continue
        _apply_rule_actions(session=session, org_id=org_id, ticket_id=ticket_id, rule=rule, occurrence_id=occurrence_id)
        break


def _rule_matches(rule: dict, *, recipient: str, sender_domain: str, sender_email: str, direction: str | None) -> bool:
    rp = (rule["match_recipient_pattern"] or "").lower()
    if rp and not fnmatch.fnmatch(recipient, rp):
        return False
    sdp = (rule["match_sender_domain_pattern"] or "").lower()
    if sdp and not fnmatch.fnmatch(sender_domain, sdp):
        return False
    sep = (rule["match_sender_email_pattern"] or "").lower()
    if sep and not fnmatch.fnmatch(sender_email, sep):
        return False
    md = rule["match_direction"]
    if md and direction and md != direction:
        return False
    return True


def _apply_rule_actions(
    *,
    session: Session,
    org_id: UUID,
    ticket_id: UUID,
    rule: dict,
    occurrence_id: UUID,
) -> None:
    before = session.execute(
        text(
            """
            SELECT status, assignee_user_id, assignee_queue_id
            FROM tickets
            WHERE organization_id = :org_id
              AND id = :ticket_id
            FOR UPDATE
            """
        ),
        {"org_id": str(org_id), "ticket_id": str(ticket_id)},
    ).mappings().fetchone()
    if before is None:
        return

    updates: dict[str, object] = {}
    if rule["action_assign_user_id"] is not None:
        updates["assignee_user_id"] = rule["action_assign_user_id"]
        updates["assignee_queue_id"] = None
    elif rule["action_assign_queue_id"] is not None:
        updates["assignee_queue_id"] = rule["action_assign_queue_id"]
        updates["assignee_user_id"] = None

    if rule["action_set_status"] is not None:
        updates["status"] = rule["action_set_status"]
    if rule["action_auto_close"]:
        updates["status"] = "closed"
        updates["closed_at"] = "now()"

    if updates:
        set_sql_parts = []
        params: dict[str, object] = {"org_id": str(org_id), "ticket_id": str(ticket_id)}
        for k, v in updates.items():
            if v == "now()":
                set_sql_parts.append(f"{k} = now()")
            else:
                set_sql_parts.append(f"{k} = :{k}")
                params[k] = v
        set_sql_parts.append("updated_at = now()")
        set_sql_parts.append("last_activity_at = now()")
        session.execute(
            text(
                f"""
                UPDATE tickets
                SET {", ".join(set_sql_parts)}
                WHERE organization_id = :org_id
                  AND id = :ticket_id
                """
            ),
            params,
        )

    after = session.execute(
        text(
            """
            SELECT status, assignee_user_id, assignee_queue_id
            FROM tickets
            WHERE organization_id = :org_id
              AND id = :ticket_id
            """
        ),
        {"org_id": str(org_id), "ticket_id": str(ticket_id)},
    ).mappings().fetchone()

    session.execute(
        text(
            """
            INSERT INTO ticket_events (organization_id, ticket_id, actor_user_id, event_type, created_at, event_data)
            VALUES (:org_id, :ticket_id, NULL, 'routing_applied', now(), CAST(:event_data AS jsonb))
            """
        ),
        {
            "org_id": str(org_id),
            "ticket_id": str(ticket_id),
            "event_data": _json_dumps(
                {
                    "occurrence_id": str(occurrence_id),
                    "rule_id": str(rule["id"]),
                    "before": dict(before),
                    "after": dict(after) if after else None,
                }
            ),
        },
    )


def _mark_spam(
    *,
    session: Session,
    org_id: UUID,
    ticket_id: UUID,
    occurrence_id: UUID,
    recipient: str,
) -> None:
    session.execute(
        text(
            """
            UPDATE tickets
            SET status = 'spam',
                closed_at = now(),
                updated_at = now(),
                last_activity_at = now()
            WHERE organization_id = :org_id
              AND id = :ticket_id
            """
        ),
        {"org_id": str(org_id), "ticket_id": str(ticket_id)},
    )
    session.execute(
        text(
            """
            INSERT INTO ticket_events (organization_id, ticket_id, actor_user_id, event_type, created_at, event_data)
            VALUES (:org_id, :ticket_id, NULL, 'auto_spam', now(), CAST(:event_data AS jsonb))
            """
        ),
        {
            "org_id": str(org_id),
            "ticket_id": str(ticket_id),
            "event_data": _json_dumps({"occurrence_id": str(occurrence_id), "recipient": recipient}),
        },
    )


def _mark_routed(*, session: Session, occurrence_id: UUID) -> None:
    session.execute(
        text(
            """
            UPDATE message_occurrences
            SET routed_at = now(),
                route_error = NULL,
                state = :state,
                updated_at = now()
            WHERE id = :id
            """
        ),
        {"id": str(occurrence_id), "state": OccurrenceState.routed.value},
    )


def _json_dumps(payload: dict) -> str:
    import json

    return json.dumps(payload, separators=(",", ":"), sort_keys=True)

