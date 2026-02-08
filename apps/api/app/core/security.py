from __future__ import annotations

import base64
import hashlib
import hmac
import os

from fastapi import Response

from app.core.config import get_settings


def new_random_token(*, nbytes: int = 32) -> str:
    raw = os.urandom(nbytes)
    # URL-safe base64 without padding to keep cookie/header compact.
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def hash_session_token(token: str) -> bytes:
    settings = get_settings()
    # HMAC adds a server-side pepper; DB compromise alone is not enough to use tokens.
    return hmac.new(
        settings.JWT_SECRET.encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).digest()


def set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN,
        path="/",
        max_age=settings.SESSION_TTL_SECONDS,
    )


def clear_session_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=settings.SESSION_COOKIE_NAME,
        domain=settings.COOKIE_DOMAIN,
        path="/",
    )


def set_csrf_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        key=settings.CSRF_COOKIE_NAME,
        value=token,
        httponly=False,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN,
        path="/",
        max_age=settings.SESSION_TTL_SECONDS,
    )


def clear_csrf_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=settings.CSRF_COOKIE_NAME,
        domain=settings.COOKIE_DOMAIN,
        path="/",
    )
