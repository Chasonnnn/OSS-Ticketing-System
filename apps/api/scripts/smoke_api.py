from __future__ import annotations

import os
import sys

import httpx


def _assert_ok(response: httpx.Response, *, label: str) -> None:
    if response.status_code >= 400:
        raise RuntimeError(f"{label} failed: HTTP {response.status_code} body={response.text}")


def main() -> None:
    base_url = os.environ.get("API_BASE_URL", "http://localhost:8000")
    email = os.environ.get("SMOKE_EMAIL", "smoke-admin@example.com")
    organization_name = os.environ.get("SMOKE_ORG", "Smoke Test Org")

    with httpx.Client(base_url=base_url, timeout=20.0) as client:
        health = client.get("/healthz")
        _assert_ok(health, label="GET /healthz")
        print("ok: GET /healthz")

        ready = client.get("/readyz")
        _assert_ok(ready, label="GET /readyz")
        print("ok: GET /readyz")

        csrf_res = client.get("/auth/csrf")
        _assert_ok(csrf_res, label="GET /auth/csrf")
        csrf_token = csrf_res.json()["csrf_token"]
        print("ok: GET /auth/csrf")

        login = client.post(
            "/auth/dev/login",
            json={"email": email, "organization_name": organization_name},
            headers={"x-csrf-token": csrf_token},
        )
        _assert_ok(login, label="POST /auth/dev/login")
        login_data = login.json()
        print("ok: POST /auth/dev/login")

        me = client.get("/me")
        _assert_ok(me, label="GET /me")
        print("ok: GET /me")

        tickets = client.get("/tickets", params={"limit": 20})
        _assert_ok(tickets, label="GET /tickets")
        print("ok: GET /tickets")

        ops_metrics = client.get("/ops/metrics/overview")
        _assert_ok(ops_metrics, label="GET /ops/metrics/overview")
        print("ok: GET /ops/metrics/overview")

        org = login_data["organization"]
        user = login_data["user"]
        print(f"smoke complete: org={org['name']} ({org['id']}) user={user['email']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"smoke failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
