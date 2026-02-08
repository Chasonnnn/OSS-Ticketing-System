from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ParsedAttachment:
    filename: str | None
    content_type: str | None
    payload: bytes
    is_inline: bool
    content_id: str | None


@dataclass(frozen=True)
class ParsedEmail:
    rfc_message_id: str | None
    date: datetime | None
    subject: str | None
    subject_norm: str | None
    from_email: str | None
    from_name: str | None
    reply_to_emails: list[str]
    to_emails: list[str]
    cc_emails: list[str]
    headers_json: dict
    body_text: str | None
    body_html_sanitized: str | None
    in_reply_to: str | None
    references: list[str]
    attachments: list[ParsedAttachment]
