from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from contextvars import ContextVar
from dataclasses import dataclass, field

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

from app.core.config import Settings
from app.core.security import new_random_token

request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
logger = logging.getLogger("oss.api")


@dataclass
class RateLimiter:
    max_requests: int
    window_seconds: int = 60
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _buckets: dict[str, deque[float]] = field(default_factory=dict)

    def allow(self, key: str, *, now_ts: float) -> bool:
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = deque()
                self._buckets[key] = bucket

            cutoff = now_ts - float(self.window_seconds)
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= self.max_requests:
                return False

            bucket.append(now_ts)
            return True


def build_request_id(request: Request, *, header_name: str) -> str:
    incoming = (request.headers.get(header_name) or "").strip()
    if incoming:
        return incoming[:128]
    return new_random_token(nbytes=18)


def apply_security_headers(response: Response, *, settings: Settings) -> None:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Content-Security-Policy", settings.CONTENT_SECURITY_POLICY)


def rate_limit_key(request: Request) -> str:
    forwarded_for = (request.headers.get("x-forwarded-for") or "").strip()
    if forwarded_for:
        ip = forwarded_for.split(",", 1)[0].strip()
    else:
        ip = request.client.host if request.client else "unknown"
    return ip


def rate_limit_response() -> JSONResponse:
    return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})


def log_request_completion(
    *,
    request_id: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: int,
    rate_limited: bool,
) -> None:
    logger.info(
        json.dumps(
            {
                "event": "http.request.completed",
                "request_id": request_id,
                "method": method,
                "path": path,
                "status_code": status_code,
                "duration_ms": duration_ms,
                "rate_limited": rate_limited,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def now_ts() -> float:
    return time.time()
