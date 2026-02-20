from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


def test_metrics_endpoint_exposes_http_metrics() -> None:
    app = create_app()
    client = TestClient(app)

    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200

    res = client.get("/metrics")
    assert res.status_code == 200
    assert "text/plain" in (res.headers.get("content-type") or "")

    body = res.text
    assert "oss_http_requests_total" in body
    assert "oss_http_request_duration_seconds" in body
    assert 'path="/healthz"' in body


def test_metrics_endpoint_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_PROMETHEUS_METRICS", "false")
    get_settings.cache_clear()
    try:
        app = create_app()
        client = TestClient(app)
        assert client.get("/metrics").status_code == 404
    finally:
        get_settings.cache_clear()
