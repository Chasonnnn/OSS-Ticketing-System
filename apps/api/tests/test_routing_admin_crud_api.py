from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import create_app
from app.models.enums import MembershipRole
from app.models.identity import Membership, Organization, Queue, User


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


def test_routing_allowlist_crud(db_session: Session) -> None:
    app = create_app()
    client = TestClient(app)

    login = _dev_login(
        client,
        email="routing-admin-crud@example.com",
        organization_name="Org Routing CRUD",
    )
    csrf = login["csrf_token"]

    created = client.post(
        "/tickets/routing/allowlist",
        json={"pattern": "support@acme.test", "is_enabled": True},
        headers={"x-csrf-token": csrf},
    )
    assert created.status_code == 201
    allow = created.json()
    assert allow["pattern"] == "support@acme.test"
    assert allow["is_enabled"] is True

    listed = client.get("/tickets/routing/allowlist")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["id"] == allow["id"]

    updated = client.patch(
        f"/tickets/routing/allowlist/{allow['id']}",
        json={"pattern": "billing@acme.test", "is_enabled": False},
        headers={"x-csrf-token": csrf},
    )
    assert updated.status_code == 200
    assert updated.json()["pattern"] == "billing@acme.test"
    assert updated.json()["is_enabled"] is False

    duplicate = client.post(
        "/tickets/routing/allowlist",
        json={"pattern": "billing@acme.test", "is_enabled": True},
        headers={"x-csrf-token": csrf},
    )
    assert duplicate.status_code == 409

    deleted = client.delete(
        f"/tickets/routing/allowlist/{allow['id']}",
        headers={"x-csrf-token": csrf},
    )
    assert deleted.status_code == 204
    assert client.get("/tickets/routing/allowlist").json() == []


def test_routing_rules_crud_and_org_scoping(db_session: Session) -> None:
    app = create_app()
    client_one = TestClient(app)
    client_two = TestClient(app)

    login_one = _dev_login(
        client_one,
        email="rules-admin-1@example.com",
        organization_name="Org Routing Rules One",
    )
    csrf_one = login_one["csrf_token"]
    org_one, _user_one = _load_org_and_user(db_session, login_payload=login_one)

    login_two = _dev_login(
        client_two,
        email="rules-admin-2@example.com",
        organization_name="Org Routing Rules Two",
    )
    _csrf_two = login_two["csrf_token"]

    queue = Queue(organization_id=org_one.id, name="Priority Support", slug="priority-support")
    db_session.add(queue)
    db_session.commit()

    created = client_one.post(
        "/tickets/routing/rules",
        json={
            "name": "Support to queue",
            "is_enabled": True,
            "priority": 10,
            "match_recipient_pattern": "support@acme.test",
            "match_sender_domain_pattern": "customer.test",
            "match_sender_email_pattern": None,
            "match_direction": "inbound",
            "action_assign_queue_id": str(queue.id),
            "action_assign_user_id": None,
            "action_set_status": "open",
            "action_drop": False,
            "action_auto_close": False,
        },
        headers={"x-csrf-token": csrf_one},
    )
    assert created.status_code == 201
    rule = created.json()
    assert rule["name"] == "Support to queue"
    assert rule["action_assign_queue_id"] == str(queue.id)
    assert rule["priority"] == 10

    listed_one = client_one.get("/tickets/routing/rules")
    assert listed_one.status_code == 200
    assert len(listed_one.json()) == 1
    assert listed_one.json()[0]["id"] == rule["id"]

    # Org scoping: other org should not see this rule.
    listed_two = client_two.get("/tickets/routing/rules")
    assert listed_two.status_code == 200
    assert listed_two.json() == []

    updated = client_one.patch(
        f"/tickets/routing/rules/{rule['id']}",
        json={
            "name": "Support to queue v2",
            "priority": 5,
            "is_enabled": False,
            "action_set_status": "pending",
        },
        headers={"x-csrf-token": csrf_one},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Support to queue v2"
    assert updated.json()["priority"] == 5
    assert updated.json()["is_enabled"] is False
    assert updated.json()["action_set_status"] == "pending"

    # Wrong org cannot mutate.
    assert (
        client_two.patch(
            f"/tickets/routing/rules/{rule['id']}",
            json={"priority": 99},
            headers={"x-csrf-token": _csrf_two},
        ).status_code
        == 404
    )

    deleted = client_one.delete(
        f"/tickets/routing/rules/{rule['id']}",
        headers={"x-csrf-token": csrf_one},
    )
    assert deleted.status_code == 204
    assert client_one.get("/tickets/routing/rules").json() == []


def test_routing_admin_crud_requires_admin_role(db_session: Session) -> None:
    app = create_app()
    client = TestClient(app)

    login = _dev_login(
        client,
        email="routing-viewer@example.com",
        organization_name="Org Routing Viewer",
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

    assert client.get("/tickets/routing/allowlist").status_code == 403
    assert client.get("/tickets/routing/rules").status_code == 403
    assert (
        client.post(
            "/tickets/routing/allowlist",
            json={"pattern": "blocked@acme.test"},
            headers={"x-csrf-token": csrf},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/tickets/routing/rules",
            json={
                "name": "Viewer blocked",
                "priority": 100,
                "action_drop": False,
                "action_auto_close": False,
            },
            headers={"x-csrf-token": csrf},
        ).status_code
        == 403
    )
