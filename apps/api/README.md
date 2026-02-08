# OSS Ticketing API

FastAPI + Postgres backend for the OSS Ticketing System.

## Local dev auth (dev-only)
1. Set `ALLOW_DEV_LOGIN=true` in repo-root `.env`.
2. Fetch a CSRF token:
   - `GET /auth/csrf` (sets `oss_csrf` cookie, returns `{ csrf_token }`)
3. Log in:
   - `POST /auth/dev/login` with header `x-csrf-token: <csrf_token>`
4. Use the returned `csrf_token` (and cookie) for future mutations.
