from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

import httpx
from fastapi import HTTPException, status

GOOGLE_OAUTH_AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"


@dataclass(frozen=True)
class GoogleTokenResponse:
    access_token: str
    expires_in: int
    refresh_token: str | None
    scope: str | None
    token_type: str | None

    @property
    def scopes(self) -> list[str]:
        if not self.scope:
            return []
        # Google returns a space-delimited string.
        return [s for s in self.scope.split(" ") if s]


def build_authorization_url(
    *,
    client_id: str,
    redirect_uri: str,
    scopes: list[str],
    state: str,
) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
        "access_type": "offline",
        # Refresh tokens are often only returned once unless we force consent.
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    return f"{GOOGLE_OAUTH_AUTHORIZE_URL}?{urlencode(params)}"


def exchange_code_for_tokens(
    client: httpx.Client,
    *,
    code: str,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> GoogleTokenResponse:
    res = client.post(
        GOOGLE_OAUTH_TOKEN_URL,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    if res.status_code >= 400:
        # Avoid leaking raw upstream payload (might contain details we don't want to log/return).
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Google token exchange failed",
        )

    payload = res.json()
    return GoogleTokenResponse(
        access_token=payload["access_token"],
        expires_in=int(payload.get("expires_in") or 0),
        refresh_token=payload.get("refresh_token"),
        scope=payload.get("scope"),
        token_type=payload.get("token_type"),
    )


def refresh_access_token(
    client: httpx.Client,
    *,
    refresh_token: str,
    client_id: str,
    client_secret: str,
) -> GoogleTokenResponse:
    res = client.post(
        GOOGLE_OAUTH_TOKEN_URL,
        data={
            "refresh_token": refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    if res.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Google access token refresh failed",
        )

    payload = res.json()
    return GoogleTokenResponse(
        access_token=payload["access_token"],
        expires_in=int(payload.get("expires_in") or 0),
        refresh_token=None,
        scope=payload.get("scope"),
        token_type=payload.get("token_type"),
    )
