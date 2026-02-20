from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import create_app
from app.models.enums import (
    JobStatus,
    JobType,
    MailboxProvider,
    MailboxPurpose,
    MembershipRole,
    MessageDirection,
)
from app.models.identity import Membership, Organization, User
from app.models.jobs import BgJob
from app.models.mail import Mailbox, Message, OAuthCredential


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


def test_ops_mailboxes_sync_and_metrics_overview(db_session: Session) -> None:
    app = create_app()
    client = TestClient(app)

    login = _dev_login(client, email="ops-sync-admin@example.com", organization_name="Org Ops Sync")
    org_id = UUID(login["organization"]["id"])

    cred = OAuthCredential(
        organization_id=org_id,
        provider="google",
        subject="ops-sync@example.com",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        encrypted_refresh_token=b"refresh",
        encrypted_access_token=b"access",
        access_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(cred)
    db_session.flush()

    mailbox_one = Mailbox(
        organization_id=org_id,
        purpose=MailboxPurpose.journal,
        provider=MailboxProvider.gmail,
        email_address="journal-one@example.com",
        oauth_credential_id=cred.id,
        is_enabled=True,
        gmail_history_id=123,
        last_full_sync_at=datetime.now(UTC) - timedelta(hours=2),
        last_incremental_sync_at=datetime.now(UTC) - timedelta(minutes=3),
        ingestion_paused_until=datetime.now(UTC) + timedelta(minutes=20),
        ingestion_pause_reason="Manual pause by admin (20 minutes)",
    )
    mailbox_two = Mailbox(
        organization_id=org_id,
        purpose=MailboxPurpose.journal,
        provider=MailboxProvider.gmail,
        email_address="journal-two@example.com",
        oauth_credential_id=cred.id,
        is_enabled=True,
        gmail_history_id=456,
        last_full_sync_at=datetime.now(UTC) - timedelta(hours=1),
        last_incremental_sync_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    db_session.add_all([mailbox_one, mailbox_two])
    db_session.flush()

    db_session.add_all(
        [
            BgJob(
                organization_id=org_id,
                mailbox_id=mailbox_one.id,
                type=JobType.mailbox_backfill,
                status=JobStatus.queued,
                payload={},
                dedupe_key=f"mailbox_backfill:{mailbox_one.id}",
            ),
            BgJob(
                organization_id=org_id,
                mailbox_id=mailbox_one.id,
                type=JobType.mailbox_history_sync,
                status=JobStatus.running,
                payload={},
                dedupe_key=f"mailbox_history_sync:{mailbox_one.id}",
            ),
            BgJob(
                organization_id=org_id,
                mailbox_id=mailbox_one.id,
                type=JobType.occurrence_parse,
                status=JobStatus.failed,
                payload={},
                dedupe_key=f"occurrence_parse:{uuid4()}",
                last_error="parse failed",
            ),
            BgJob(
                organization_id=org_id,
                mailbox_id=mailbox_two.id,
                type=JobType.occurrence_fetch_raw,
                status=JobStatus.failed,
                payload={},
                dedupe_key=f"occurrence_fetch_raw:{uuid4()}",
                last_error="fetch failed",
            ),
        ]
    )
    db_session.commit()

    sync_res = client.get("/ops/mailboxes/sync")
    assert sync_res.status_code == 200
    sync_items = sync_res.json()["items"]
    assert len(sync_items) == 2
    by_mailbox_id = {row["mailbox_id"]: row for row in sync_items}

    one = by_mailbox_id[str(mailbox_one.id)]
    assert one["queued_jobs_by_type"]["mailbox_backfill"] == 1
    assert one["running_jobs_by_type"]["mailbox_history_sync"] == 1
    assert one["failed_jobs_last_24h"] == 1
    assert one["sync_lag_seconds"] >= 120
    assert one["pause_reason"] is not None

    two = by_mailbox_id[str(mailbox_two.id)]
    assert two["failed_jobs_last_24h"] == 1

    metrics_res = client.get("/ops/metrics/overview")
    assert metrics_res.status_code == 200
    metrics = metrics_res.json()
    assert metrics["mailbox_count"] == 2
    assert metrics["paused_mailbox_count"] == 1
    assert metrics["queued_jobs"] == 1
    assert metrics["running_jobs"] == 1
    assert metrics["failed_jobs_24h"] == 2
    assert metrics["avg_sync_lag_seconds"] is not None
    assert metrics["avg_sync_lag_seconds"] >= 30


def test_ops_collision_groups_summary(db_session: Session) -> None:
    app = create_app()
    client = TestClient(app)

    login = _dev_login(
        client,
        email="ops-collisions-admin@example.com",
        organization_name="Org Ops Collisions",
    )
    org_id = UUID(login["organization"]["id"])
    collision_group_id = uuid4()

    message_one = Message(
        organization_id=org_id,
        direction=MessageDirection.inbound,
        oss_message_id=None,
        rfc_message_id="<m1@example.com>",
        fingerprint_v1=b"a" * 32,
        signature_v1=b"b" * 32,
        collision_group_id=collision_group_id,
    )
    message_two = Message(
        organization_id=org_id,
        direction=MessageDirection.inbound,
        oss_message_id=None,
        rfc_message_id="<m2@example.com>",
        fingerprint_v1=b"c" * 32,
        signature_v1=b"d" * 32,
        collision_group_id=collision_group_id,
    )
    message_three = Message(
        organization_id=org_id,
        direction=MessageDirection.inbound,
        oss_message_id=None,
        rfc_message_id="<m3@example.com>",
        fingerprint_v1=b"e" * 32,
        signature_v1=b"f" * 32,
        collision_group_id=None,
    )
    db_session.add_all([message_one, message_two, message_three])
    db_session.commit()

    res = client.get("/ops/messages/collisions?limit=10")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) == 1
    assert items[0]["collision_group_id"] == str(collision_group_id)
    assert items[0]["message_count"] == 2
    assert len(items[0]["sample_message_ids"]) == 2


def test_ops_dashboard_endpoints_require_admin_role(db_session: Session) -> None:
    app = create_app()
    client = TestClient(app)

    login = _dev_login(
        client,
        email="ops-viewer-2@example.com",
        organization_name="Org Ops Roles 2",
    )
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

    assert client.get("/ops/mailboxes/sync").status_code == 403
    assert client.get("/ops/messages/collisions").status_code == 403
    assert client.get("/ops/metrics/overview").status_code == 403
