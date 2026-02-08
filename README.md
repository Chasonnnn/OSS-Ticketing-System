# OSS Ticketing System

Enterprise-grade ticketing system built around Google Workspace journaling: mail is mirrored into a dedicated "journal" Gmail mailbox, ingested via Gmail API, and stored in Postgres as the system of record.

## Docs
- `WORKMAP.md` (week-by-week plan)
- `AGENTS.md` (engineering rules)

## Development (Target)
1. `docker compose up -d postgres minio`
   - If you already have something on `:5432`, run: `POSTGRES_PORT=5433 docker compose up -d postgres minio`
   - Then set `DATABASE_URL` to use the same port (e.g. `localhost:5433`)
   - The API reads configuration from repo-root `.env` (see `.env.example`).
2. Backend:
   - `cd apps/api && uv sync --extra dev --extra test`
   - `cd apps/api && uv run -- uvicorn app.main:app --reload`
3. Frontend:
   - `cd apps/web && pnpm dev`
