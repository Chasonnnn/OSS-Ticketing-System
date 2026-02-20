from __future__ import annotations

from prometheus_client import Counter, Histogram

_HTTP_REQUESTS_TOTAL = Counter(
    "oss_http_requests_total",
    "Total HTTP requests handled by the API.",
    labelnames=("method", "path", "status_code"),
)
_HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "oss_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    labelnames=("method", "path"),
)
_HTTP_RATE_LIMITED_TOTAL = Counter(
    "oss_http_rate_limited_total",
    "Total HTTP requests blocked by rate limiting.",
    labelnames=("method", "path"),
)


def observe_http_request(
    *,
    method: str,
    path: str,
    status_code: int,
    duration_ms: int,
    rate_limited: bool,
) -> None:
    safe_path = path or "unknown"
    safe_method = method or "UNKNOWN"

    _HTTP_REQUESTS_TOTAL.labels(
        method=safe_method,
        path=safe_path,
        status_code=str(status_code),
    ).inc()
    _HTTP_REQUEST_DURATION_SECONDS.labels(method=safe_method, path=safe_path).observe(
        max(0.0, duration_ms / 1000.0)
    )
    if rate_limited:
        _HTTP_RATE_LIMITED_TOTAL.labels(method=safe_method, path=safe_path).inc()
