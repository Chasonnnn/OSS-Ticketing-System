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

## Rate Limiting

### Goal
Control burst abuse and accidental high-frequency traffic.

### Configuration
- `RATE_LIMIT_REQUESTS_PER_MINUTE` controls per-IP request limit (default: `120`).
- Set to `0` to disable.

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
