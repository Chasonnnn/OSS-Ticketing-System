# OSS Ticketing API

FastAPI + Postgres backend for the OSS Ticketing System.

## Local dev auth (dev-only)
1. Set `ALLOW_DEV_LOGIN=true` in repo-root `.env`.
2. Fetch a CSRF token:
   - `GET /auth/csrf` (sets `oss_csrf` cookie, returns `{ csrf_token }`)
3. Log in:
   - `POST /auth/dev/login` with header `x-csrf-token: <csrf_token>`
4. Use the returned `csrf_token` (and cookie) for future mutations.

## Worker
- Run the ingestion worker:
  - `uv run -m app.worker`
- Job chain:
  - `mailbox_backfill` / `mailbox_history_sync` -> `occurrence_fetch_raw` -> `occurrence_parse` -> `occurrence_stitch` -> `ticket_apply_routing`
- Recipient evidence precedence written to `message_occurrences`:
  - `X-Gm-Original-To` -> `workspace_header` (`high`)
  - `Delivered-To` -> `delivered_to` (`medium`)
  - `X-Original-To` -> `x_original_to` (`medium`)
  - `To`/`Cc` fallback -> `to_cc_scan` (`low`)
  - Unknown recipient -> `unknown` (`low`) and treated as non-allowlisted in routing (auto-spam)

## Sync Admin Endpoints
- Trigger full backfill:
  - `POST /mailboxes/{mailbox_id}/sync/backfill`
- Trigger incremental history sync:
  - `POST /mailboxes/{mailbox_id}/sync/history`
- Check sync status (lag + queued/running jobs):
  - `GET /mailboxes/{mailbox_id}/sync/status`
- Resume auto-paused ingestion and enqueue history sync:
  - `POST /mailboxes/{mailbox_id}/sync/resume`

## Ticket Endpoints
- List/search with cursor pagination:
  - `GET /tickets`
  - Query params: `limit`, `cursor`, `status`, `q`, `assignee_user_id`, `assignee_queue_id`
- Ticket detail:
  - `GET /tickets/{ticket_id}`
  - Returns ticket data + thread messages + message attachment metadata + ticket events + notes + routing evidence from occurrences.
