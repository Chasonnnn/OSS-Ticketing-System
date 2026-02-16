from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.main import create_app
from app.models.enums import TicketPriority, TicketStatus
from app.models.tickets import Ticket


def _get_csrf(client: TestClient) -> str:
    res = client.get("/auth/csrf")
    assert res.status_code == 200
    return res.json()["csrf_token"]


def _dev_login(client: TestClient, *, email: str, organization_name: str) -> dict:
    csrf = _get_csrf(client)
    res = client.post(
        "/auth/dev/login",
        json={"email": email, "organization_name": organization_name},
        headers={"x-csrf-token": csrf},
    )
    assert res.status_code == 200
    return res.json()


def test_tickets_api_contract_keys_are_stable(db_session: Session) -> None:
    app = create_app()
    client = TestClient(app)

    login = _dev_login(
        client,
        email="contract-admin@example.com",
        organization_name="Org Tickets Contract",
    )
    org_id = UUID(login["organization"]["id"])

    now = datetime.now(UTC)
    db_session.add(
        Ticket(
            organization_id=org_id,
            ticket_code="tkt-contract",
            status=TicketStatus.open,
            priority=TicketPriority.normal,
            subject="Contract test",
            requester_email="customer@example.com",
            first_message_at=now - timedelta(hours=2),
            last_message_at=now - timedelta(hours=1),
            last_activity_at=now - timedelta(minutes=30),
        )
    )
    db_session.commit()

    list_res = client.get("/tickets", params={"limit": 1})
    assert list_res.status_code == 200
    list_payload = list_res.json()
    assert set(list_payload.keys()) == {"items", "next_cursor"}
    assert len(list_payload["items"]) == 1
    assert set(list_payload["items"][0].keys()) == {
        "id",
        "ticket_code",
        "status",
        "priority",
        "subject",
        "requester_email",
        "requester_name",
        "assignee_user_id",
        "assignee_queue_id",
        "created_at",
        "updated_at",
        "first_message_at",
        "last_message_at",
        "last_activity_at",
        "closed_at",
        "stitch_reason",
        "stitch_confidence",
    }

    ticket_id = list_payload["items"][0]["id"]
    detail_res = client.get(f"/tickets/{ticket_id}")
    assert detail_res.status_code == 200
    detail_payload = detail_res.json()
    assert set(detail_payload.keys()) == {"ticket", "messages", "events", "notes"}
    assert set(detail_payload["ticket"].keys()) == {
        "id",
        "ticket_code",
        "status",
        "priority",
        "subject",
        "requester_email",
        "requester_name",
        "assignee_user_id",
        "assignee_queue_id",
        "created_at",
        "updated_at",
        "first_message_at",
        "last_message_at",
        "last_activity_at",
        "closed_at",
        "stitch_reason",
        "stitch_confidence",
    }


def test_tickets_filters_have_expected_indexes_and_plan(db_session: Session) -> None:
    app = create_app()
    client = TestClient(app)

    login = _dev_login(
        client,
        email="plan-admin@example.com",
        organization_name="Org Tickets Plan",
    )
    org_id = UUID(login["organization"]["id"])
    now = datetime.now(UTC)
    db_session.add_all(
        [
            Ticket(
                organization_id=org_id,
                ticket_code="tkt-plan-1",
                status=TicketStatus.open,
                priority=TicketPriority.normal,
                subject="Plan 1",
                requester_email="a@example.com",
                last_activity_at=now - timedelta(minutes=5),
            ),
            Ticket(
                organization_id=org_id,
                ticket_code="tkt-plan-2",
                status=TicketStatus.open,
                priority=TicketPriority.normal,
                subject="Plan 2",
                requester_email="b@example.com",
                last_activity_at=now - timedelta(minutes=10),
            ),
        ]
    )
    db_session.commit()

    index_rows = (
        db_session.execute(
            text(
                """
            SELECT indexname
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = 'tickets'
            """
            )
        )
        .mappings()
        .all()
    )
    index_names = {str(row["indexname"]) for row in index_rows}
    assert "tickets_inbox_idx" in index_names
    assert "tickets_assignee_user_idx" in index_names
    assert "tickets_assignee_queue_idx" in index_names

    # Force planner to choose index paths when available, then verify the expected index appears.
    db_session.execute(text("SET LOCAL enable_seqscan = off"))
    plan_rows = db_session.execute(
        text(
            """
            EXPLAIN
            SELECT id
            FROM tickets
            WHERE organization_id = :organization_id
              AND status = 'open'
            ORDER BY last_activity_at DESC
            LIMIT 20
            """
        ),
        {"organization_id": str(org_id)},
    ).fetchall()
    plan_text = "\n".join(str(row[0]) for row in plan_rows)
    assert "tickets_inbox_idx" in plan_text
