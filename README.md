# OSS Ticketing System

Enterprise-grade ticketing system built around Google Workspace journaling: mail is mirrored into a dedicated "journal" Gmail mailbox, ingested via Gmail API, and stored in Postgres as the system of record.

## Docs
- `WORKMAP.md` (week-by-week plan)
- `AGENTS.md` (engineering rules)

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
  - If Gmail returns an invalid/expired `historyId`, the system enqueues a full `mailbox_backfill` recovery job.

## Tests
- API:
  - `cd apps/api && uv run -- ruff check .`
  - `cd apps/api && uv run -- ruff format --check .`
  - `cd apps/api && uv run -m pytest -v`
- Web:
  - `cd apps/web && pnpm lint`
  - `cd apps/web && pnpm tsc --noEmit`
  - `cd apps/web && pnpm test --run`
