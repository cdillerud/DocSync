# GPI Hub Test Credentials

## Admin Account (seeded from env on startup)

**Environment variables that drive the seed:**
- `ADMIN_EMAIL` — admin account email
- `ADMIN_PASSWORD` — plain-text admin password (hashed to bcrypt at seed time, not stored in .env after rotation)

**Preview/dev environment (v2.5.24+):**
- Email: `hub-admin@gamerpackaging.com`
- Password: `ChangeMeOnFirstDeploy-K8p2q`
- Role: `admin`

**Production VM:** rotate both values via docker-compose env. The startup validator will refuse to boot with any known-insecure default (`admin`, `admin123`, `changeme`, `admin@example.com`, `gpi-hub-secret-key`, etc.).

## Auth flow for tests

```bash
# 1. Login -> JWT
TOKEN=$(curl -s -X POST http://localhost:8001/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"hub-admin@gamerpackaging.com","password":"ChangeMeOnFirstDeploy-K8p2q"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

# 2. Use on mutating routes
curl -X POST http://localhost:8001/api/admin/backfill-ap-mailbox?dry_run=true \
  -H "Authorization: Bearer $TOKEN"
```

## JWT_SECRET

- Preview/dev: 96-char hex string in `/app/backend/.env` (rotate via `python -c "import secrets; print(secrets.token_hex(48))"`)
- Production VM: set in `docker-compose.yml` environment, NEVER commit to git

## Do NOT use

The pre-v2.5.24 `admin/admin` plaintext credentials are removed and the startup validator will refuse to boot with any of them.
