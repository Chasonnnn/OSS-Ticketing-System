from __future__ import annotations

from datetime import UTC, datetime
from email import policy
from email.headerregistry import Address
from email.message import Message
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime

from app.services.ingest.normalize import normalize_subject
from app.services.ingest.sanitize import sanitize_html
from app.services.ingest.types import ParsedAttachment, ParsedEmail


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _lower_emails(emails: list[str]) -> list[str]:
    out: list[str] = []
    for e in emails:
        e = (e or "").strip().lower()
        if e:
            out.append(e)
    return out


def _extract_addresses(msg: Message, header_name: str) -> list[str]:
    values = msg.get_all(header_name, [])
    parsed = getaddresses(values)
    emails = [addr for _name, addr in parsed if addr]
    return _lower_emails(emails)


def _extract_from(msg: Message) -> tuple[str | None, str | None]:
    value = msg.get("From")
    if not value:
        return None, None
    if isinstance(value, Address):
        email = value.addr_spec.lower() if value.addr_spec else None
        name = value.display_name or None
        return email, name
    parsed = getaddresses([value])
    if not parsed:
        return None, None
    name, email = parsed[0]
    return (email or "").strip().lower() or None, (name or "").strip() or None


def _is_attachment(part: Message) -> bool:
    disp = (part.get_content_disposition() or "").lower()
    return bool(disp in {"attachment", "inline"} and part.get_filename())


def _walk_bodies_and_attachments(
    msg: Message,
) -> tuple[str | None, str | None, list[ParsedAttachment]]:
    text_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[ParsedAttachment] = []

    if msg.is_multipart():
        parts = list(msg.walk())
    else:
        parts = [msg]

    for part in parts:
        if part.is_multipart():
            continue

        content_type = (part.get_content_type() or "").lower()
        if _is_attachment(part):
            payload = part.get_payload(decode=True) or b""
            attachments.append(
                ParsedAttachment(
                    filename=part.get_filename(),
                    content_type=content_type or None,
                    payload=payload,
                    is_inline=(part.get_content_disposition() or "").lower() == "inline",
                    content_id=(part.get("Content-ID") or "").strip("<>") or None,
                )
            )
            continue

        try:
            payload_bytes = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            payload_text = payload_bytes.decode(charset, errors="replace")
        except Exception:
            continue

        if content_type == "text/plain":
            if payload_text.strip():
                text_parts.append(payload_text)
        elif content_type == "text/html" and payload_text.strip():
            html_parts.append(payload_text)

    body_text = "\n\n".join([p.strip() for p in text_parts if p.strip()]) or None
    body_html = "\n\n".join([p.strip() for p in html_parts if p.strip()]) or None
    body_html_sanitized = sanitize_html(body_html)
    return body_text, body_html_sanitized, attachments


def parse_raw_email(raw: bytes) -> ParsedEmail:
    msg = BytesParser(policy=policy.default).parsebytes(raw)

    subject = msg.get("Subject")
    subject_str = str(subject) if subject is not None else None
    subject_norm = normalize_subject(subject_str)

    from_email, from_name = _extract_from(msg)
    reply_to_emails = _extract_addresses(msg, "Reply-To")
    to_emails = _extract_addresses(msg, "To")
    cc_emails = _extract_addresses(msg, "Cc")

    rfc_message_id = (msg.get("Message-ID") or "").strip() or None
    date_header = _parse_date(str(msg.get("Date")) if msg.get("Date") is not None else None)

    in_reply_to = (msg.get("In-Reply-To") or "").strip() or None
    references = []
    for ref in msg.get_all("References", []):
        references.extend([r.strip() for r in str(ref).split() if r.strip()])

    body_text, body_html_sanitized, attachments = _walk_bodies_and_attachments(msg)

    headers_json: dict[str, list[str]] = {}
    for k, v in msg.items():
        headers_json.setdefault(k, []).append(str(v))

    return ParsedEmail(
        rfc_message_id=rfc_message_id,
        date=date_header,
        subject=subject_str,
        subject_norm=subject_norm,
        from_email=from_email,
        from_name=from_name,
        reply_to_emails=reply_to_emails,
        to_emails=to_emails,
        cc_emails=cc_emails,
        headers_json=headers_json,
        body_text=body_text,
        body_html_sanitized=body_html_sanitized,
        in_reply_to=in_reply_to,
        references=references,
        attachments=attachments,
    )
