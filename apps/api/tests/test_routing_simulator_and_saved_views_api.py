from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import create_app
from app.models.enums import MembershipRole, MessageDirection, TicketStatus
from app.models.identity import Membership, Organization, Queue, User
from app.models.tickets import RecipientAllowlist, RoutingRule


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


def _load_org_and_user(db_session: Session, *, login_payload: dict) -> tuple[Organization, User]:
    org = db_session.get(Organization, UUID(login_payload["organization"]["id"]))
    user = db_session.get(User, UUID(login_payload["user"]["id"]))
    assert org is not None
    assert user is not None
    return org, user


def test_routing_simulator_explains_matching_rule(db_session: Session) -> None:
    app = create_app()
    client = TestClient(app)

    login = _dev_login(
        client,
        email="routing-admin@example.com",
        organization_name="Org Routing Simulator",
    )
    csrf = login["csrf_token"]
    org, _user = _load_org_and_user(db_session, login_payload=login)

    queue = Queue(organization_id=org.id, name="Billing", slug="billing")
    db_session.add(queue)
    db_session.flush()
    db_session.add(
        RecipientAllowlist(
            organization_id=org.id,
            pattern="support@acme.test",
            is_enabled=True,
        )
    )
    rule = RoutingRule(
        organization_id=org.id,
        name="Support to Billing",
        priority=10,
        match_recipient_pattern="support@acme.test",
        match_sender_domain_pattern="customer.test",
        match_direction=MessageDirection.inbound,
        action_assign_queue_id=queue.id,
        action_set_status=TicketStatus.open,
        action_drop=False,
        action_auto_close=False,
    )
    db_session.add(rule)
    db_session.commit()

    res = client.post(
        "/tickets/routing/simulate",
        json={
            "recipient": "support@acme.test",
            "sender_email": "alice@customer.test",
            "direction": "inbound",
        },
        headers={"x-csrf-token": csrf},
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload["allowlisted"] is True
    assert payload["would_mark_spam"] is False
    assert payload["matched_rule"]["id"] == str(rule.id)
    assert payload["matched_rule"]["name"] == "Support to Billing"
    assert payload["applied_actions"]["assign_queue_id"] == str(queue.id)
    assert payload["applied_actions"]["set_status"] == "open"
    assert "recipient" in payload["explanation"].lower()


def test_routing_simulator_reports_non_allowlisted_as_spam(db_session: Session) -> None:
    app = create_app()
    client = TestClient(app)

    login = _dev_login(
        client,
        email="routing-admin-2@example.com",
        organization_name="Org Routing Simulator 2",
    )
    csrf = login["csrf_token"]

    res = client.post(
        "/tickets/routing/simulate",
        json={
            "recipient": "unknown@outside.test",
            "sender_email": "alice@customer.test",
            "direction": "inbound",
        },
        headers={"x-csrf-token": csrf},
    )
    assert res.status_code == 200
    payload = res.json()
    assert payload["allowlisted"] is False
    assert payload["would_mark_spam"] is True
    assert payload["matched_rule"] is None


def test_saved_views_crud_and_org_scoping(db_session: Session) -> None:
    app = create_app()
    client_one = TestClient(app)
    client_two = TestClient(app)

    login_one = _dev_login(
        client_one,
        email="views-admin-1@example.com",
        organization_name="Org Saved Views One",
    )
    csrf_one = login_one["csrf_token"]
    _dev_login(
        client_two,
        email="views-admin-2@example.com",
        organization_name="Org Saved Views Two",
    )

    create = client_one.post(
        "/tickets/saved-views",
        json={
            "name": "Open Billing",
            "filters": {
                "status": "open",
                "q": "refund",
                "assignee_queue_id": "11111111-1111-1111-1111-111111111111",
            },
        },
        headers={"x-csrf-token": csrf_one},
    )
    assert create.status_code == 201
    created = create.json()
    assert created["name"] == "Open Billing"
    assert created["filters"]["status"] == "open"
    assert created["filters"]["q"] == "refund"
    assert created["id"]
    assert created["created_at"]
    assert created["updated_at"]

    list_one = client_one.get("/tickets/saved-views")
    assert list_one.status_code == 200
    assert len(list_one.json()) == 1
    assert list_one.json()[0]["id"] == created["id"]

    # Second org must not see first org's saved view.
    list_two = client_two.get("/tickets/saved-views")
    assert list_two.status_code == 200
    assert list_two.json() == []

    delete = client_one.delete(
        f"/tickets/saved-views/{created['id']}",
        headers={"x-csrf-token": csrf_one},
    )
    assert delete.status_code == 204
    assert client_one.get("/tickets/saved-views").json() == []


def test_saved_view_create_requires_agent_or_admin_role(db_session: Session) -> None:
    app = create_app()
    client = TestClient(app)

    login = _dev_login(
        client,
        email="views-viewer@example.com",
        organization_name="Org Saved Views Role",
    )
    csrf = login["csrf_token"]
    org_id = UUID(login["organization"]["id"])
    user_id = UUID(login["user"]["id"])

    membership = (
        db_session.execute(
            select(Membership).where(
                Membership.organization_id == org_id,
                Membership.user_id == user_id,
            )
        )
        .scalars()
        .one()
    )
    membership.role = MembershipRole.viewer
    db_session.commit()

    res = client.post(
        "/tickets/saved-views",
        json={"name": "Viewer blocked", "filters": {"status": "open"}},
        headers={"x-csrf-token": csrf},
    )
    assert res.status_code == 403
