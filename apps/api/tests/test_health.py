from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def test_healthz_ok() -> None:
    app = create_app()
    client = TestClient(app)
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}
