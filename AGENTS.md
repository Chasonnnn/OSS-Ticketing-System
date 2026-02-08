# AGENTS.md — OSS Ticketing System

> Single source of truth for building this project. Every contributor (human or AI) follows these rules.

## 1) Production-Quality Standard (Non-Negotiable)

Build FULLY FUNCTIONAL, POLISHED features — not MVPs.

✅ Required:
- Complete error handling & loading states
- Validation & edge cases covered
- Visual polish (consistent styling, transitions)

❌ Forbidden:
- "Basic" or "minimal" implementations
- Missing error/loading states
- "TODO: Add feature X later" comments
- Placeholder text instead of functionality

## 1.1) No Backward Compatibility

This project is still under active development. Breaking changes are acceptable.
- Prioritize clean design over compatibility (API, DB, and UI can change).
- Migrations can be rewritten and ingestion can be re-synced as needed.

## 2) Git Rules

### Commit Prefix Rule
All commits must start with: `feat:`, `fix:`, `docs:`, `refactor:`, `test:`, or `chore:`.

### Commit Message Format
```
feat: Add bulk task completion endpoint
fix: Resolve CSRF validation on file upload
docs: Update agents.md with new commands
refactor: Simplify authorization dependencies
test: Add coverage for mailbox sync recovery
```

## 3) TDD Rule

Write or update tests FIRST.
- Start with a failing test capturing the behavior/bug.
- Implement until it passes.
- If behavior changes, update tests in the same PR.

## 4) Security Boundaries (Zero Tolerance)
- Never commit secrets (use `.env`, keep `.env.example` updated).
- Never log raw PII (mask emails, subjects, bodies; store content only in DB/object storage).
- Never skip org scoping (every query filters by `organization_id`).
- Never auto-send AI-generated messages (human review is required).

## 5) Centralized Dependencies (Backend)
All authorization, org scoping, and CSRF checks are centralized as FastAPI dependencies.
- ✅ Do: `user = Depends(require_roles([...]))`, `org = Depends(require_org())`, `Depends(require_csrf_header)`
- ❌ Don’t: ad-hoc checks scattered inside route functions.

## 6) Tech Stack

Backend:
- FastAPI, Pydantic v2
- PostgreSQL
- SQLAlchemy 2.0 + Alembic
- Cookie auth + CSRF protection
- Google OAuth for mailbox connectors (Gmail API)

Frontend:
- Next.js (App Router), TypeScript (strict)
- Tailwind + shadcn/ui
- TanStack Query for server state
- Zustand for UI-only state
- React Hook Form + Zod

Infra:
- Postgres (required)
- S3-compatible object storage (MinIO for self-host/dev)

## 6.1) Dependency Freshness
- Prefer the latest stable versions of packages/dependencies.
- Do not intentionally choose older versions without a written justification.
- Check and upgrade dependencies regularly; keep CI green after upgrades.

## 7) Repo Structure (Target)

```
apps/api
  app/routers (thin)
  app/services (business logic)
  app/models (SQLAlchemy)
  app/schemas (Pydantic)
  app/core (config/security)
  app/db (engine/session)
  alembic (migrations)
  tests

apps/web
  app/(auth)
  app/(app)
  components
  lib/api
  lib/hooks
  lib/types
  tests
```

## 8) Commands

Backend (apps/api):
- Dev: `cd apps/api && uv sync --extra test` then `cd apps/api && uv run -- uvicorn app.main:app --reload`
- Tests: `cd apps/api && uv run -m pytest -v`
- Lint/format: `cd apps/api && uv run -- ruff check . --fix && uv run -- ruff format .`
- Migrations: `cd apps/api && uv run -m alembic upgrade head`

Frontend (apps/web):
- Dev: `cd apps/web && pnpm dev`
- Typecheck: `cd apps/web && pnpm tsc --noEmit`
- Tests: `cd apps/web && pnpm test --run`
- Lint: `cd apps/web && pnpm lint`

Database:
- Postgres: `docker compose up -d postgres`

## 9) Mailflow Guardrails (Required)
- Workspace mirroring rules MUST exclude the journal mailbox and any sending/relay mailbox, or you can create self-BCC loops.
- Assume the same logical email can arrive multiple times; dedupe is normal behavior.
- Treat Gmail `message.id` as a mailbox-specific occurrence, never as canonical identity.
