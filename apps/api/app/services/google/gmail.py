from __future__ import annotations

from dataclasses import dataclass

import httpx
from fastapi import HTTPException, status

GMAIL_PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"


@dataclass(frozen=True)
class GmailProfile:
    email_address: str
    history_id: int | None


def get_profile(client: httpx.Client, *, access_token: str) -> GmailProfile:
    res = client.get(
        GMAIL_PROFILE_URL,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if res.status_code >= 400:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Gmail profile lookup failed",
        )

    payload = res.json()
    history_raw = payload.get("historyId")
    return GmailProfile(
        email_address=payload["emailAddress"],
        history_id=int(history_raw) if history_raw is not None else None,
    )
