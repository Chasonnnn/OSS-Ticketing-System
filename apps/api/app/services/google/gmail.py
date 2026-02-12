from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from fastapi import HTTPException, status

GMAIL_PROFILE_URL = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
GMAIL_MESSAGES_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
GMAIL_HISTORY_URL = "https://gmail.googleapis.com/gmail/v1/users/me/history"


@dataclass(frozen=True)
class GmailProfile:
    email_address: str
    history_id: int | None


@dataclass(frozen=True)
class GmailMessageListItem:
    id: str
    thread_id: str | None


@dataclass(frozen=True)
class GmailMessageRaw:
    id: str
    thread_id: str | None
    history_id: int | None
    internal_date: datetime | None
    label_ids: list[str]
    raw: str


@dataclass(frozen=True)
class GmailHistoryRecord:
    history_id: int | None
    message_ids: list[str]


@dataclass(frozen=True)
class GmailHistoryPage:
    records: list[GmailHistoryRecord]
    next_page_token: str | None
    history_id: int | None


class GmailApiError(RuntimeError):
    def __init__(self, *, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class GmailHistoryExpiredError(GmailApiError):
    pass


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


def list_message_ids(
    client: httpx.Client,
    *,
    access_token: str,
    page_token: str | None = None,
    max_results: int = 100,
) -> tuple[list[GmailMessageListItem], str | None]:
    params: dict[str, object] = {
        "includeSpamTrash": "true",
        "maxResults": max(1, min(500, max_results)),
    }
    if page_token:
        params["pageToken"] = page_token

    res = client.get(
        GMAIL_MESSAGES_URL,
        params=params,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    _raise_for_gmail_error(res, default_message="Gmail message list failed")

    payload = res.json()
    messages: list[GmailMessageListItem] = []
    for item in payload.get("messages") or []:
        msg_id = item.get("id")
        if not msg_id:
            continue
        messages.append(
            GmailMessageListItem(
                id=msg_id,
                thread_id=item.get("threadId"),
            )
        )

    return messages, payload.get("nextPageToken")


def get_message_raw(
    client: httpx.Client,
    *,
    access_token: str,
    message_id: str,
) -> GmailMessageRaw:
    res = client.get(
        f"{GMAIL_MESSAGES_URL}/{message_id}",
        params={"format": "raw"},
        headers={"Authorization": f"Bearer {access_token}"},
    )
    _raise_for_gmail_error(res, default_message="Gmail raw message fetch failed")

    payload = res.json()
    raw = payload.get("raw")
    if not raw:
        raise GmailApiError(status_code=502, message="Gmail raw message payload missing raw body")

    return GmailMessageRaw(
        id=payload.get("id") or message_id,
        thread_id=payload.get("threadId"),
        history_id=_parse_int(payload.get("historyId")),
        internal_date=_parse_epoch_millis(payload.get("internalDate")),
        label_ids=[v for v in payload.get("labelIds") or [] if isinstance(v, str)],
        raw=raw,
    )


def list_history(
    client: httpx.Client,
    *,
    access_token: str,
    start_history_id: int,
    page_token: str | None = None,
    max_results: int = 100,
) -> GmailHistoryPage:
    params: dict[str, object] = {
        "startHistoryId": str(start_history_id),
        "historyTypes": "messageAdded",
        "maxResults": max(1, min(500, max_results)),
    }
    if page_token:
        params["pageToken"] = page_token

    res = client.get(
        GMAIL_HISTORY_URL,
        params=params,
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if res.status_code == 404:
        raise GmailHistoryExpiredError(
            status_code=res.status_code,
            message="Gmail historyId is invalid or expired",
        )
    _raise_for_gmail_error(res, default_message="Gmail history list failed")

    payload = res.json()
    records: list[GmailHistoryRecord] = []
    for item in payload.get("history") or []:
        message_ids: list[str] = []
        for added in item.get("messagesAdded") or []:
            msg = added.get("message") or {}
            msg_id = msg.get("id")
            if msg_id:
                message_ids.append(msg_id)
        records.append(
            GmailHistoryRecord(
                history_id=_parse_int(item.get("id")),
                message_ids=message_ids,
            )
        )

    return GmailHistoryPage(
        records=records,
        next_page_token=payload.get("nextPageToken"),
        history_id=_parse_int(payload.get("historyId")),
    )


def _raise_for_gmail_error(res: httpx.Response, *, default_message: str) -> None:
    if res.status_code < 400:
        return

    message = default_message
    try:
        payload = res.json()
        message = payload.get("error", {}).get("message") or default_message
    except Exception:  # noqa: BLE001
        message = default_message

    raise GmailApiError(status_code=res.status_code, message=message)


def _parse_int(v: object) -> int | None:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _parse_epoch_millis(v: object) -> datetime | None:
    parsed = _parse_int(v)
    if parsed is None:
        return None
    return datetime.fromtimestamp(parsed / 1000.0, tz=UTC)
