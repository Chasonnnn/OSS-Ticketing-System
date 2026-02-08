from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import create_app
from app.models.enums import MembershipRole
from app.models.identity import Membership


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


def test_dev_login_requires_csrf() -> None:
    app = create_app()
    client = TestClient(app)

    res = client.post(
        "/auth/dev/login", json={"email": "a@example.com", "organization_name": "Org A"}
    )
    assert res.status_code == 403


def test_me_and_csrf_protected_mutation() -> None:
    app = create_app()
    client = TestClient(app)

    login = _dev_login(client, email="admin1@example.com", organization_name="Org CSRF Test")
    csrf = login["csrf_token"]

    me = client.get("/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "admin1@example.com"

    # Mutation endpoints require CSRF header + cookie match.
    no_csrf = client.post("/queues", json={"name": "Support"})
    assert no_csrf.status_code == 403

    created = client.post("/queues", json={"name": "Support"}, headers={"x-csrf-token": csrf})
    assert created.status_code == 201
    assert created.json()["slug"] == "support"

    lst = client.get("/queues")
    assert lst.status_code == 200
    assert [q["slug"] for q in lst.json()] == ["support"]


def test_queue_list_is_org_scoped() -> None:
    app = create_app()

    c1 = TestClient(app)
    c2 = TestClient(app)

    login1 = _dev_login(c1, email="admin1@example.com", organization_name="Org Scope 1")
    csrf1 = login1["csrf_token"]
    created = c1.post("/queues", json={"name": "Support"}, headers={"x-csrf-token": csrf1})
    assert created.status_code == 201

    _dev_login(c2, email="admin2@example.com", organization_name="Org Scope 2")
    lst2 = c2.get("/queues")
    assert lst2.status_code == 200
    assert lst2.json() == []


def test_role_check_is_enforced_via_dependency(db_session: Session) -> None:
    app = create_app()
    client = TestClient(app)

    login = _dev_login(client, email="viewer@example.com", organization_name="Org Role Test")
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

    res = client.post("/queues", json={"name": "Should Fail"}, headers={"x-csrf-token": csrf})
    assert res.status_code == 403
