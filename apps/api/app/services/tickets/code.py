from __future__ import annotations

import base64
import os


def new_ticket_code() -> str:
    raw = os.urandom(10)
    token = base64.b32encode(raw).decode("ascii").rstrip("=").lower()
    return f"tkt-{token}"
