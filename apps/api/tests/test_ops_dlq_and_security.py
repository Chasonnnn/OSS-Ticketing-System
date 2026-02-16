from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.main import create_app
from app.models.enums import JobStatus, JobType, MembershipRole
from app.models.identity import Membership, Organization, User
from app.models.jobs import BgJob


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


def test_dlq_list_and_replay(db_session: Session) -> None:
    app = create_app()
    client = TestClient(app)

    login = _dev_login(client, email="ops-admin@example.com", organization_name="Org Ops DLQ")
    csrf = login["csrf_token"]
    org, _user = _load_org_and_user(db_session, login_payload=login)

    failed_job = BgJob(
        organization_id=org.id,
        mailbox_id=None,
        type=JobType.occurrence_parse,
        status=JobStatus.failed,
        attempts=3,
        max_attempts=25,
        last_error="parse failed",
        dedupe_key=f"occurrence_parse:{uuid4()}",
        payload={"occurrence_id": str(uuid4())},
        run_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    db_session.add(failed_job)
    db_session.commit()

    listed = client.get("/ops/jobs/dlq")
    assert listed.status_code == 200
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == str(failed_job.id)
    assert items[0]["type"] == "occurrence_parse"
    assert items[0]["last_error"] == "parse failed"

    replay = client.post(f"/ops/jobs/{failed_job.id}/replay", headers={"x-csrf-token": csrf})
    assert replay.status_code == 200
    payload = replay.json()
    assert payload["status"] == "queued"
    assert payload["job_id"] == str(failed_job.id)

    db_session.refresh(failed_job)
    assert failed_job.status == JobStatus.queued
    assert failed_job.last_error is None
    assert failed_job.locked_at is None
    assert failed_job.locked_by is None


def test_dlq_endpoints_require_admin_role(db_session: Session) -> None:
    app = create_app()
    client = TestClient(app)

    login = _dev_login(client, email="ops-viewer@example.com", organization_name="Org Ops Roles")
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

    failed_job = BgJob(
        organization_id=org.id,
        mailbox_id=None,
        type=JobType.occurrence_parse,
        status=JobStatus.failed,
        attempts=1,
        max_attempts=25,
        last_error="parse failed",
        dedupe_key=f"occurrence_parse:{uuid4()}",
        payload={"occurrence_id": str(uuid4())},
    )
    db_session.add(failed_job)
    db_session.commit()

    assert client.get("/ops/jobs/dlq").status_code == 403
    assert (
        client.post(f"/ops/jobs/{failed_job.id}/replay", headers={"x-csrf-token": csrf}).status_code
        == 403
    )


def test_security_headers_and_request_id_are_set() -> None:
    app = create_app()
    client = TestClient(app)

    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.headers.get("x-request-id")
    assert res.headers.get("x-content-type-options") == "nosniff"
    assert res.headers.get("x-frame-options") == "DENY"
    assert res.headers.get("referrer-policy") == "same-origin"
    csp = res.headers.get("content-security-policy")
    assert csp is not None
    assert "default-src 'self'" in csp

    forwarded = client.get("/healthz", headers={"x-request-id": "test-request-id-123"})
    assert forwarded.status_code == 200
    assert forwarded.headers.get("x-request-id") == "test-request-id-123"


def test_rate_limiting_blocks_excessive_requests(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_REQUESTS_PER_MINUTE", "2")
    get_settings.cache_clear()
    try:
        app = create_app()
        client = TestClient(app)

        assert client.get("/healthz").status_code == 200
        assert client.get("/healthz").status_code == 200

        blocked = client.get("/healthz")
        assert blocked.status_code == 429
        assert "rate limit" in blocked.json()["detail"].lower()
    finally:
        get_settings.cache_clear()
