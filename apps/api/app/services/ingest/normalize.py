from __future__ import annotations

import re

_SUBJECT_PREFIX_RE = re.compile(r"^\s*(re|fw|fwd)\s*:\s*", re.IGNORECASE)


def normalize_subject(subject: str | None) -> str | None:
    if subject is None:
        return None
    s = subject.strip()
    while True:
        new_s = _SUBJECT_PREFIX_RE.sub("", s)
        if new_s == s:
            break
        s = new_s.strip()
    return s or None
