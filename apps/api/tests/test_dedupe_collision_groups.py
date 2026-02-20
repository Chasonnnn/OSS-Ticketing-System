from __future__ import annotations

from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import create_app
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


def test_dedupe_assigns_collision_group_for_fingerprint_ambiguity(db_session: Session) -> None:
    app = create_app()
    client = TestClient(app)
    login = _dev_login(
        client,
        email="dedupe-collisions@example.com",
        organization_name="Org Dedupe Collisions",
    )
    org_id = UUID(login["organization"]["id"])

    fingerprint = b"\x11" * 32
    first_signature = b"\x22" * 32
    second_signature = b"\x33" * 32

    first_message_id = _upsert_canonical_message(
        session=db_session,
        organization_id=org_id,
        direction="inbound",
        oss_message_id=None,
        rfc_message_id="<first@example.test>",
        fingerprint_v1=fingerprint,
        signature_v1=first_signature,
    )
    second_message_id = _upsert_canonical_message(
        session=db_session,
        organization_id=org_id,
        direction="inbound",
        oss_message_id=None,
        rfc_message_id="<second@example.test>",
        fingerprint_v1=fingerprint,
        signature_v1=second_signature,
    )
    db_session.commit()

    assert second_message_id != first_message_id

    first_message = db_session.get(Message, first_message_id)
    second_message = db_session.get(Message, second_message_id)
    assert first_message is not None
    assert second_message is not None
    assert first_message.collision_group_id is not None
    assert second_message.collision_group_id is not None
    assert first_message.collision_group_id == second_message.collision_group_id


def test_dedupe_reuses_existing_collision_group_for_new_signature(db_session: Session) -> None:
    app = create_app()
    client = TestClient(app)
    login = _dev_login(
        client,
        email="dedupe-collisions-2@example.com",
        organization_name="Org Dedupe Collisions 2",
    )
    org_id = UUID(login["organization"]["id"])

    fingerprint = b"\x44" * 32
    signatures = [b"\x51" * 32, b"\x52" * 32, b"\x53" * 32]

    message_ids = [
        _upsert_canonical_message(
            session=db_session,
            organization_id=org_id,
            direction="inbound",
            oss_message_id=None,
            rfc_message_id=f"<msg-{idx}@example.test>",
            fingerprint_v1=fingerprint,
            signature_v1=sig,
        )
        for idx, sig in enumerate(signatures, start=1)
    ]
    db_session.commit()

    rows = db_session.execute(
        select(Message.id, Message.collision_group_id).where(
            Message.organization_id == org_id,
            Message.id.in_(message_ids),
        )
    ).all()
    assert len(rows) == 3
    collision_ids = {row[1] for row in rows}
    assert None not in collision_ids
    assert len(collision_ids) == 1
