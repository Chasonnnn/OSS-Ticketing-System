from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.middleware import (
    RateLimiter,
    apply_security_headers,
    build_request_id,
    log_request_completion,
    now_ts,
    rate_limit_key,
    rate_limit_response,
    request_id_ctx,
)
from app.routers.auth import router as auth_router
from app.routers.health import router as health_router
from app.routers.mailboxes import router as mailboxes_router
from app.routers.me import router as me_router
from app.routers.ops import router as ops_router
from app.routers.queues import router as queues_router
from app.routers.tickets import router as tickets_router


def create_app() -> FastAPI:
    app = FastAPI(title="OSS Ticketing API")

    settings = get_settings()
    rate_limiter = (
        RateLimiter(max_requests=settings.RATE_LIMIT_REQUESTS_PER_MINUTE)
        if settings.RATE_LIMIT_REQUESTS_PER_MINUTE > 0
        else None
    )
    origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_security_headers_and_request_context(request, call_next):  # type: ignore[no-untyped-def]
        request_id = build_request_id(request, header_name=settings.REQUEST_ID_HEADER)
        token = request_id_ctx.set(request_id)
        start_ts = now_ts()
        method = request.method
        path = request.url.path
        response = None
        blocked = False
        status_code = 500

        try:
            if rate_limiter is not None:
                key = rate_limit_key(request)
                if not rate_limiter.allow(key, now_ts=now_ts()):
                    blocked = True
                    response = rate_limit_response()

            if response is None:
                response = await call_next(request)

            status_code = response.status_code
            response.headers[settings.REQUEST_ID_HEADER] = request_id
            apply_security_headers(response, settings=settings)
            return response
        finally:
            duration_ms = int((now_ts() - start_ts) * 1000)
            log_request_completion(
                request_id=request_id,
                method=method,
                path=path,
                status_code=status_code,
                duration_ms=duration_ms,
                rate_limited=blocked,
            )
            request_id_ctx.reset(token)

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(me_router)
    app.include_router(queues_router)
    app.include_router(tickets_router)
    app.include_router(ops_router)
    app.include_router(mailboxes_router)
    return app


app = create_app()
