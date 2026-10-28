# Deployment

Production runs the same images as local development, with `docker-compose.prod.yml` layered on top of `docker-compose.yml`. It adds the following:

- **Caddy** terminates TLS. It obtains and renews the certificate for `$DOMAIN` automatically and redirects HTTP to HTTPS. It is the only container with published ports (80 and 443).
- **Production settings:** `ENVIRONMENT=production`, `LOG_FORMAT=json`, secure cookies, rate limiting forced on, and API docs hidden.
- **Redis password** (`--requirepass`), plus memory limits on every container.

```
internet ──443──▶ Caddy (TLS, HSTS) ──▶ nginx (SPA, /api proxy) ──▶ uvicorn (WEB_CONCURRENCY workers)
                                                                       │            │
                                                                   PostgreSQL     Redis
```

## 1. Server prerequisites

- A Linux host with Docker Engine and the Compose plugin (v2.24 or later).
- A DNS `A`/`AAAA` record for your domain that points at the host.
- Inbound ports 80 and 443 open. Close everything else, including 5432 and 6379; they are not published anyway.

## 2. Configure

```bash
git clone <repo> teamflow && cd teamflow
cp .env.production.example .env.production
chmod 600 .env.production
python3 -c "import secrets; print(secrets.token_hex(32))"   # once per secret
```

Fill in `DOMAIN`, `ACME_EMAIL`, `POSTGRES_PASSWORD`, `REDIS_PASSWORD` and `JWT_SECRET_KEY`. Use at least 64 characters for `JWT_SECRET_KEY`; `token_hex(32)` produces exactly 64.

If the backend sees unsafe settings in production, it **refuses to start**. These are:

- `COOKIE_SECURE=false`;
- a short or placeholder JWT secret;
- rate limiting disabled.

The error names the setting that's wrong and never prints its value.

## 3. Deploy

```bash
alias tf='docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.prod.yml'
tf up -d --build --wait
tf ps                        # every service healthy, migrate "Exited (0)"
curl https://$DOMAIN/health/ready
```

Start-up is gated: the database must be healthy, then migrations must succeed, then the backend must be ready, then nginx starts, then Caddy. If a migration fails, the old backend keeps running and nothing new starts. Check the reason with `tf logs migrate`.

## 4. Upgrades and rollback

```bash
git pull
tf up -d --build --wait      # runs new migrations, then replaces backend and frontend
```

- **Write migrations to be backward compatible** (expand, then contract). For a moment during the upgrade, the old backend runs against the new schema. Add nullable columns or columns with defaults first; drop old columns in a later release.
- **Roll back code:** `git checkout <previous tag> && tf up -d --build --wait`.
- **Roll back schema:** downgrade only when the downgrade loses no data: `tf run --rm migrate alembic downgrade -1`. Otherwise restore a backup (below).
- **Tag images by release** (for example, push `teamflow-backend:<git sha>` to a registry and deploy by tag). Then rolling back doesn't require a rebuild.

## 5. Backups

PostgreSQL holds all state. Redis holds only cache entries and rate-limit counters, so losing it is harmless.

```bash
# Nightly (cron): compressed custom-format dump, kept off the host.
tf exec -T db pg_dump -U teamflow -d teamflow -Fc > backup-$(date +%F).dump

# Restore into an empty database (stop the app first):
tf stop backend frontend proxy
tf exec -T db pg_restore -U teamflow -d teamflow --clean --if-exists < backup-YYYY-MM-DD.dump
tf up -d --wait
```

**Test a restore regularly;** an untested backup isn't a backup. If you'd rather not run this yourself, a managed PostgreSQL service (with point-in-time recovery) is the main upgrade to consider. To use one, point `DATABASE_URL` at it and remove the `db` service.

## 6. Monitoring

| Signal | Where |
| --- | --- |
| Liveness (process up; no dependencies) | `GET /health/live` |
| Readiness (PostgreSQL reachable; Redis status reported) | `GET /health/ready` (503 when the database is down) |
| Request logs | `tf logs backend`: one JSON object per line with `request_id`, method, path, status, duration and client IP |
| Correlating a user's error report | the `request_id` in the error body equals the `X-Request-ID` response header and appears in every log line for that request |

Point an uptime checker at `/health/ready`. Ship container logs (the json-file driver rotates them at 5 × 10 MB per container) to your log platform, and alert on `"level": "ERROR"` and on 5xx counts.

## 7. Routine maintenance

Expired refresh tokens are never read again but are kept, so the table grows. Delete old ones monthly. That stays safe until the planned worker service takes this job over:

```bash
tf exec -T db psql -U teamflow -d teamflow -c \
  "DELETE FROM refresh_tokens WHERE expires_at < now() - interval '30 days';"
```

## 8. Scaling

- **More throughput on one host:** raise `WEB_CONCURRENCY` (about one per CPU core) and the backend memory limit. Each worker keeps its own pool of up to `DB_POOL_SIZE + DB_MAX_OVERFLOW` connections (default 5 + 10). Keep `workers × 15` below PostgreSQL's `max_connections` (default 100), or put PgBouncer in front.
- **Several hosts:** the backend is stateless (tokens, cache and rate limits are all in PostgreSQL or Redis), so you can run replicas behind a load balancer. Run `migrate` once per deploy, not once per replica.

## Pre-launch checklist

- [ ] `.env.production` holds unique random secrets, has mode 600, and is not committed.
- [ ] DNS resolves, and `https://$DOMAIN` shows a valid certificate.
- [ ] `tf ps` shows every service healthy.
- [ ] `/docs` and `/openapi.json` return 404.
- [ ] A backup has been taken **and restored** successfully.
- [ ] Uptime check and error alerts are configured.
- [ ] CI (`.github/workflows/ci.yml`) is green on the deployed commit.
- [ ] Read the open items in [security.md](security.md#known-limitations--todo), in particular email verification.
