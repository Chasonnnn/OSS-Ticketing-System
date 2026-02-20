from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.identity import Membership, Queue, User
from app.models.tickets import RecipientAllowlist, RoutingRule
from app.services.audit import log_event


def list_allowlist(*, session: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = (
        session.execute(
            select(RecipientAllowlist)
            .where(RecipientAllowlist.organization_id == organization_id)
            .order_by(RecipientAllowlist.created_at.asc(), RecipientAllowlist.id.asc())
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": row.id,
            "pattern": row.pattern,
            "is_enabled": row.is_enabled,
            "created_at": row.created_at,
        }
        for row in rows
    ]


def create_allowlist_entry(
    *,
    session: Session,
    organization_id: UUID,
    actor_user_id: UUID,
    pattern: str,
    is_enabled: bool,
) -> dict[str, Any]:
    normalized_pattern = _normalize_pattern(pattern)
    if not normalized_pattern:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="pattern is required",
        )

    row = RecipientAllowlist(
        organization_id=organization_id,
        pattern=normalized_pattern,
        is_enabled=is_enabled,
    )
    session.add(row)
    try:
        session.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Allowlist pattern already exists",
        ) from exc

    log_event(
        session=session,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        event_type="routing.allowlist.created",
        event_data={"allowlist_id": str(row.id), "pattern": row.pattern},
    )
    return {
        "id": row.id,
        "pattern": row.pattern,
        "is_enabled": row.is_enabled,
        "created_at": row.created_at,
    }


def update_allowlist_entry(
    *,
    session: Session,
    organization_id: UUID,
    actor_user_id: UUID,
    allowlist_id: UUID,
    updates: dict[str, Any],
) -> dict[str, Any]:
    row = (
        session.execute(
            select(RecipientAllowlist)
            .where(
                RecipientAllowlist.organization_id == organization_id,
                RecipientAllowlist.id == allowlist_id,
            )
            .with_for_update()
        )
        .scalars()
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Allowlist entry not found",
        )

    if "pattern" in updates:
        normalized_pattern = _normalize_pattern(updates["pattern"])
        if not normalized_pattern:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="pattern is required",
            )
        row.pattern = normalized_pattern

    if "is_enabled" in updates and updates["is_enabled"] is not None:
        row.is_enabled = bool(updates["is_enabled"])

    session.add(row)
    try:
        session.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Allowlist pattern already exists",
        ) from exc

    log_event(
        session=session,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        event_type="routing.allowlist.updated",
        event_data={"allowlist_id": str(row.id), "pattern": row.pattern},
    )
    return {
        "id": row.id,
        "pattern": row.pattern,
        "is_enabled": row.is_enabled,
        "created_at": row.created_at,
    }


def delete_allowlist_entry(
    *,
    session: Session,
    organization_id: UUID,
    actor_user_id: UUID,
    allowlist_id: UUID,
) -> None:
    row = (
        session.execute(
            select(RecipientAllowlist)
            .where(
                RecipientAllowlist.organization_id == organization_id,
                RecipientAllowlist.id == allowlist_id,
            )
            .with_for_update()
        )
        .scalars()
        .first()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Allowlist entry not found",
        )
    session.delete(row)
    session.flush()
    log_event(
        session=session,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        event_type="routing.allowlist.deleted",
        event_data={"allowlist_id": str(allowlist_id)},
    )


def list_routing_rules(*, session: Session, organization_id: UUID) -> list[dict[str, Any]]:
    rows = (
        session.execute(
            select(RoutingRule)
            .where(RoutingRule.organization_id == organization_id)
            .order_by(RoutingRule.priority.asc(), RoutingRule.id.asc())
        )
        .scalars()
        .all()
    )
    return [_routing_rule_row(row) for row in rows]


def create_routing_rule(
    *,
    session: Session,
    organization_id: UUID,
    actor_user_id: UUID,
    payload: dict[str, Any],
) -> dict[str, Any]:
    normalized = _normalize_routing_payload(payload)
    _validate_routing_payload(
        session=session,
        organization_id=organization_id,
        assign_queue_id=normalized["action_assign_queue_id"],
        assign_user_id=normalized["action_assign_user_id"],
    )
    _validate_routing_actions(normalized)

    row = RoutingRule(
        organization_id=organization_id,
        name=normalized["name"],
        is_enabled=normalized["is_enabled"],
        priority=normalized["priority"],
        match_recipient_pattern=normalized["match_recipient_pattern"],
        match_sender_domain_pattern=normalized["match_sender_domain_pattern"],
        match_sender_email_pattern=normalized["match_sender_email_pattern"],
        match_direction=normalized["match_direction"],
        action_assign_queue_id=normalized["action_assign_queue_id"],
        action_assign_user_id=normalized["action_assign_user_id"],
        action_set_status=normalized["action_set_status"],
        action_drop=normalized["action_drop"],
        action_auto_close=normalized["action_auto_close"],
    )
    session.add(row)
    session.flush()
    log_event(
        session=session,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        event_type="routing.rule.created",
        event_data={"routing_rule_id": str(row.id), "name": row.name},
    )
    return _routing_rule_row(row)


def update_routing_rule(
    *,
    session: Session,
    organization_id: UUID,
    actor_user_id: UUID,
    rule_id: UUID,
    updates: dict[str, Any],
) -> dict[str, Any]:
    row = (
        session.execute(
            select(RoutingRule)
            .where(
                RoutingRule.organization_id == organization_id,
                RoutingRule.id == rule_id,
            )
            .with_for_update()
        )
        .scalars()
        .first()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Routing rule not found")

    normalized_updates = _normalize_routing_payload(updates, partial=True)

    current_values = _routing_rule_row(row)
    candidate: dict[str, Any] = {
        "name": current_values["name"],
        "is_enabled": current_values["is_enabled"],
        "priority": current_values["priority"],
        "match_recipient_pattern": current_values["match_recipient_pattern"],
        "match_sender_domain_pattern": current_values["match_sender_domain_pattern"],
        "match_sender_email_pattern": current_values["match_sender_email_pattern"],
        "match_direction": row.match_direction,
        "action_assign_queue_id": current_values["action_assign_queue_id"],
        "action_assign_user_id": current_values["action_assign_user_id"],
        "action_set_status": row.action_set_status,
        "action_drop": current_values["action_drop"],
        "action_auto_close": current_values["action_auto_close"],
    }
    candidate.update(normalized_updates)

    _validate_routing_payload(
        session=session,
        organization_id=organization_id,
        assign_queue_id=candidate["action_assign_queue_id"],
        assign_user_id=candidate["action_assign_user_id"],
    )
    _validate_routing_actions(candidate)

    for key, value in normalized_updates.items():
        setattr(row, key, value)

    session.add(row)
    session.flush()
    log_event(
        session=session,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        event_type="routing.rule.updated",
        event_data={"routing_rule_id": str(row.id), "name": row.name},
    )
    return _routing_rule_row(row)


def delete_routing_rule(
    *,
    session: Session,
    organization_id: UUID,
    actor_user_id: UUID,
    rule_id: UUID,
) -> None:
    row = (
        session.execute(
            select(RoutingRule)
            .where(
                RoutingRule.organization_id == organization_id,
                RoutingRule.id == rule_id,
            )
            .with_for_update()
        )
        .scalars()
        .first()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Routing rule not found")

    session.delete(row)
    session.flush()
    log_event(
        session=session,
        organization_id=organization_id,
        actor_user_id=actor_user_id,
        event_type="routing.rule.deleted",
        event_data={"routing_rule_id": str(rule_id)},
    )


def _routing_rule_row(row: RoutingRule) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "is_enabled": row.is_enabled,
        "priority": row.priority,
        "match_recipient_pattern": row.match_recipient_pattern,
        "match_sender_domain_pattern": row.match_sender_domain_pattern,
        "match_sender_email_pattern": row.match_sender_email_pattern,
        "match_direction": row.match_direction.value if row.match_direction is not None else None,
        "action_assign_queue_id": row.action_assign_queue_id,
        "action_assign_user_id": row.action_assign_user_id,
        "action_set_status": (
            row.action_set_status.value if row.action_set_status is not None else None
        ),
        "action_drop": row.action_drop,
        "action_auto_close": row.action_auto_close,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _normalize_routing_payload(payload: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {}

    if "name" in payload:
        name = (payload["name"] or "").strip()
        if not name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="name is required",
            )
        out["name"] = name
    elif not partial:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="name is required",
        )

    if "is_enabled" in payload:
        out["is_enabled"] = bool(payload["is_enabled"])
    elif not partial:
        out["is_enabled"] = True

    if "priority" in payload:
        out["priority"] = int(payload["priority"])
    elif not partial:
        out["priority"] = 100

    for key in (
        "match_recipient_pattern",
        "match_sender_domain_pattern",
        "match_sender_email_pattern",
    ):
        if key in payload:
            value = payload[key]
            out[key] = _normalize_pattern(value) if value is not None else None

    if "match_direction" in payload:
        out["match_direction"] = payload["match_direction"]

    for key in ("action_assign_queue_id", "action_assign_user_id", "action_set_status"):
        if key in payload:
            out[key] = payload[key]

    for key in ("action_drop", "action_auto_close"):
        if key in payload:
            out[key] = bool(payload[key])
        elif not partial:
            out[key] = False

    return out


def _validate_routing_payload(
    *,
    session: Session,
    organization_id: UUID,
    assign_queue_id: UUID | None,
    assign_user_id: UUID | None,
) -> None:
    if assign_queue_id is not None and assign_user_id is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Only one of action_assign_queue_id or action_assign_user_id can be set",
        )

    if assign_queue_id is not None:
        queue_row = (
            session.execute(
                select(Queue.id).where(
                    Queue.organization_id == organization_id,
                    Queue.id == assign_queue_id,
                )
            )
            .scalars()
            .first()
        )
        if queue_row is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="action_assign_queue_id is not in this organization",
            )

    if assign_user_id is not None:
        member_row = (
            session.execute(
                select(Membership.user_id).where(
                    Membership.organization_id == organization_id,
                    Membership.user_id == assign_user_id,
                )
            )
            .scalars()
            .first()
        )
        if member_row is None:
            user_row = (
                session.execute(select(User.id).where(User.id == assign_user_id)).scalars().first()
            )
            if user_row is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="action_assign_user_id does not exist",
                )
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="action_assign_user_id is not in this organization",
            )


def _validate_routing_actions(payload: dict[str, Any]) -> None:
    has_action = any(
        (
            payload.get("action_assign_queue_id") is not None,
            payload.get("action_assign_user_id") is not None,
            payload.get("action_set_status") is not None,
            bool(payload.get("action_drop")),
            bool(payload.get("action_auto_close")),
        )
    )
    if not has_action:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="At least one action_* field must be set",
        )


def _normalize_pattern(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()
