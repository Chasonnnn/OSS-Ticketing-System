# OSS Ticketing System

Enterprise-grade ticketing system built around Google Workspace journaling: mail is mirrored into a dedicated "journal" Gmail mailbox, ingested via Gmail API, and stored in Postgres as the system of record.

## Docs
- `WORKMAP.md` (week-by-week plan)
- `AGENTS.md` (engineering rules)
- `docs/self-hosting.md`
- `docs/workspace-journal-setup.md`
- `docs/production-checklist.md`
- `docs/runbooks.md`
- `docs/load-testing.md`

## Development

### Prereqs
- Docker (for Postgres 18 + MinIO)
- Python 3.12+ (API)
- Node 20+ (Web)

### Setup
1. Create a repo-root `.env` from `.env.example` (do not commit it).
   - For local UI testing, set `ALLOW_DEV_LOGIN=true`.
   - For Gmail OAuth, set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`.
   - Set `ENCRYPTION_KEY_BASE64` to **base64 that decodes to 32 bytes** (AES-256).
2. Start dependencies:
   - `docker compose up -d postgres minio`
   - If you already have something on `:5432`, set `POSTGRES_PORT=5433` (in `.env` or inline) and update `DATABASE_URL` to match.
3. Backend:
   - `cd apps/api && uv sync --extra dev --extra test`
   - `cd apps/api && uv run -- uvicorn app.main:app --reload`
4. Frontend:
   - `cd apps/web && pnpm dev`

### Dev Login + CSRF
This repo uses cookie auth + CSRF (double-submit cookie). Any non-GET request must include an `x-csrf-token` header that matches the `oss_csrf` cookie.

For local development, `ALLOW_DEV_LOGIN=true` enables:
- `GET /auth/csrf` (issues a CSRF cookie + returns token)
- `POST /auth/dev/login` (creates a DB-backed session cookie)

The Web UI at `http://localhost:3000/mailboxes` includes a dev-login form and uses the CSRF flow automatically.

### Gmail Journal Mailbox Connect
1. Configure Google OAuth:
   - Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `.env`.
   - Add an authorized redirect URI matching:
     - `${API_BASE_URL}/mailboxes/gmail/oauth/callback`
     - Default: `http://localhost:8000/mailboxes/gmail/oauth/callback`
2. In the Web UI (`/mailboxes`), click "Connect Gmail journal mailbox".
   - After Google redirects back, the API will redirect your browser to:
     - `/mailboxes/connected?mailbox_id=...`
   - On successful connection, the API enqueues an initial `mailbox_backfill` sync job.
3. Connectivity can be checked via:
   - UI button, or
   - `GET /mailboxes/{mailbox_id}/connectivity` (admin-only)

## Ingestion Worker
- Start the worker:
  - `cd apps/api && uv run -m app.worker`
- Sync flow:
  - `mailbox_backfill` lists mailbox messages and upserts `message_occurrences`, then enqueues `occurrence_fetch_raw` jobs.
  - `mailbox_history_sync` processes Gmail history deltas and enqueues `occurrence_fetch_raw` jobs for new message additions.
  - `occurrence_fetch_raw` stores RFC822 bytes in blob storage and enqueues `occurrence_parse`.
  - `occurrence_parse` builds canonical message/content records, resolves recipient evidence, and enqueues `occurrence_stitch`.
  - `occurrence_stitch` links or creates a ticket, then enqueues `ticket_apply_routing`.
  - `ticket_apply_routing` applies recipient allowlist + routing rules and marks the occurrence as routed.
  - If Gmail returns an invalid/expired `historyId`, the system enqueues a full `mailbox_backfill` recovery job.
  - Repeated mailbox sync failures trip a circuit breaker that auto-pauses ingestion for that mailbox.
- Recipient evidence precedence:
  - `X-Gm-Original-To` -> `workspace_header` (`high`)
  - `Delivered-To` -> `delivered_to` (`medium`)
  - `X-Original-To` -> `x_original_to` (`medium`)
  - `To`/`Cc` fallback -> `to_cc_scan` (`low`)
  - Unknown recipient stays `unknown` (`low`) and is treated as non-allowlisted in routing.
- Admin sync controls:
  - `POST /mailboxes/{mailbox_id}/sync/backfill`
  - `POST /mailboxes/{mailbox_id}/sync/history`
  - `GET /mailboxes/{mailbox_id}/sync/status`
  - `POST /mailboxes/{mailbox_id}/sync/pause?minutes=30`
  - `POST /mailboxes/{mailbox_id}/sync/resume` (clears pause and queues history sync)

## Ops APIs
- Mailbox sync summary (all mailboxes):
  - `GET /ops/mailboxes/sync`
- Collision-group summary:
  - `GET /ops/messages/collisions?limit=50`
- Collision-group backfill (assign missing groups on historical ambiguous fingerprints):
  - `POST /ops/messages/collisions/backfill`
- Ops metrics overview:
  - `GET /ops/metrics/overview`
- Prometheus metrics export:
  - `GET /metrics` (when `ENABLE_PROMETHEUS_METRICS=true`)
- OpenTelemetry tracing export:
  - Enable with `ENABLE_OTEL_TRACING=true`
  - Configure collector endpoint via `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`
- DLQ:
  - `GET /ops/jobs/dlq`
  - `POST /ops/jobs/{job_id}/replay`

## Routing Admin APIs
- Allowlist CRUD:
  - `GET /tickets/routing/allowlist`
  - `POST /tickets/routing/allowlist`
  - `PATCH /tickets/routing/allowlist/{allowlist_id}`
  - `DELETE /tickets/routing/allowlist/{allowlist_id}`
- Routing rule CRUD:
  - `GET /tickets/routing/rules`
  - `POST /tickets/routing/rules`
  - `PATCH /tickets/routing/rules/{rule_id}`
  - `DELETE /tickets/routing/rules/{rule_id}`

## Ticket APIs
- List/search tickets (cursor pagination):
  - `GET /tickets?limit=20&cursor=...&status=open&q=refund&assignee_user_id=...&assignee_queue_id=...`
- Ticket detail:
  - `GET /tickets/{ticket_id}`
  - Includes ticket record, stitched thread messages, attachments metadata, events, notes, and per-message routing evidence from `message_occurrences`.
- Attachment download (org-scoped):
  - `GET /tickets/{ticket_id}/attachments/{attachment_id}/download`
  - Returns authenticated, org-scoped downloads; on S3/MinIO storage it issues a short-lived signed redirect URL.

## Ticket UI
- Inbox:
  - `http://localhost:3000/tickets`
- Ticket detail:
  - `http://localhost:3000/tickets/{ticket_id}`

## Tests
- API:
  - `cd apps/api && uv run -- ruff check .`
  - `cd apps/api && uv run -- ruff format --check .`
  - `cd apps/api && uv run -m pytest -v`
- Web:
  - `cd apps/web && pnpm lint`
  - `cd apps/web && pnpm tsc --noEmit`
  - `cd apps/web && pnpm test --run`
