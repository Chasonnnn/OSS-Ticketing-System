from __future__ import annotations

import base64
import hashlib
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.enums import BlobKind, JobType, OccurrenceState
from app.storage.factory import build_blob_store
from app.worker.queue import enqueue_job


def occurrence_fetch_raw(*, session: Session, payload: dict) -> None:
    occurrence_id = UUID(payload["occurrence_id"])

    occ = (
        session.execute(
            text(
                """
            SELECT id, organization_id, mailbox_id, gmail_message_id, state, raw_blob_id
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

    if occ["raw_blob_id"] is not None and occ["state"] in (
        OccurrenceState.raw_fetched.value,
        OccurrenceState.parsed.value,
        OccurrenceState.stitched.value,
        OccurrenceState.routed.value,
    ):
        return

    raw_bytes = _get_raw_bytes_from_payload(payload)
    if raw_bytes is None:
        session.execute(
            text(
                """
                UPDATE message_occurrences
                SET state = 'failed',
                    raw_fetch_error = 'raw_eml_base64 missing from payload',
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {"id": str(occurrence_id)},
        )
        return

    sha = hashlib.sha256(raw_bytes).digest()
    sha_hex = sha.hex()
    org_id = UUID(str(occ["organization_id"]))

    storage_key = f"{org_id}/raw_eml/{sha_hex}.eml"
    blob_store = build_blob_store()
    blob_store.put_bytes(key=storage_key, data=raw_bytes, content_type="message/rfc822")

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
            VALUES (:org_id, :kind, :sha256, :size, :key, :content_type, now())
            ON CONFLICT (organization_id, kind, sha256)
            DO UPDATE SET storage_key = EXCLUDED.storage_key
            RETURNING id
            """
            ),
            {
                "org_id": str(org_id),
                "kind": BlobKind.raw_eml.value,
                "sha256": sha,
                "size": len(raw_bytes),
                "key": storage_key,
                "content_type": "message/rfc822",
            },
        )
        .mappings()
        .fetchone()
    )
    assert blob_row is not None
    raw_blob_id = UUID(str(blob_row["id"]))

    session.execute(
        text(
            """
            UPDATE message_occurrences
            SET raw_blob_id = :raw_blob_id,
                raw_fetched_at = now(),
                raw_fetch_error = NULL,
                state = :state,
                updated_at = now()
            WHERE id = :id
            """
        ),
        {
            "id": str(occurrence_id),
            "raw_blob_id": str(raw_blob_id),
            "state": OccurrenceState.raw_fetched.value,
        },
    )

    enqueue_job(
        session=session,
        job_type=JobType.occurrence_parse,
        organization_id=org_id,
        mailbox_id=UUID(str(occ["mailbox_id"])),
        payload={"occurrence_id": str(occurrence_id)},
        dedupe_key=f"occurrence_parse:{occurrence_id}",
    )


def _get_raw_bytes_from_payload(payload: dict) -> bytes | None:
    raw_b64 = payload.get("raw_eml_base64")
    if not raw_b64:
        return None
    return base64.b64decode(raw_b64.encode("ascii"), validate=True)
