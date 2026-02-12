from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.crypto import decrypt_bytes, encrypt_bytes
from app.models.enums import JobType
from app.models.mail import Mailbox, OAuthCredential
from app.services.google.gmail import (
    GmailApiError,
    GmailHistoryExpiredError,
    get_message_raw,
    list_history,
    list_message_ids,
)
from app.services.google.oauth import refresh_access_token
from app.worker.queue import enqueue_job


def enqueue_mailbox_backfill(
    *,
    session: Session,
    organization_id: UUID,
    mailbox_id: UUID,
    reason: str,
) -> UUID | None:
    return enqueue_job(
        session=session,
        job_type=JobType.mailbox_backfill,
        organization_id=organization_id,
        mailbox_id=mailbox_id,
        payload={
            "organization_id": str(organization_id),
            "mailbox_id": str(mailbox_id),
            "reason": reason,
        },
        dedupe_key=f"mailbox_backfill:{mailbox_id}",
    )


def enqueue_mailbox_history_sync(
    *,
    session: Session,
    organization_id: UUID,
    mailbox_id: UUID,
    reason: str,
) -> UUID | None:
    return enqueue_job(
        session=session,
        job_type=JobType.mailbox_history_sync,
        organization_id=organization_id,
        mailbox_id=mailbox_id,
        payload={
            "organization_id": str(organization_id),
            "mailbox_id": str(mailbox_id),
            "reason": reason,
        },
        dedupe_key=f"mailbox_history_sync:{mailbox_id}",
    )


def sync_mailbox_backfill(
    *,
    session: Session,
    http_client: httpx.Client,
    organization_id: UUID,
    mailbox_id: UUID,
) -> None:
    mailbox = _load_mailbox_for_sync(
        session=session,
        organization_id=organization_id,
        mailbox_id=mailbox_id,
    )
    if mailbox is None:
        return

    access_token = _get_mailbox_access_token(
        session=session,
        http_client=http_client,
        organization_id=organization_id,
        mailbox=mailbox,
    )

    highest_history_id = mailbox.gmail_history_id
    page_token: str | None = None

    try:
        while True:
            messages, page_token = list_message_ids(
                http_client,
                access_token=access_token,
                page_token=page_token,
            )
            for listed in messages:
                raw_msg = get_message_raw(
                    http_client,
                    access_token=access_token,
                    message_id=listed.id,
                )
                occurrence_id = _upsert_occurrence(
                    session=session,
                    organization_id=organization_id,
                    mailbox_id=mailbox.id,
                    gmail_message_id=raw_msg.id,
                    gmail_thread_id=raw_msg.thread_id,
                    gmail_history_id=raw_msg.history_id,
                    gmail_internal_date=raw_msg.internal_date,
                    label_ids=raw_msg.label_ids,
                )
                _enqueue_occurrence_fetch_raw(
                    session=session,
                    organization_id=organization_id,
                    mailbox_id=mailbox.id,
                    occurrence_id=occurrence_id,
                    raw_base64url=raw_msg.raw,
                )
                if raw_msg.history_id is not None and (
                    highest_history_id is None or raw_msg.history_id > highest_history_id
                ):
                    highest_history_id = raw_msg.history_id

            if not page_token:
                break
    except GmailApiError as e:
        mailbox.last_sync_error = f"Gmail backfill failed ({e.status_code})"
        session.add(mailbox)
        session.flush()
        raise

    now = datetime.now(UTC)
    mailbox.last_full_sync_at = now
    mailbox.last_sync_error = None
    if highest_history_id is not None:
        mailbox.gmail_history_id = highest_history_id
    session.add(mailbox)
    session.flush()

    enqueue_mailbox_history_sync(
        session=session,
        organization_id=organization_id,
        mailbox_id=mailbox.id,
        reason="post_backfill",
    )


def sync_mailbox_history(
    *,
    session: Session,
    http_client: httpx.Client,
    organization_id: UUID,
    mailbox_id: UUID,
) -> None:
    mailbox = _load_mailbox_for_sync(
        session=session,
        organization_id=organization_id,
        mailbox_id=mailbox_id,
    )
    if mailbox is None:
        return

    if mailbox.gmail_history_id is None:
        mailbox.last_sync_error = "No gmail_history_id; queued full backfill"
        session.add(mailbox)
        session.flush()
        enqueue_mailbox_backfill(
            session=session,
            organization_id=organization_id,
            mailbox_id=mailbox.id,
            reason="missing_history_id",
        )
        return

    access_token = _get_mailbox_access_token(
        session=session,
        http_client=http_client,
        organization_id=organization_id,
        mailbox=mailbox,
    )

    highest_history_id = mailbox.gmail_history_id
    page_token: str | None = None
    ordered_message_ids: list[str] = []
    seen_message_ids: set[str] = set()

    try:
        while True:
            page = list_history(
                http_client,
                access_token=access_token,
                start_history_id=mailbox.gmail_history_id,
                page_token=page_token,
            )
            if page.history_id is not None and page.history_id > highest_history_id:
                highest_history_id = page.history_id

            for record in page.records:
                if record.history_id is not None and record.history_id > highest_history_id:
                    highest_history_id = record.history_id
                for message_id in record.message_ids:
                    if message_id in seen_message_ids:
                        continue
                    seen_message_ids.add(message_id)
                    ordered_message_ids.append(message_id)

            if not page.next_page_token:
                break
            page_token = page.next_page_token
    except GmailHistoryExpiredError:
        mailbox.last_sync_error = "Gmail history is invalid/expired; queued full backfill"
        session.add(mailbox)
        session.flush()
        enqueue_mailbox_backfill(
            session=session,
            organization_id=organization_id,
            mailbox_id=mailbox.id,
            reason="history_invalid",
        )
        return
    except GmailApiError as e:
        mailbox.last_sync_error = f"Gmail incremental sync failed ({e.status_code})"
        session.add(mailbox)
        session.flush()
        raise

    try:
        for message_id in ordered_message_ids:
            raw_msg = get_message_raw(
                http_client,
                access_token=access_token,
                message_id=message_id,
            )
            occurrence_id = _upsert_occurrence(
                session=session,
                organization_id=organization_id,
                mailbox_id=mailbox.id,
                gmail_message_id=raw_msg.id,
                gmail_thread_id=raw_msg.thread_id,
                gmail_history_id=raw_msg.history_id,
                gmail_internal_date=raw_msg.internal_date,
                label_ids=raw_msg.label_ids,
            )
            _enqueue_occurrence_fetch_raw(
                session=session,
                organization_id=organization_id,
                mailbox_id=mailbox.id,
                occurrence_id=occurrence_id,
                raw_base64url=raw_msg.raw,
            )
            if raw_msg.history_id is not None and raw_msg.history_id > highest_history_id:
                highest_history_id = raw_msg.history_id
    except GmailApiError as e:
        mailbox.last_sync_error = f"Gmail incremental sync failed ({e.status_code})"
        session.add(mailbox)
        session.flush()
        raise

    mailbox.gmail_history_id = highest_history_id
    mailbox.last_incremental_sync_at = datetime.now(UTC)
    mailbox.last_sync_error = None
    session.add(mailbox)
    session.flush()


def _load_mailbox_for_sync(
    *,
    session: Session,
    organization_id: UUID,
    mailbox_id: UUID,
) -> Mailbox | None:
    mailbox = (
        session.execute(
            select(Mailbox)
            .where(
                Mailbox.organization_id == organization_id,
                Mailbox.id == mailbox_id,
            )
            .with_for_update()
        )
        .scalars()
        .first()
    )
    if mailbox is None:
        return None
    if not mailbox.is_enabled:
        return None
    now = datetime.now(UTC)
    if mailbox.ingestion_paused_until and mailbox.ingestion_paused_until > now:
        return None
    return mailbox


def _get_mailbox_access_token(
    *,
    session: Session,
    http_client: httpx.Client,
    organization_id: UUID,
    mailbox: Mailbox,
) -> str:
    cred = (
        session.execute(
            select(OAuthCredential).where(
                OAuthCredential.organization_id == organization_id,
                OAuthCredential.id == mailbox.oauth_credential_id,
            )
        )
        .scalars()
        .first()
    )
    if cred is None:
        raise RuntimeError("Mailbox OAuth credential is missing")

    aad = _oauth_credential_aad(organization_id=organization_id, subject=cred.subject)
    refresh_token = decrypt_bytes(blob=cred.encrypted_refresh_token, aad=aad).decode("utf-8")

    now = datetime.now(UTC)
    if (
        cred.encrypted_access_token
        and cred.access_token_expires_at
        and cred.access_token_expires_at > (now + timedelta(seconds=30))
    ):
        try:
            return decrypt_bytes(blob=cred.encrypted_access_token, aad=aad).decode("utf-8")
        except Exception:  # noqa: BLE001
            pass

    settings = get_settings()
    token = refresh_access_token(
        http_client,
        refresh_token=refresh_token,
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
    )

    access_token = token.access_token
    cred.encrypted_access_token = encrypt_bytes(plaintext=access_token.encode("utf-8"), aad=aad)
    cred.access_token_expires_at = now + timedelta(seconds=max(1, token.expires_in))
    session.add(cred)
    session.flush()
    return access_token


def _upsert_occurrence(
    *,
    session: Session,
    organization_id: UUID,
    mailbox_id: UUID,
    gmail_message_id: str,
    gmail_thread_id: str | None,
    gmail_history_id: int | None,
    gmail_internal_date: datetime | None,
    label_ids: list[str],
) -> UUID:
    row = (
        session.execute(
            text(
                """
                INSERT INTO message_occurrences (
                  organization_id,
                  mailbox_id,
                  gmail_message_id,
                  gmail_thread_id,
                  gmail_history_id,
                  gmail_internal_date,
                  label_ids,
                  state,
                  created_at,
                  updated_at
                )
                VALUES (
                  :organization_id,
                  :mailbox_id,
                  :gmail_message_id,
                  :gmail_thread_id,
                  :gmail_history_id,
                  :gmail_internal_date,
                  :label_ids,
                  'discovered',
                  now(),
                  now()
                )
                ON CONFLICT (organization_id, mailbox_id, gmail_message_id)
                DO UPDATE SET
                  gmail_thread_id = EXCLUDED.gmail_thread_id,
                  gmail_history_id = EXCLUDED.gmail_history_id,
                  gmail_internal_date = EXCLUDED.gmail_internal_date,
                  label_ids = EXCLUDED.label_ids,
                  updated_at = now()
                RETURNING id
                """
            ),
            {
                "organization_id": str(organization_id),
                "mailbox_id": str(mailbox_id),
                "gmail_message_id": gmail_message_id,
                "gmail_thread_id": gmail_thread_id,
                "gmail_history_id": gmail_history_id,
                "gmail_internal_date": gmail_internal_date,
                "label_ids": label_ids,
            },
        )
        .mappings()
        .fetchone()
    )
    assert row is not None
    return UUID(str(row["id"]))


def _enqueue_occurrence_fetch_raw(
    *,
    session: Session,
    organization_id: UUID,
    mailbox_id: UUID,
    occurrence_id: UUID,
    raw_base64url: str,
) -> None:
    raw_base64 = _base64url_to_base64(raw_base64url)
    enqueue_job(
        session=session,
        job_type=JobType.occurrence_fetch_raw,
        organization_id=organization_id,
        mailbox_id=mailbox_id,
        payload={
            "occurrence_id": str(occurrence_id),
            "raw_eml_base64": raw_base64,
        },
        dedupe_key=f"occurrence_fetch_raw:{occurrence_id}",
    )


def _base64url_to_base64(value: str) -> str:
    padded = value + ("=" * ((4 - len(value) % 4) % 4))
    raw_bytes = base64.urlsafe_b64decode(padded.encode("ascii"))
    return base64.b64encode(raw_bytes).decode("ascii")


def _oauth_credential_aad(*, organization_id: UUID, subject: str) -> bytes:
    return f"oauth_credentials:{organization_id}:google:{subject}".encode()
