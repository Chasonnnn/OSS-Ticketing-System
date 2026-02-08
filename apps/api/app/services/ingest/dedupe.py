from __future__ import annotations

import hashlib
from datetime import datetime
from uuid import UUID

import orjson

from app.services.ingest.types import ParsedAttachment, ParsedEmail


def _stable_json_bytes(obj: object) -> bytes:
    return orjson.dumps(obj, option=orjson.OPT_SORT_KEYS)


def _sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_attachment_sha256(attachment: ParsedAttachment) -> bytes:
    return _sha256(attachment.payload)


def compute_fingerprint_v1(parsed: ParsedEmail, attachment_sha256: list[bytes]) -> bytes:
    body_text = (parsed.body_text or "").strip()
    body_hash = sha256_hex(body_text.encode("utf-8", errors="replace"))
    payload = {
        "from": parsed.from_email,
        "subject_norm": parsed.subject_norm,
        "date": parsed.date.date().isoformat() if parsed.date else None,
        "body_hash_prefix": body_hash[:16],
        "attachment_count": len(attachment_sha256),
        "attachment_sha_prefixes": [a.hex()[:16] for a in attachment_sha256[:10]],
    }
    return _sha256(_stable_json_bytes(payload))


def compute_signature_v1(parsed: ParsedEmail, attachment_sha256: list[bytes]) -> bytes:
    body_text = (parsed.body_text or "").strip()
    payload = {
        "rfc_message_id": parsed.rfc_message_id,
        "date": parsed.date.isoformat() if isinstance(parsed.date, datetime) else None,
        "from": parsed.from_email,
        "to": sorted(parsed.to_emails),
        "cc": sorted(parsed.cc_emails),
        "reply_to": sorted(parsed.reply_to_emails),
        "subject_norm": parsed.subject_norm,
        "body_text": body_text,
        "attachment_sha": [a.hex() for a in attachment_sha256],
    }
    return _sha256(_stable_json_bytes(payload))


def extract_uuid_header(headers_json: dict, header_name: str) -> UUID | None:
    values = headers_json.get(header_name)
    if not values:
        values = headers_json.get(header_name.lower())
    if not values:
        return None
    raw = (values[0] or "").strip()
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None
