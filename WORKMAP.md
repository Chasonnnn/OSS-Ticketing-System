# Workmap (Week-by-Week)

## Week 1
- Status: Completed (2026-02-08)
- Aim: Repo + infra foundation.
- Outcome: monorepo scaffolding (`apps/api`, `apps/web`), Docker Compose for Postgres + MinIO, baseline docs (`AGENTS.md`, `WORKMAP.md`), initial Postgres schema (Alembic), API health/ready endpoints, CI running API/web checks.
- Completion rule: `docker compose up -d postgres minio` works (port configurable), `cd apps/api && uv run -m alembic upgrade head` succeeds on a fresh DB, `cd apps/api && uv run -m pytest -v` passes, `cd apps/web && pnpm lint && pnpm tsc --noEmit && pnpm test --run` passes, CI is green, and lockfiles are committed.

## Week 2
- Status: Completed (2026-02-08)
- Aim: Identity + tenancy.
- Outcome: org/user/membership + RBAC model, DB-backed sessions (opaque cookie token, hashed in DB), org context derived from session + membership (no org header/URL in v1), CSRF on mutations (double-submit cookie), centralized auth/org/role dependencies, audit/event logging skeleton, `updated_at` triggers, Postgres-backed tests that prove scoping.
- Completion rule: every org-owned endpoint resolves `OrgContext` via one dependency (`require_org()`), every org query path is scoped by construction (tests prove cross-org data is invisible), every mutation endpoint rejects missing CSRF, and role checks are centralized dependencies with test coverage; CI starts Postgres, runs `alembic upgrade head`, and runs API tests against Postgres.

## Week 3
- Status: Completed (2026-02-08)
- Aim: Mailbox connection (Gmail OAuth).
- Outcome: connect one journal Gmail mailbox per org, token encryption-at-rest (AES-GCM), scope verification, one-time OAuth state to prevent replay, mailbox health state (connected/degraded/paused/disabled), and an admin UI to start OAuth + check connectivity.
- Completion rule: an org admin can connect a Gmail account, the app persists encrypted refresh tokens, and a mailbox connectivity check endpoint/UI shows scopes + profile email and fails safely with actionable errors.

## Week 4
- Status: Completed (2026-02-16)
- Aim: Sync engine (polling, replayable).
- Outcome: full backfill + incremental sync loop, `message_occurrence` upserts, storm circuit breaker, sync-lag metrics/runbook.
- Completion rule: sync is at-least-once and idempotent (re-running does not duplicate canonical messages), and “history invalid => full resync” is a tested and documented recovery path.

## Week 5
- Status: Completed (2026-02-16)
- Aim: Raw storage + MIME parsing.
- Outcome: raw RFC822 EML and attachment blobs stored in object storage, deterministic parsing + HTML sanitization, CID handling, parser versioning.
- Completion rule: given a test EML corpus, parsing produces stable normalized outputs, sanitized HTML blocks remote loads by default, and attachments round-trip via signed download URLs.

## Week 6
- Status: Partial (2026-02-16)
- Aim: Canonical message model + dedupe.
- Outcome: canonical `messages` + mailbox-specific `message_occurrences`, versioned fingerprint/signature strategy, collision groups + admin visibility.
- Completion rule: duplication scenarios (same mail in N mailboxes, duplicate deliveries, missing/rewritten Message-ID) produce N occurrences but exactly 1 canonical message, with collision groups recorded when ambiguity exists.

## Week 7
- Status: Partial (2026-02-16)
- Aim: Ticket stitching (provider-agnostic).
- Outcome: outbound markers (`X-OSS-Ticket-ID`, `X-OSS-Message-ID`, Reply-To token), stitching by markers then `In-Reply-To/References`, stitch reason/confidence persisted.
- Completion rule: replies reliably stitch even when Gmail thread IDs differ, and stitch_reason/stitch_confidence are visible in admin/debug views with reproducible explanations.

## Week 8
- Status: Partial (2026-02-16)
- Aim: Routing with original-recipient evidence.
- Outcome: Workspace header injection supported/recommended, To/Cc fallback with confidence downgrade, recipient allowlist, rule simulator.
- Completion rule: routing uses persisted original-recipient evidence (with source+confidence), allowlist prevents catch-all spam floods, and a simulator can explain which rule fired and why.

## Week 9
- Status: Partial (2026-02-16)
- Aim: Core API (tickets/messages).
- Outcome: list/search APIs with cursor pagination, ticket detail API (thread + events + notes), strict validation and error handling.
- Completion rule: all list endpoints are paginated and indexed, common filters are covered by query-plan checks, and API contract tests lock the response shapes.

## Week 10
- Status: Partial (2026-02-16)
- Aim: Web UI foundation.
- Outcome: Next.js App Router shell, authenticated app layout, inbox list with filters/saved views, polished loading/error states.
- Completion rule: every page has explicit loading/error UI, there are no placeholder components/text, and the UI is consistently styled with production-grade interaction states.

## Week 11
- Status: Completed (2026-02-16)
- Aim: Ticket detail UI + thread viewer.
- Outcome: safe HTML rendering, attachments via signed URLs, internal notes, event timeline, status/assignment controls.
- Completion rule: message rendering is safe-by-default (no remote loads), attachment downloads are authorized and org-scoped, and thread/timeline rendering remains performant on large tickets.

## Week 12
- Status: Partial (2026-02-16)
- Aim: Reply composer + outbound send.
- Outcome: allowlisted send-as identities, ingest-on-send canonical persistence, mirrored outbound dedupes into occurrences only, robust failure handling.
- Completion rule: a sent reply always creates/links exactly one canonical message, “journal mirror” creates only an occurrence, and send failures are recoverable without duplicate sends.

## Week 13
- Status: Partial (2026-02-16)
- Aim: Admin & ops tooling.
- Outcome: mailbox sync dashboard, DLQ viewer/replay, dedupe collision UI, routing evidence UI, pause/unpause controls.
- Completion rule: an admin can diagnose lag/loops, replay DLQ items safely, and explain dedupe and routing decisions for any ticket/message.

## Week 14
- Status: Partial (2026-02-16)
- Aim: Observability + security hardening.
- Outcome: structured logs with correlation IDs, optional OTel/Prom, rate limiting/abuse controls, CSP/secure headers, PII-safe logging.
- Completion rule: logs are PII-safe by default, key metrics exist (sync lag, job throughput, error rates), and security headers/CSP ship with documented overrides.

## Week 15
- Status: Partial (2026-02-16)
- Aim: Performance + scale.
- Outcome: index/FTS tuning, batching/concurrency controls, large-org backfills validated, retention policies, optional attachment scanning hook.
- Completion rule: load tests demonstrate predictable performance at target scale, DB indexes match query patterns, and ingestion can be throttled without correctness loss.

## Week 16
- Status: Partial (2026-02-16)
- Aim: Release-grade packaging + docs.
- Outcome: dockerized deploy, self-host guide, Workspace setup guide (loop-prevention checklist), production checklist, seed data + smoke tests, Apache-2.0 compliance.
- Completion rule: a new operator can deploy from docs, configure Workspace journaling safely, run smoke tests, and reach a functional inbox with clear operational runbooks.
