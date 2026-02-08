from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.routers.auth import router as auth_router
from app.routers.health import router as health_router
from app.routers.me import router as me_router
from app.routers.queues import router as queues_router


def create_app() -> FastAPI:
    app = FastAPI(title="OSS Ticketing API")

    settings = get_settings()
    origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(me_router)
    app.include_router(queues_router)
    return app


app = create_app()
