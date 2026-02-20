from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from threading import Lock
from typing import Any

from fastapi import FastAPI

from app.core.config import Settings
from app.db.session import get_engine

logger = logging.getLogger("oss.api")


@dataclass(frozen=True)
class OTelSetupResult:
    enabled: bool
    reason: str
    shutdown: Callable[[], None] | None = None


_TRACER_PROVIDER: Any | None = None
_TRACER_PROVIDER_LOCK = Lock()
_SQLALCHEMY_INSTRUMENTED = False


def setup_otel(*, app: FastAPI, settings: Settings) -> OTelSetupResult:
    if not settings.ENABLE_OTEL_TRACING:
        return OTelSetupResult(enabled=False, reason="disabled")

    endpoint = settings.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT.strip()
    if not endpoint:
        logger.warning(
            "OpenTelemetry tracing is enabled but OTEL_EXPORTER_OTLP_TRACES_ENDPOINT is empty."
        )
        return OTelSetupResult(enabled=False, reason="missing_endpoint")

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
    except Exception as exc:
        logger.warning("OpenTelemetry tracing setup skipped: %s", exc)
        return OTelSetupResult(enabled=False, reason="dependency_missing")

    provider = _get_or_create_provider(
        trace_module=trace,
        tracer_provider_cls=TracerProvider,
        trace_id_ratio_based_cls=TraceIdRatioBased,
        resource_cls=Resource,
        service_name_key=SERVICE_NAME,
        service_version_key=SERVICE_VERSION,
        batch_span_processor_cls=BatchSpanProcessor,
        otlp_exporter_cls=OTLPSpanExporter,
        settings=settings,
    )

    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        excluded_urls=settings.OTEL_EXCLUDED_URLS,
    )

    global _SQLALCHEMY_INSTRUMENTED
    if not _SQLALCHEMY_INSTRUMENTED:
        SQLAlchemyInstrumentor().instrument(
            engine=get_engine(),
            tracer_provider=provider,
        )
        _SQLALCHEMY_INSTRUMENTED = True

    logger.info(
        "OpenTelemetry tracing enabled for service=%s endpoint=%s",
        settings.OTEL_SERVICE_NAME,
        endpoint,
    )

    def _shutdown() -> None:
        with suppress(Exception):
            FastAPIInstrumentor.uninstrument_app(app)

    return OTelSetupResult(enabled=True, reason="enabled", shutdown=_shutdown)


def _get_or_create_provider(
    *,
    trace_module,
    tracer_provider_cls,
    trace_id_ratio_based_cls,
    resource_cls,
    service_name_key: str,
    service_version_key: str,
    batch_span_processor_cls,
    otlp_exporter_cls,
    settings: Settings,
):
    global _TRACER_PROVIDER
    with _TRACER_PROVIDER_LOCK:
        if _TRACER_PROVIDER is not None:
            return _TRACER_PROVIDER

        resource = resource_cls.create(
            {
                service_name_key: settings.OTEL_SERVICE_NAME,
                service_version_key: settings.VERSION,
            }
        )
        provider = tracer_provider_cls(
            resource=resource,
            sampler=trace_id_ratio_based_cls(settings.OTEL_TRACE_SAMPLE_RATIO),
        )

        otlp_headers = _parse_otlp_headers(settings.OTEL_EXPORTER_OTLP_HEADERS)
        exporter_kwargs: dict[str, Any] = {"endpoint": settings.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT}
        if otlp_headers:
            exporter_kwargs["headers"] = otlp_headers

        exporter = otlp_exporter_cls(**exporter_kwargs)
        provider.add_span_processor(batch_span_processor_cls(exporter))
        trace_module.set_tracer_provider(provider)
        _TRACER_PROVIDER = provider
        return provider


def _parse_otlp_headers(raw_headers: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for token in raw_headers.split(","):
        piece = token.strip()
        if not piece:
            continue
        if "=" not in piece:
            logger.warning("Ignoring malformed OTLP header token: %s", piece)
            continue
        key, value = piece.split("=", 1)
        header_key = key.strip()
        header_value = value.strip()
        if not header_key or not header_value:
            logger.warning("Ignoring malformed OTLP header token: %s", piece)
            continue
        out[header_key] = header_value
    return out
