from __future__ import annotations

from dataclasses import dataclass
from email.utils import getaddresses

from app.models.enums import RoutingConfidence, RoutingRecipientSource


@dataclass(frozen=True)
class RecipientResolution:
    recipient: str | None
    source: RoutingRecipientSource
    confidence: RoutingConfidence
    evidence: dict


def resolve_original_recipient(
    *,
    headers_json: dict,
    to_emails: list[str],
    cc_emails: list[str],
) -> RecipientResolution:
    x_gm_values = _header_candidates(headers_json, "x-gm-original-to")
    delivered_values = _header_candidates(headers_json, "delivered-to")
    x_original_values = _header_candidates(headers_json, "x-original-to")

    selected: str | None = None
    selected_from: str | None = None
    source = RoutingRecipientSource.unknown
    confidence = RoutingConfidence.low

    if x_gm_values:
        selected = x_gm_values[0]
        selected_from = "X-Gm-Original-To"
        source = RoutingRecipientSource.workspace_header
        confidence = RoutingConfidence.high
    elif delivered_values:
        selected = delivered_values[0]
        selected_from = "Delivered-To"
        source = RoutingRecipientSource.delivered_to
        confidence = RoutingConfidence.medium
    elif x_original_values:
        selected = x_original_values[0]
        selected_from = "X-Original-To"
        source = RoutingRecipientSource.x_original_to
        confidence = RoutingConfidence.medium
    elif to_emails:
        selected = (to_emails[0] or "").strip().lower() or None
        if selected:
            selected_from = "to"
            source = RoutingRecipientSource.to_cc_scan
            confidence = RoutingConfidence.low
    elif cc_emails:
        selected = (cc_emails[0] or "").strip().lower() or None
        if selected:
            selected_from = "cc"
            source = RoutingRecipientSource.to_cc_scan
            confidence = RoutingConfidence.low

    return RecipientResolution(
        recipient=selected,
        source=source,
        confidence=confidence,
        evidence={
            "selected_from": selected_from,
            "selected_value": selected,
            "x_gm_original_to_candidates": x_gm_values,
            "delivered_to_candidates": delivered_values,
            "x_original_to_candidates": x_original_values,
            "to_candidates": [(e or "").strip().lower() for e in to_emails if (e or "").strip()],
            "cc_candidates": [(e or "").strip().lower() for e in cc_emails if (e or "").strip()],
        },
    )


def _header_candidates(headers_json: dict, header_name_lc: str) -> list[str]:
    raw_values: list[str] = []
    for key, value in headers_json.items():
        if (key or "").lower() != header_name_lc:
            continue
        if isinstance(value, list):
            raw_values.extend([str(v) for v in value if v is not None])
        elif value is not None:
            raw_values.append(str(value))

    emails: list[str] = []
    for raw in raw_values:
        parsed = getaddresses([raw])
        for _display_name, addr in parsed:
            candidate = (addr or "").strip().lower()
            if candidate:
                emails.append(candidate)

    return _unique_preserving_order(emails)


def _unique_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered
