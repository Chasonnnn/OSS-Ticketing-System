from __future__ import annotations

from collections.abc import Callable

import bleach


def _filter_img_src(value: str) -> str | None:
    v = (value or "").strip()
    if v.startswith("cid:"):
        return v
    return None


def _attr_filter(tag: str, name: str, value: str) -> str | None:
    if tag == "a" and name == "href":
        v = (value or "").strip()
        if v.startswith("http://") or v.startswith("https://") or v.startswith("mailto:"):
            return v
        return None
    if tag == "img" and name == "src":
        return _filter_img_src(value)
    if name in {"title", "alt"}:
        return value
    if tag == "a" and name in {"rel", "target"}:
        return value
    return None


def sanitize_html(html: str | None) -> str | None:
    if html is None:
        return None

    allowed_tags = [
        "a",
        "p",
        "br",
        "div",
        "span",
        "strong",
        "em",
        "b",
        "i",
        "ul",
        "ol",
        "li",
        "blockquote",
        "code",
        "pre",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "table",
        "thead",
        "tbody",
        "tr",
        "td",
        "th",
        "hr",
        "img",
    ]
    allowed_attrs: dict[str, Callable[[str, str, str], str | None] | list[str]] = {
        "*": _attr_filter,
    }

    cleaned = bleach.clean(html, tags=allowed_tags, attributes=allowed_attrs, strip=True)
    cleaned = bleach.linkify(cleaned)
    return cleaned or None
