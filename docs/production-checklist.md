# Production Checklist

## Security
- `ALLOW_DEV_LOGIN=false`
- `COOKIE_SECURE=true`
- Strong `ENCRYPTION_KEY_BASE64` configured (32-byte decoded key)
- CORS narrowed to production web origin(s)
- CSP reviewed (`CONTENT_SECURITY_POLICY`)

## Data + Storage
- Postgres backups scheduled and restore-tested
- MinIO/S3 bucket lifecycle + retention policy defined
- Blob storage access keys rotated and scoped

## Gmail + Routing
- Gmail OAuth client configured with correct callback URL
- Journal mailbox connected and connectivity checked
- Recipient allowlist configured for supported inbox addresses
- Routing rules validated with `/tickets/routing/simulate`

## Runtime Operations
- API, worker, and web start successfully
- Migrations applied (`alembic upgrade head`)
- Mailbox sync dashboard healthy (`/ops`)
- DLQ monitored and replay flow tested (`/ops/jobs/dlq`)

## Observability
- Request IDs present in responses (`x-request-id`)
- Structured request logs collected
- Rate limits tuned (`RATE_LIMIT_REQUESTS_PER_MINUTE`)
- Alerting configured for failed job growth and long sync lag

## Validation
- Run API smoke script:
  - `cd apps/api && uv run -- python scripts/smoke_api.py`
- Run load regression check:
  - `cd apps/api && uv run -- python scripts/validate_ticket_list_scale.py`

