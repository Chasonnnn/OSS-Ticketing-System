# OSS Ticketing System

Enterprise-grade ticketing system built around Google Workspace journaling: mail is mirrored into a dedicated "journal" Gmail mailbox, ingested via Gmail API, and stored in Postgres as the system of record.

## Docs
- `WORKMAP.md` (week-by-week plan)
- `AGENTS.md` (engineering rules)

## Development (Target)
1. `docker compose up -d postgres minio`
2. Backend:
   - `cd apps/api && uv sync --extra test`
   - `cd apps/api && uv run -- uvicorn app.main:app --reload`
3. Frontend:
   - `cd apps/web && pnpm dev`
