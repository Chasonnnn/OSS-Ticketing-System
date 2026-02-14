from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.enums import JobType, MessageDirection, OccurrenceState
from app.services.ingest.dedupe import (
    compute_attachment_sha256,
    compute_fingerprint_v1,
    compute_signature_v1,
    extract_uuid_header,
)
from app.services.ingest.parser import parse_raw_email
from app.services.ingest.recipient import resolve_original_recipient
from app.storage.factory import build_blob_store
from app.worker.queue import enqueue_job


def occurrence_parse(*, session: Session, payload: dict) -> None:
    occurrence_id = UUID(payload["occurrence_id"])

    occ = (
        session.execute(
            text(
                """
            SELECT id, organization_id, mailbox_id, state, raw_blob_id, message_id
            FROM message_occurrences
            WHERE id = :id
            FOR UPDATE
            """
            ),
            {"id": str(occurrence_id)},
        )
        .mappings()
        .fetchone()
    )
    if occ is None:
        return
    if occ["message_id"] is not None and occ["state"] in (
        OccurrenceState.parsed.value,
        OccurrenceState.stitched.value,
        OccurrenceState.routed.value,
    ):
        return

    if occ["raw_blob_id"] is None:
        session.execute(
            text(
                """
                UPDATE message_occurrences
                SET state = 'failed',
                    parse_error = 'missing raw_blob_id',
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": str(occurrence_id)},
        )
        return

    raw_row = (
        session.execute(
            text("SELECT storage_key FROM blobs WHERE id = :id"),
            {"id": str(occ["raw_blob_id"])},
        )
        .mappings()
        .fetchone()
    )
    if raw_row is None:
        session.execute(
            text(
                """
                UPDATE message_occurrences
                SET state = 'failed',
                    parse_error = 'raw blob row missing',
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": str(occurrence_id)},
        )
        return

    blob_store = build_blob_store()
    try:
        raw_bytes = blob_store.get_bytes(key=str(raw_row["storage_key"]))
    except Exception as e:
        session.execute(
            text(
                """
                UPDATE message_occurrences
                SET state = 'failed',
                    parse_error = :err,
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": str(occurrence_id), "err": f"blob read failed: {e}"},
        )
        return

    parsed = parse_raw_email(raw_bytes)
    attachment_sha = [compute_attachment_sha256(a) for a in parsed.attachments]
    fingerprint_v1 = compute_fingerprint_v1(parsed, attachment_sha)
    signature_v1 = compute_signature_v1(parsed, attachment_sha)

    oss_message_id = extract_uuid_header(parsed.headers_json, "X-OSS-Message-ID")

    message_id = _upsert_canonical_message(
        session=session,
        organization_id=UUID(str(occ["organization_id"])),
        direction=MessageDirection.inbound.value,
        oss_message_id=oss_message_id,
        rfc_message_id=parsed.rfc_message_id,
        fingerprint_v1=fingerprint_v1,
        signature_v1=signature_v1,
    )

    org_id = UUID(str(occ["organization_id"]))
    _insert_message_content(
        session=session, organization_id=org_id, message_id=message_id, parsed=parsed
    )
    _store_attachments(
        session=session,
        organization_id=org_id,
        message_id=message_id,
        attachments=parsed.attachments,
        attachment_sha256=attachment_sha,
    )
    recipient = resolve_original_recipient(
        headers_json=parsed.headers_json,
        to_emails=parsed.to_emails,
        cc_emails=parsed.cc_emails,
    )

    session.execute(
        text(
            """
            UPDATE message_occurrences
            SET message_id = :message_id,
                parsed_at = now(),
                parse_error = NULL,
                original_recipient = :original_recipient,
                original_recipient_source = :original_recipient_source,
                original_recipient_confidence = :original_recipient_confidence,
                original_recipient_evidence = CAST(:original_recipient_evidence AS jsonb),
                state = :state,
                updated_at = now()
            WHERE id = :id
            """
        ),
        {
            "id": str(occurrence_id),
            "message_id": str(message_id),
            "original_recipient": recipient.recipient,
            "original_recipient_source": recipient.source.value,
            "original_recipient_confidence": recipient.confidence.value,
            "original_recipient_evidence": _json_dumps(recipient.evidence),
            "state": OccurrenceState.parsed.value,
        },
    )

    enqueue_job(
        session=session,
        job_type=JobType.occurrence_stitch,
        organization_id=org_id,
        mailbox_id=UUID(str(occ["mailbox_id"])),
        payload={"occurrence_id": str(occurrence_id)},
        dedupe_key=f"occurrence_stitch:{occurrence_id}",
    )


def _upsert_canonical_message(
    *,
    session: Session,
    organization_id: UUID,
    direction: str,
    oss_message_id: UUID | None,
    rfc_message_id: str | None,
    fingerprint_v1: bytes,
    signature_v1: bytes,
) -> UUID:
    if oss_message_id is not None:
        existing = (
            session.execute(
                text(
                    """
                SELECT message_id
                FROM message_oss_ids
                WHERE organization_id = :org_id
                  AND oss_message_id = :oss_message_id
                """
                ),
                {"org_id": str(organization_id), "oss_message_id": str(oss_message_id)},
            )
            .mappings()
            .fetchone()
        )
        if existing is not None:
            return UUID(str(existing["message_id"]))

    existing_fp = (
        session.execute(
            text(
                """
            SELECT message_id
            FROM message_fingerprints
            WHERE organization_id = :org_id
              AND fingerprint_version = 1
              AND fingerprint = :fingerprint
              AND signature_v1 = :signature
            """
            ),
            {
                "org_id": str(organization_id),
                "fingerprint": fingerprint_v1,
                "signature": signature_v1,
            },
        )
        .mappings()
        .fetchone()
    )
    if existing_fp is not None:
        return UUID(str(existing_fp["message_id"]))

    row = (
        session.execute(
            text(
                """
            INSERT INTO messages (
              organization_id,
              direction,
              oss_message_id,
              rfc_message_id,
              fingerprint_v1,
              signature_v1,
              created_at,
              first_seen_at
            )
            VALUES (
              :org_id,
              :direction,
              :oss_message_id,
              :rfc_message_id,
              :fingerprint,
              :signature,
              now(),
              now()
            )
            RETURNING id
            """
            ),
            {
                "org_id": str(organization_id),
                "direction": direction,
                "oss_message_id": str(oss_message_id) if oss_message_id else None,
                "rfc_message_id": rfc_message_id,
                "fingerprint": fingerprint_v1,
                "signature": signature_v1,
            },
        )
        .mappings()
        .fetchone()
    )
    assert row is not None
    message_id = UUID(str(row["id"]))

    session.execute(
        text(
            """
            INSERT INTO message_fingerprints (
              organization_id,
              fingerprint_version,
              fingerprint,
              signature_v1,
              message_id,
              created_at
            )
            VALUES (:org_id, 1, :fingerprint, :signature, :message_id, now())
            ON CONFLICT DO NOTHING
            """
        ),
        {
            "org_id": str(organization_id),
            "fingerprint": fingerprint_v1,
            "signature": signature_v1,
            "message_id": str(message_id),
        },
    )

    if rfc_message_id:
        session.execute(
            text(
                """
                INSERT INTO message_rfc_ids (
                  organization_id,
                  rfc_message_id,
                  signature_v1,
                  message_id,
                  created_at
                )
                VALUES (:org_id, :rfc_message_id, :signature, :message_id, now())
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "org_id": str(organization_id),
                "rfc_message_id": rfc_message_id,
                "signature": signature_v1,
                "message_id": str(message_id),
            },
        )

    if oss_message_id is not None:
        session.execute(
            text(
                """
                INSERT INTO message_oss_ids (organization_id, oss_message_id, message_id, created_at)
                VALUES (:org_id, :oss_message_id, :message_id, now())
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "org_id": str(organization_id),
                "oss_message_id": str(oss_message_id),
                "message_id": str(message_id),
            },
        )

    return message_id


def _insert_message_content(
    *, session: Session, organization_id: UUID, message_id: UUID, parsed
) -> None:
    row = (
        session.execute(
            text(
                """
            SELECT COALESCE(MAX(content_version), 0) AS max_v
            FROM message_contents
            WHERE organization_id = :org_id
              AND message_id = :message_id
            """
            ),
            {"org_id": str(organization_id), "message_id": str(message_id)},
        )
        .mappings()
        .fetchone()
    )
    max_v = int(row["max_v"]) if row is not None else 0
    content_version = max_v + 1 if max_v == 0 else max_v

    session.execute(
        text(
            """
            INSERT INTO message_contents (
              organization_id,
              message_id,
              content_version,
              parser_version,
              parsed_at,
              date_header,
              subject,
              subject_norm,
              from_email,
              from_name,
              reply_to_emails,
              to_emails,
              cc_emails,
              headers_json,
              body_text,
              body_html_sanitized,
              has_attachments,
              attachment_count,
              snippet
            )
            VALUES (
              :org_id,
              :message_id,
              :content_version,
              :parser_version,
              now(),
              :date_header,
              :subject,
              :subject_norm,
              :from_email,
              :from_name,
              :reply_to_emails,
              :to_emails,
              :cc_emails,
              CAST(:headers_json AS jsonb),
              :body_text,
              :body_html_sanitized,
              :has_attachments,
              :attachment_count,
              :snippet
            )
            ON CONFLICT (organization_id, message_id, content_version) DO NOTHING
            """
        ),
        {
            "org_id": str(organization_id),
            "message_id": str(message_id),
            "content_version": content_version,
            "parser_version": 1,
            "date_header": parsed.date,
            "subject": parsed.subject,
            "subject_norm": parsed.subject_norm,
            "from_email": parsed.from_email,
            "from_name": parsed.from_name,
            "reply_to_emails": parsed.reply_to_emails,
            "to_emails": parsed.to_emails,
            "cc_emails": parsed.cc_emails,
            "headers_json": _json_dumps(parsed.headers_json),
            "body_text": parsed.body_text,
            "body_html_sanitized": parsed.body_html_sanitized,
            "has_attachments": bool(parsed.attachments),
            "attachment_count": len(parsed.attachments),
            "snippet": (parsed.body_text or parsed.subject or "")[:280] or None,
        },
    )

    if parsed.in_reply_to:
        session.execute(
            text(
                """
                INSERT INTO message_thread_refs (
                  organization_id,
                  message_id,
                  ref_type,
                  ref_rfc_message_id,
                  created_at
                )
                VALUES (:org_id, :message_id, 'in_reply_to', :ref, now())
                ON CONFLICT DO NOTHING
                """
            ),
            {
                "org_id": str(organization_id),
                "message_id": str(message_id),
                "ref": parsed.in_reply_to,
            },
        )
    for ref in parsed.references:
        session.execute(
            text(
                """
                INSERT INTO message_thread_refs (
                  organization_id,
                  message_id,
                  ref_type,
                  ref_rfc_message_id,
                  created_at
                )
                VALUES (:org_id, :message_id, 'references', :ref, now())
                ON CONFLICT DO NOTHING
                """
            ),
            {"org_id": str(organization_id), "message_id": str(message_id), "ref": ref},
        )


def _store_attachments(
    *,
    session: Session,
    organization_id: UUID,
    message_id: UUID,
    attachments,
    attachment_sha256: list[bytes],
) -> None:
    if not attachments:
        return
    blob_store = build_blob_store()
    for att, sha in zip(attachments, attachment_sha256, strict=True):
        sha_hex = sha.hex()
        storage_key = f"{organization_id}/attachments/{sha_hex}"
        try:
            stored = blob_store.put_bytes(
                key=storage_key, data=att.payload, content_type=att.content_type
            )
        except Exception:
            continue

        blob_row = (
            session.execute(
                text(
                    """
                INSERT INTO blobs (
                  organization_id,
                  kind,
                  sha256,
                  size_bytes,
                  storage_key,
                  content_type,
                  created_at
                )
                VALUES (:org_id, 'attachment', :sha256, :size, :key, :content_type, now())
                ON CONFLICT (organization_id, kind, sha256)
                DO UPDATE SET storage_key = EXCLUDED.storage_key
                RETURNING id
                """
                ),
                {
                    "org_id": str(organization_id),
                    "sha256": sha,
                    "size": stored.size_bytes,
                    "key": stored.storage_key,
                    "content_type": att.content_type,
                },
            )
            .mappings()
            .fetchone()
        )
        if blob_row is None:
            continue

        session.execute(
            text(
                """
                INSERT INTO message_attachments (
                  organization_id,
                  message_id,
                  blob_id,
                  filename,
                  content_type,
                  size_bytes,
                  sha256,
                  is_inline,
                  content_id,
                  created_at
                )
                VALUES (
                  :org_id,
                  :message_id,
                  :blob_id,
                  :filename,
                  :content_type,
                  :size,
                  :sha256,
                  :is_inline,
                  :content_id,
                  now()
                )
                ON CONFLICT (organization_id, message_id, blob_id) DO NOTHING
                """
            ),
            {
                "org_id": str(organization_id),
                "message_id": str(message_id),
                "blob_id": str(blob_row["id"]),
                "filename": att.filename,
                "content_type": att.content_type,
                "size": stored.size_bytes,
                "sha256": sha,
                "is_inline": att.is_inline,
                "content_id": att.content_id,
            },
        )


def _json_dumps(payload: dict) -> str:
    import json

    return json.dumps(payload, separators=(",", ":"), sort_keys=True)
