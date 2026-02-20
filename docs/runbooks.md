# OSS Ticketing Runbooks

## DLQ Replay

### Goal
Replay failed worker jobs safely for a single organization.

### Steps
1. Log in as an `admin`.
2. List failed jobs:
   - `GET /ops/jobs/dlq`
3. Inspect `type`, `attempts`, and `last_error`.
4. Replay one job:
   - `POST /ops/jobs/{job_id}/replay`
5. Confirm the job moves back to `queued` and follow worker logs for completion.

### Notes
- Replay only resets queue state (`status`, `run_at`, locks, `last_error`); payload remains unchanged.
- Repeated failures should be investigated before repeated replays.

## Mailbox Sync Pause/Resume

### Goal
Pause noisy mailbox ingestion and safely resume after remediation.

### Endpoints
- Pause:
  - `POST /mailboxes/{mailbox_id}/sync/pause?minutes=30`
- Resume:
  - `POST /mailboxes/{mailbox_id}/sync/resume`
- Status:
  - `GET /mailboxes/{mailbox_id}/sync/status`

### Operator Steps
1. Pause mailbox ingestion when loops/failure storms are observed.
2. Resolve root cause (routing, credentials, mailbox config).
3. Resume ingestion to clear pause and enqueue history sync.
4. Confirm `sync_lag_seconds` and job queues trend back to normal.

## Correlation IDs

### Goal
Trace a request across API logs and client reports.

### Behavior
- The API returns `x-request-id` for every response.
- If a client sends `x-request-id`, the same value is echoed back.
- Request logs include `request_id`, `method`, `path`, `status_code`, `duration_ms`, and `rate_limited`.

### Usage
1. Capture the `x-request-id` from a failing API response.
2. Search backend logs for the same `request_id`.
3. Use `path` and `status_code` entries to identify where the failure occurred.

## Ops Dashboard APIs

### Goal
Provide an organization-scoped operational snapshot.

### Endpoints
- `GET /ops/mailboxes/sync`
- `GET /ops/messages/collisions?limit=50`
- `GET /ops/metrics/overview`

### Usage
1. Start at `/ops/metrics/overview` for queue and mailbox-level health.
2. Inspect `/ops/mailboxes/sync` for lag, pauses, and per-mailbox failures.
3. Use `/ops/messages/collisions` when dedupe ambiguity needs investigation.

## Rate Limiting

### Goal
Control burst abuse and accidental high-frequency traffic.

### Configuration
- `RATE_LIMIT_REQUESTS_PER_MINUTE` controls per-IP request limit (default: `120`).
- Set to `0` to disable.
- `ENABLE_PROMETHEUS_METRICS` controls `/metrics` exposure (default: `true`).

### Operator Response
1. If legitimate clients are throttled, increase `RATE_LIMIT_REQUESTS_PER_MINUTE`.
2. For attack traffic, keep lower limits and add edge/network-level filtering.
3. Correlate `429` responses with request logs (`rate_limited=true`).

## Security Headers

### Shipped Headers
- `Content-Security-Policy`
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: same-origin`

### Override
- Set `CONTENT_SECURITY_POLICY` in environment to customize CSP for your deployment.

## Metrics Export

### Goal
Expose Prometheus-scrapable API metrics for request throughput and latency.

### Endpoint
- `GET /metrics`

### Included Metrics
- `oss_http_requests_total`
- `oss_http_request_duration_seconds`
- `oss_http_rate_limited_total`
