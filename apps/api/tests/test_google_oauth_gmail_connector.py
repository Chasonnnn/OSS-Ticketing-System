from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.main import create_app
from app.models.mail import Mailbox, OAuthCredential


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


def test_gmail_journal_oauth_flow_persists_encrypted_tokens(db_session: Session) -> None:
    app = create_app()
    client = TestClient(app)

    login = _dev_login(client, email="admin@gmail.test", organization_name="Org Gmail OAuth")
    csrf = login["csrf_token"]

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://oauth2.googleapis.com/token":
            body = request.content.decode("utf-8")
            form = dict((k, v[0]) for k, v in parse_qs(body).items())
            if form.get("grant_type") != "authorization_code":
                return httpx.Response(400, json={"error": "unsupported_grant_type"})
            return httpx.Response(
                200,
                json={
                    "access_token": "access-token-1",
                    "expires_in": 3600,
                    "refresh_token": "refresh-token-1",
                    "scope": "https://www.googleapis.com/auth/gmail.readonly",
                    "token_type": "Bearer",
                },
            )

        if str(request.url) == "https://gmail.googleapis.com/gmail/v1/users/me/profile":
            assert request.headers.get("Authorization") == "Bearer access-token-1"
            return httpx.Response(
                200,
                json={"emailAddress": "journal@example.com", "historyId": "123"},
            )

        return httpx.Response(404, json={"error": "not_found"})

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, timeout=10.0)

    from app.core.http import get_http_client

    def override_http_client() -> Generator[httpx.Client, None, None]:
        try:
            yield http_client
        finally:
            pass

    app.dependency_overrides[get_http_client] = override_http_client

    start = client.post("/mailboxes/gmail/journal/oauth/start", headers={"x-csrf-token": csrf})
    assert start.status_code == 200
    auth_url = start.json()["authorization_url"]

    parts = urlsplit(auth_url)
    assert parts.netloc == "accounts.google.com"
    qs = parse_qs(parts.query)
    assert qs["client_id"] == ["test-google-client-id"]
    assert qs["access_type"] == ["offline"]
    assert qs["prompt"] == ["consent"]
    assert "https://www.googleapis.com/auth/gmail.readonly" in qs["scope"][0]
    state = qs["state"][0]

    callback = client.get(f"/mailboxes/gmail/oauth/callback?state={state}&code=test-code")
    assert callback.status_code == 200
    body = callback.json()
    assert body["status"] == "connected"

    mailbox_id = UUID(body["mailbox_id"])

    cred = db_session.execute(select(OAuthCredential)).scalars().one()
    assert cred.organization_id == UUID(login["organization"]["id"])
    assert cred.provider == "google"
    assert cred.subject == "journal@example.com"
    assert cred.scopes == ["https://www.googleapis.com/auth/gmail.readonly"]
    assert cred.encrypted_refresh_token != b"refresh-token-1"
    assert cred.access_token_expires_at is not None
    assert cred.access_token_expires_at > datetime.now(UTC)

    mb = db_session.get(Mailbox, mailbox_id)
    assert mb is not None
    assert mb.provider.value == "gmail"
    assert mb.purpose.value == "journal"
    assert mb.email_address == "journal@example.com"
    assert mb.gmail_profile_email == "journal@example.com"

    check = client.get(f"/mailboxes/{mailbox_id}/connectivity")
    assert check.status_code == 200
    chk = check.json()
    assert chk["status"] == "connected"
    assert chk["profile_email"] == "journal@example.com"
    assert chk["scopes"] == ["https://www.googleapis.com/auth/gmail.readonly"]

    app.dependency_overrides.clear()
    http_client.close()


def test_oauth_state_cannot_be_reused() -> None:
    app = create_app()
    client = TestClient(app)

    login = _dev_login(client, email="admin2@gmail.test", organization_name="Org Gmail OAuth Reuse")
    csrf = login["csrf_token"]

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://oauth2.googleapis.com/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "access-token-2",
                    "expires_in": 3600,
                    "refresh_token": "refresh-token-2",
                    "scope": "https://www.googleapis.com/auth/gmail.readonly",
                    "token_type": "Bearer",
                },
            )
        if str(request.url) == "https://gmail.googleapis.com/gmail/v1/users/me/profile":
            return httpx.Response(
                200,
                json={"emailAddress": "journal2@example.com", "historyId": "5"},
            )
        return httpx.Response(404, json={"error": "not_found"})

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, timeout=10.0)

    from app.core.http import get_http_client

    def override_http_client() -> Generator[httpx.Client, None, None]:
        yield http_client

    app.dependency_overrides[get_http_client] = override_http_client

    start = client.post("/mailboxes/gmail/journal/oauth/start", headers={"x-csrf-token": csrf})
    state = parse_qs(urlsplit(start.json()["authorization_url"]).query)["state"][0]

    first = client.get(f"/mailboxes/gmail/oauth/callback?state={state}&code=test-code")
    assert first.status_code == 200

    second = client.get(f"/mailboxes/gmail/oauth/callback?state={state}&code=test-code")
    assert second.status_code == 400

    app.dependency_overrides.clear()
    http_client.close()


def test_oauth_callback_redirects_for_browser_accept_text_html(db_session: Session) -> None:
    app = create_app()
    client = TestClient(app)

    login = _dev_login(
        client,
        email="admin3@gmail.test",
        organization_name="Org Gmail OAuth Redirect",
    )
    csrf = login["csrf_token"]

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://oauth2.googleapis.com/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "access-token-3",
                    "expires_in": 3600,
                    "refresh_token": "refresh-token-3",
                    "scope": "https://www.googleapis.com/auth/gmail.readonly",
                    "token_type": "Bearer",
                },
            )
        if str(request.url) == "https://gmail.googleapis.com/gmail/v1/users/me/profile":
            return httpx.Response(
                200,
                json={"emailAddress": "journal3@example.com", "historyId": "42"},
            )
        return httpx.Response(404, json={"error": "not_found"})

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, timeout=10.0)

    from app.core.http import get_http_client

    def override_http_client() -> Generator[httpx.Client, None, None]:
        yield http_client

    app.dependency_overrides[get_http_client] = override_http_client

    start = client.post("/mailboxes/gmail/journal/oauth/start", headers={"x-csrf-token": csrf})
    state = parse_qs(urlsplit(start.json()["authorization_url"]).query)["state"][0]

    callback = client.get(
        f"/mailboxes/gmail/oauth/callback?state={state}&code=test-code",
        headers={"accept": "text/html"},
        follow_redirects=False,
    )
    assert callback.status_code in {302, 303}
    assert callback.headers["location"].startswith("http://localhost:3000/")

    # Ensure the mailbox row was still created.
    mb = db_session.execute(select(Mailbox).where(Mailbox.email_address == "journal3@example.com"))
    assert mb.scalars().first() is not None

    app.dependency_overrides.clear()
    http_client.close()
