# Workmap (Week-by-Week)

- Week 1 Aim: Repo + infra foundation. Outcome: monorepo scaffolding (`apps/api`, `apps/web`), Docker Compose for Postgres + MinIO, CI pipeline with “no warnings” policy, baseline `AGENTS.md`, basic health endpoints.
- Week 2 Aim: Identity + tenancy. Outcome: org/user/membership + RBAC model, cookie auth, CSRF on mutations, “org scoping required” test helpers, audit/event logging framework.
- Week 3 Aim: Mailbox connection (Gmail OAuth). Outcome: connect one journal Gmail mailbox per org, token encryption-at-rest, permission/scopes verification, mailbox status UI (connected / degraded / paused).
- Week 4 Aim: Sync engine (polling, replayable). Outcome: full backfill + incremental sync loop via Gmail `history.list` with “history invalid => full resync” recovery, `message_occurrence` upsert model, storm circuit breaker, runbooks/metrics for sync lag.
- Week 5 Aim: Raw storage + MIME parsing. Outcome: store raw RFC822 EML and attachment blobs in object storage, deterministic parsing + HTML sanitization, attachment metadata + CID handling, parser versioning policy.
- Week 6 Aim: Canonical message model + dedupe. Outcome: canonical `messages` + mailbox-specific `message_occurrences`, versioned fingerprint/signature strategy, collision groups + admin visibility, “Gmail IDs are occurrences” invariant enforced.
- Week 7 Aim: Ticket stitching (provider-agnostic). Outcome: outbound markers (`X-OSS-Ticket-ID`, `X-OSS-Message-ID`, Reply-To token), stitching by markers then `In-Reply-To/References` graph, deterministic ticket creation, stitch reason/confidence persisted and visible.
- Week 8 Aim: Routing with original-recipient evidence. Outcome: Workspace header injection supported and strongly recommended, To/Cc fallback with confidence downgrade, allowlist patterns + default spam/close/drop policy, rule simulator in admin.
- Week 9 Aim: Core API (tickets/messages). Outcome: production-grade list/search APIs with cursor pagination, ticket detail API returning full thread + events + notes, strict validation/errors, load-tested queries with indexes.
- Week 10 Aim: Web UI foundation. Outcome: Next.js App Router shell, authenticated app layout, inbox list with filters/saved views, loading/error states everywhere, visual polish standards applied (no placeholders).
- Week 11 Aim: Ticket detail UI + thread viewer. Outcome: safe HTML rendering (remote loads blocked by default), attachment download via signed URLs, internal notes with mentions, event timeline, assignment/status controls.
- Week 12 Aim: Reply composer + outbound send. Outcome: send-as identities allowlisted and verified, ingest-on-send is authoritative, mirrored outbound copies dedupe into occurrences only, full failure handling (draft retry/rollback).
- Week 13 Aim: Admin & ops tooling. Outcome: mailbox sync dashboard (lag, historyId, watch health), DLQ viewer/replay, dedupe collision UI, routing evidence UI, pause/unpause ingestion controls.
- Week 14 Aim: Observability + security hardening. Outcome: structured logs with correlation IDs, OTel optional, Prom metrics optional, rate limiting and abuse controls, PII-safe logging enforced, CSP and secure headers shipped.
- Week 15 Aim: Performance + scale. Outcome: index tuning, FTS tuning, job batching/concurrency controls, large org backfills validated, storage retention policies, attachment scanning optional hook.
- Week 16 Aim: Release-grade packaging + docs. Outcome: dockerized deploy, self-host guide, Workspace configuration guide (loop-prevention checklist), production checklist, seed data + smoke tests, Apache-2.0 compliance (`LICENSE`).

