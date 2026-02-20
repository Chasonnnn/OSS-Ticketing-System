from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import create_app
from app.models.enums import MembershipRole, MessageDirection
from app.models.identity import Membership, Organization, User
from app.models.mail import Message
from app.worker.jobs.occurrence_parse import _upsert_canonical_message


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


def test_ops_collision_backfill_assigns_existing_messages(db_session: Session) -> None:
    app = create_app()
    client = TestClient(app)
    login = _dev_login(
        client,
        email="ops-collision-backfill@example.com",
        organization_name="Org Collision Backfill",
    )
    csrf = login["csrf_token"]
    org_id = UUID(login["organization"]["id"])

    fingerprint = b"\x99" * 32
    _upsert_canonical_message(
        session=db_session,
        organization_id=org_id,
        direction=MessageDirection.inbound.value,
        oss_message_id=None,
        rfc_message_id="<backfill-1@example.test>",
        fingerprint_v1=fingerprint,
        signature_v1=b"\xaa" * 32,
    )
    _upsert_canonical_message(
        session=db_session,
        organization_id=org_id,
        direction=MessageDirection.inbound.value,
        oss_message_id=None,
        rfc_message_id="<backfill-2@example.test>",
        fingerprint_v1=fingerprint,
        signature_v1=b"\xbb" * 32,
    )
    db_session.commit()

    # Simulate historical data without collision assignment.
    db_session.execute(
        select(Message).where(
            Message.organization_id == org_id,
            Message.fingerprint_v1 == fingerprint,
        )
    )
    for row in (
        db_session.execute(
            select(Message).where(
                Message.organization_id == org_id,
                Message.fingerprint_v1 == fingerprint,
            )
        )
        .scalars()
        .all()
    ):
        row.collision_group_id = None
        db_session.add(row)
    db_session.commit()

    first = client.post("/ops/messages/collisions/backfill", headers={"x-csrf-token": csrf})
    assert first.status_code == 200
    payload = first.json()
    assert payload["fingerprints_scanned"] >= 1
    assert payload["groups_updated"] >= 1
    assert payload["messages_updated"] >= 2

    rows = (
        db_session.execute(
            select(Message.collision_group_id).where(
                Message.organization_id == org_id,
                Message.fingerprint_v1 == fingerprint,
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 2
    assert rows[0] is not None
    assert rows[0] == rows[1]

    # Idempotent: second run should not update anything.
    second = client.post("/ops/messages/collisions/backfill", headers={"x-csrf-token": csrf})
    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["messages_updated"] == 0


def test_ops_collision_backfill_requires_admin_role(db_session: Session) -> None:
    app = create_app()
    client = TestClient(app)
    login = _dev_login(
        client,
        email="ops-collision-backfill-viewer@example.com",
        organization_name="Org Collision Backfill Role",
    )
    csrf = login["csrf_token"]
    org, user = _load_org_and_user(db_session, login_payload=login)

    membership = (
        db_session.execute(
            select(Membership).where(
                Membership.organization_id == org.id,
                Membership.user_id == user.id,
            )
        )
        .scalars()
        .one()
    )
    membership.role = MembershipRole.viewer
    db_session.commit()

    assert (
        client.post("/ops/messages/collisions/backfill", headers={"x-csrf-token": csrf}).status_code
        == 403
    )
