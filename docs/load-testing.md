# Ticket List Load Validation

This repository includes a repeatable smoke load check for the ticket inbox list API.

## Prerequisites
- API running locally (`uv run -- uvicorn app.main:app --reload`)
- `ALLOW_DEV_LOGIN=true`
- Seeded data in the target org (or ingest running)

## Command

```bash
cd apps/api
uv run -- python scripts/validate_ticket_list_scale.py
```

## Optional Environment Variables
- `API_BASE_URL` (default: `http://localhost:8000`)
- `LOAD_TEST_EMAIL` (default: `load-test-admin@example.com`)
- `LOAD_TEST_ORG` (default: `Load Test Org`)
- `LOAD_TEST_ITERATIONS` (default: `50`)

## Output
The script prints:
- request count
- p50 latency
- p95 latency
- max latency

Use this as a regression guard when changing ticket list queries, indexes, or pagination logic.
