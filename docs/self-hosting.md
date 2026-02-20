# Self-Hosting Guide

This guide covers a single-node deployment for the OSS Ticketing System.

## 1. Prerequisites
- Docker + Docker Compose
- Python 3.12+
- Node 20+
- Google Cloud OAuth client (for Gmail API)

## 2. Environment
Create `.env` at repo root from `.env.example`, then set at minimum:
- `APP_ENV=prod`
- `DATABASE_URL`
- `ENCRYPTION_KEY_BASE64` (base64 that decodes to 32 bytes)
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `API_BASE_URL`
- `FRONTEND_URL`
- `COOKIE_SECURE=true`

## 3. Start Stateful Services
```bash
docker compose up -d postgres minio
```

## 4. Backend Install + Migrate
```bash
cd apps/api
uv sync --extra dev --extra test
uv run -m alembic upgrade head
```

## 5. Run Services
Use separate processes:

API:
```bash
cd apps/api
uv run -- uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Worker:
```bash
cd apps/api
uv run -m app.worker
```

Web:
```bash
cd apps/web
pnpm install --frozen-lockfile
pnpm build
pnpm start
```

## 6. Smoke Check
With API running and `ALLOW_DEV_LOGIN=true` in environment:
```bash
cd apps/api
uv run -- python scripts/smoke_api.py
```

## 7. Recommended Hardening
- Put API/web behind TLS reverse proxy.
- Restrict CORS to known web origins.
- Rotate OAuth secrets and encryption key via secret manager.
- Configure backups for Postgres and object storage.
- Keep `ALLOW_DEV_LOGIN=false` in production.

