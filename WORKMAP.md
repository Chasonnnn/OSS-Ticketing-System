# Workmap (Week-by-Week)

- Week 1
  Aim: Repo + infra foundation.
  Outcome: monorepo scaffolding (`apps/api`, `apps/web`), Docker Compose for Postgres + MinIO, CI pipeline with “no warnings” policy, baseline `AGENTS.md`, basic health endpoints.
  Completion rule: CI is green; `docker compose up -d postgres minio` becomes healthy; API `/healthz` and `/readyz` return 200; `cd apps/api && uv run -m pytest -v` passes; `cd apps/web && pnpm tsc --noEmit` and `pnpm test --run` pass.

- Week 2
  Aim: Identity + tenancy.
  Outcome: org/user/membership + RBAC model, cookie auth, CSRF on mutations, “org scoping required” test helpers, audit/event logging framework.
  Completion rule: Auth + CSRF enforced on all mutating endpoints; every query is org-scoped and has tests proving cross-org access is impossible; audit events are emitted for workflow mutations; all tests pass and no lint/typecheck warnings exist.

- Week 3
  Aim: Mailbox connection (Gmail OAuth).
  Outcome: connect one journal Gmail mailbox per org, token encryption-at-rest, permission/scopes verification, mailbox status UI (connected / degraded / paused).
  Completion rule: Admin can connect a Gmail mailbox and see verified status; refresh tokens are stored encrypted (no plaintext token in DB/logs); scope validation blocks mis-scoped credentials; disconnect/reconnect is idempotent; failure modes are visible in UI and logs without PII.

- Week 4
  Aim: Sync engine (polling, replayable).
  Outcome: full backfill + incremental sync loop via Gmail `history.list` with “history invalid => full resync” recovery, `message_occurrence` upsert model, storm circuit breaker, runbooks/metrics for sync lag.
  Completion rule: Re-running backfill/incremental creates zero duplicates (verified by tests); invalid `historyId` triggers a full resync path (tested); storm circuit breaker auto-pauses ingestion and is recoverable via admin action; sync lag is measured and exposed.

- Week 5
  Aim: Raw storage + MIME parsing.
  Outcome: store raw RFC822 EML and attachment blobs in object storage, deterministic parsing + HTML sanitization, attachment metadata + CID handling, parser versioning policy.
  Completion rule: Every ingested message stores raw EML and attachment blobs; HTML is sanitized and remote loads are blocked by default; CID/inline metadata is preserved; parser output is deterministic on fixtures; parser versioning is recorded and re-parse is safe.

- Week 6
  Aim: Canonical message model + dedupe.
  Outcome: canonical `messages` + mailbox-specific `message_occurrences`, versioned fingerprint/signature strategy, collision groups + admin visibility, “Gmail IDs are occurrences” invariant enforced.
  Completion rule: Same logical email arriving multiple times (or via multiple mailboxes) yields many occurrences and exactly one canonical message; missing/duplicated/rewritten `Message-ID` does not break ingestion; collision cases are recorded and visible in admin tooling.

- Week 7
  Aim: Ticket stitching (provider-agnostic).
  Outcome: outbound markers (`X-OSS-Ticket-ID`, `X-OSS-Message-ID`, Reply-To token), stitching by markers then `In-Reply-To/References` graph, deterministic ticket creation, stitch reason/confidence persisted and visible.
  Completion rule: Replies stitch correctly via (1) explicit ticket markers, then (2) threading headers; stitch reason/confidence is stored for every link; idempotent retries do not create extra tickets/messages; tests cover all stitch paths.

- Week 8
  Aim: Routing with original-recipient evidence.
  Outcome: Workspace header injection supported and strongly recommended, To/Cc fallback with confidence downgrade, allowlist patterns + default spam/close/drop policy, rule simulator in admin.
  Completion rule: Routing persists original-recipient value + source + confidence; allowlist prevents catch-all spam by default; rule engine is deterministic and priority-ordered; admin simulator produces identical results to production routing; tests cover header-injection and To/Cc fallback.

- Week 9
  Aim: Core API (tickets/messages).
  Outcome: production-grade list/search APIs with cursor pagination, ticket detail API returning full thread + events + notes, strict validation/errors, load-tested queries with indexes.
  Completion rule: Ticket list/search/detail endpoints are fully typed and validated; cursor pagination is stable and tested; query plans are index-backed for primary inbox queries; API errors are explicit and consistent; no N+1 query patterns in hot paths.

- Week 10
  Aim: Web UI foundation.
  Outcome: Next.js App Router shell, authenticated app layout, inbox list with filters/saved views, loading/error states everywhere, visual polish standards applied (no placeholders).
  Completion rule: App has a polished authenticated shell; inbox supports filtering and saved views; all routes have real loading/error states; no console errors; lint/typecheck/tests pass.

- Week 11
  Aim: Ticket detail UI + thread viewer.
  Outcome: safe HTML rendering (remote loads blocked by default), attachment download via signed URLs, internal notes with mentions, event timeline, assignment/status controls.
  Completion rule: Ticket detail renders large threads reliably; sanitized HTML cannot execute scripts or load remote resources by default; attachments download through server-authorized URLs; notes/events/assignment/status mutations work with full error handling and tests.

- Week 12
  Aim: Reply composer + outbound send.
  Outcome: send-as identities allowlisted and verified, ingest-on-send is authoritative, mirrored outbound copies dedupe into occurrences only, full failure handling (draft retry/rollback).
  Completion rule: Only verified send identities are usable; sending persists canonical outbound message before send; mirrored outbound ingestion does not create duplicates; compose/send UX handles all failures cleanly; tests cover send + dedupe + stitch round trips.

- Week 13
  Aim: Admin & ops tooling.
  Outcome: mailbox sync dashboard (lag, historyId, watch health), DLQ viewer/replay, dedupe collision UI, routing evidence UI, pause/unpause ingestion controls.
  Completion rule: Admin can observe sync lag/health, inspect occurrences, replay failures safely, manage routing rules/allowlists, and pause/unpause ingestion; all actions are audited; no PII is logged.

- Week 14
  Aim: Observability + security hardening.
  Outcome: structured logs with correlation IDs, OTel optional, Prom metrics optional, rate limiting and abuse controls, PII-safe logging enforced, CSP and secure headers shipped.
  Completion rule: Logs are structured and correlated end-to-end; PII masking is enforced by tests; optional instrumentation can be toggled; API rate limits are in place and tested; frontend ships CSP/security headers appropriate for email HTML rendering.

- Week 15
  Aim: Performance + scale.
  Outcome: index tuning, FTS tuning, job batching/concurrency controls, large org backfills validated, storage retention policies, attachment scanning optional hook.
  Completion rule: Inbox/search queries meet defined latency targets on representative datasets; worker concurrency/backpressure prevents storms; retention policies are implemented and tested; attachment scanning is available as an optional integration point.

- Week 16
  Aim: Release-grade packaging + docs.
  Outcome: dockerized deploy, self-host guide, Workspace configuration guide (loop-prevention checklist), production checklist, seed data + smoke tests, Apache-2.0 compliance (`LICENSE`).
  Completion rule: A self-host deploy can run from docs to a working system; Workspace config guide prevents loops by default; smoke tests validate critical flows (ingest, stitch, route, view, reply); release checklist is complete and CI remains warning-free.
