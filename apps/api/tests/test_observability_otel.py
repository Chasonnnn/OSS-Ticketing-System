from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


def test_otel_tracing_disabled_via_config(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_OTEL_TRACING", "false")
    get_settings.cache_clear()
    try:
        app = create_app()
        assert app.state.otel_tracing_enabled is False
        assert app.state.otel_tracing_reason == "disabled"
    finally:
        get_settings.cache_clear()


def test_otel_tracing_requires_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_OTEL_TRACING", "true")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "")
    get_settings.cache_clear()
    try:
        app = create_app()
        assert app.state.otel_tracing_enabled is False
        assert app.state.otel_tracing_reason == "missing_endpoint"
    finally:
        get_settings.cache_clear()


def test_otel_tracing_enablement_instruments_app(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_OTEL_TRACING", "true")
    monkeypatch.setenv("OTEL_TRACE_SAMPLE_RATIO", "0")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://127.0.0.1:4318/v1/traces")
    monkeypatch.setenv("OTEL_SERVICE_NAME", "oss-ticketing-api-test")
    get_settings.cache_clear()
    try:
        app = create_app()
        client = TestClient(app)
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code == 200
        assert app.state.otel_tracing_enabled is True
        assert app.state.otel_tracing_reason == "enabled"
    finally:
        get_settings.cache_clear()
