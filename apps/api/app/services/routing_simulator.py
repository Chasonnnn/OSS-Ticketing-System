from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class RoutingSimulationResult:
    allowlisted: bool
    would_mark_spam: bool
    matched_rule: dict | None
    applied_actions: dict
    explanation: str


def simulate_routing(
    *,
    session: Session,
    organization_id: UUID,
    recipient: str,
    sender_email: str,
    direction: str,
) -> RoutingSimulationResult:
    recipient_norm = (recipient or "").strip().lower()
    sender_email_norm = (sender_email or "").strip().lower()
    sender_domain = sender_email_norm.split("@", 1)[1] if "@" in sender_email_norm else ""
    direction_norm = (direction or "").strip().lower()

    allowlisted = _is_allowlisted(
        session=session,
        organization_id=organization_id,
        recipient=recipient_norm,
    )
    if not allowlisted:
        return RoutingSimulationResult(
            allowlisted=False,
            would_mark_spam=True,
            matched_rule=None,
            applied_actions={
                "assign_queue_id": None,
                "assign_user_id": None,
                "set_status": "spam",
                "drop": False,
                "auto_close": True,
            },
            explanation=(
                f"Recipient '{recipient_norm or 'unknown'}' is not allowlisted, "
                "so routing would mark the ticket as spam."
            ),
        )

    rules = (
        session.execute(
            text(
                """
            SELECT
              id,
              name,
              priority,
              match_recipient_pattern,
              match_sender_domain_pattern,
              match_sender_email_pattern,
              match_direction,
              action_assign_queue_id,
              action_assign_user_id,
              action_set_status,
              action_drop,
              action_auto_close
            FROM routing_rules
            WHERE organization_id = :organization_id
              AND is_enabled = true
            ORDER BY priority ASC, id ASC
            """
            ),
            {"organization_id": str(organization_id)},
        )
        .mappings()
        .all()
    )

    for rule in rules:
        if not _rule_matches(
            rule=rule,
            recipient=recipient_norm,
            sender_domain=sender_domain,
            sender_email=sender_email_norm,
            direction=direction_norm,
        ):
            continue
        applied_actions = {
            "assign_queue_id": rule["action_assign_queue_id"],
            "assign_user_id": rule["action_assign_user_id"],
            "set_status": rule["action_set_status"],
            "drop": bool(rule["action_drop"]),
            "auto_close": bool(rule["action_auto_close"]),
        }
        return RoutingSimulationResult(
            allowlisted=True,
            would_mark_spam=False,
            matched_rule={
                "id": rule["id"],
                "name": rule["name"],
                "priority": int(rule["priority"]),
            },
            applied_actions=applied_actions,
            explanation=(
                f"Matched rule '{rule['name']}' (priority {rule['priority']}) for "
                f"recipient '{recipient_norm}', sender '{sender_email_norm}', "
                f"direction '{direction_norm}'."
            ),
        )

    return RoutingSimulationResult(
        allowlisted=True,
        would_mark_spam=False,
        matched_rule=None,
        applied_actions={
            "assign_queue_id": None,
            "assign_user_id": None,
            "set_status": None,
            "drop": False,
            "auto_close": False,
        },
        explanation=(
            f"No enabled routing rule matched recipient '{recipient_norm}', "
            f"sender '{sender_email_norm}', direction '{direction_norm}'."
        ),
    )


def _is_allowlisted(*, session: Session, organization_id: UUID, recipient: str) -> bool:
    if not recipient:
        return False
    rows = (
        session.execute(
            text(
                """
            SELECT pattern
            FROM recipient_allowlist
            WHERE organization_id = :organization_id
              AND is_enabled = true
            """
            ),
            {"organization_id": str(organization_id)},
        )
        .mappings()
        .all()
    )
    for row in rows:
        pattern = (row["pattern"] or "").strip().lower()
        if pattern and fnmatch.fnmatch(recipient, pattern):
            return True
    return False


def _rule_matches(
    *,
    rule: dict,
    recipient: str,
    sender_domain: str,
    sender_email: str,
    direction: str,
) -> bool:
    rp = (rule["match_recipient_pattern"] or "").strip().lower()
    if rp and not fnmatch.fnmatch(recipient, rp):
        return False

    sdp = (rule["match_sender_domain_pattern"] or "").strip().lower()
    if sdp and not fnmatch.fnmatch(sender_domain, sdp):
        return False

    sep = (rule["match_sender_email_pattern"] or "").strip().lower()
    if sep and not fnmatch.fnmatch(sender_email, sep):
        return False

    md = (rule["match_direction"] or "").strip().lower()
    return not (md and md != direction)
