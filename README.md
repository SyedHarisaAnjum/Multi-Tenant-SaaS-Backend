# TeamFlow SaaS

Multi-tenant project and task management API: organizations → workspaces → projects → tasks.

**Stack:** FastAPI · SQLAlchemy 2 · PostgreSQL 17 · Redis 7 · Alembic · Argon2id · JWT

## Run everything with Docker

Prerequisite: Docker Desktop.

```powershell
Copy-Item .env.example .env        # then set POSTGRES_PASSWORD (in both DATABASE_URLs) and JWT_SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(64))"   # a JWT_SECRET_KEY
docker compose up --build
```

Open **http://localhost:8080**. API docs: http://localhost:8080/docs.

Start-up is gated on readiness: PostgreSQL healthy → a one-off `migrate` container runs `alembic upgrade head` and exits → backend healthy (its `/health` reaches the DB) → nginx frontend. The backend has no published port; nginx serves the React app and proxies `/api` on the same origin. For plain-http local use, `.env` sets `COOKIE_SECURE=false`. Keep it `true` behind HTTPS.

## Develop on the host

```powershell
docker compose up -d db redis                  # PostgreSQL :5433 and Redis :6380 only

py -3.12 -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -e ".\backend[dev]"
cd backend; alembic upgrade head; uvicorn app.main:app --reload     # API on :8000

cd frontend; npm install; npm run dev          # UI on http://localhost:5173 (proxies /api to :8000)
```

Behind your own reverse proxy, run uvicorn with `--proxy-headers --forwarded-allow-ips=<proxy IP>` and have the proxy *overwrite* `X-Forwarded-For`, so per-IP rate limits can't be spoofed.

## Development

Backend commands run from `backend/`:

| Task | Command |
| --- | --- |
| All tests + coverage (fails under 80%; needs Postgres + Redis) | `pytest --cov=app --cov-report=term-missing` |
| Unit tests only (no services needed, under 1 s) | `pytest tests/unit` |
| Real-concurrency race tests | `pytest tests/concurrency -v` |
| Lint / format | `ruff check .` / `ruff format .` |
| Type check | `mypy app` |
| New migration | `alembic revision --autogenerate -m "describe change"` (then **review it**) |
| Apply migrations | `alembic upgrade head` |

Frontend commands run from `frontend/`: `npm run dev`, `npm run typecheck`, `npm run build`.

### Test layout

| Folder | What | Needs |
| --- | --- | --- |
| `tests/unit` | role matrix, status transitions, invitation expiry, update rules, pagination/sort/search, security helpers | nothing |
| `tests/integration` | API + DB: auth, orgs, members, invitations, workspaces, projects, tasks, cache, errors, constraints, migrations (schema matches models; every revision down/up) | Postgres, Redis |
| `tests/security` | tenant isolation, a permission matrix of every role × sensitive action, "rejected **and** data unchanged" checks, rate limits | Postgres, Redis |
| `tests/concurrency` | real parallel requests with thread barriers (slug race, double accept, lost update, assign vs. remove, failed transfer) | Postgres, Redis |

## API (v1)

| Method | Path | Auth |
| --- | --- | --- |
| POST | `/api/v1/auth/register` | – |
| POST | `/api/v1/auth/login` | – → access token in body, refresh token in HttpOnly cookie |
| POST | `/api/v1/auth/refresh` | refresh cookie → rotates it |
| POST | `/api/v1/auth/logout` | refresh cookie → revokes the session |
| GET | `/api/v1/auth/me` | `Authorization: Bearer <access token>` |

All endpoints below need a bearer token. `{org}` = organization id. Non-members get **404**.

| Method | Path | Who |
| --- | --- | --- |
| POST | `/api/v1/organizations` | any user → becomes owner |
| GET | `/api/v1/organizations` | your organizations, with your role |
| GET | `/api/v1/organizations/{org}` | any member |
| PATCH | `/api/v1/organizations/{org}` | owner, admin |
| GET | `/api/v1/organizations/{org}/members` | any member |
| PATCH | `/api/v1/organizations/{org}/members/{user_id}` | owner, admin (only for roles below their own) |
| DELETE | `/api/v1/organizations/{org}/members/{user_id}` | owner, admin; or yourself (leave) |
| POST | `/api/v1/organizations/{org}/transfer-ownership` | owner |
| POST | `/api/v1/organizations/{org}/invitations` | owner, admin → returns the token once |
| GET | `/api/v1/organizations/{org}/invitations` | owner, admin (pending only) |
| DELETE | `/api/v1/organizations/{org}/invitations/{id}` | owner, admin (revoke) |
| POST | `/api/v1/invitations/accept` | the invited email's account |
| GET | `/api/v1/organizations/{org}/summary` | any member (cached) |

### Workspaces, projects, tasks

| Method | Path | Who |
| --- | --- | --- |
| POST | `/api/v1/organizations/{org}/workspaces` | owner, admin |
| GET | `/api/v1/organizations/{org}/workspaces` | any member (paginated, cached) |
| GET / PATCH / DELETE | `/api/v1/organizations/{org}/workspaces/{id}` | read: member; write: owner, admin; delete refused (409) while it has projects |
| POST | `/api/v1/organizations/{org}/projects` | owner, admin, member |
| GET | `/api/v1/organizations/{org}/projects` | any member (paginated, cached) |
| GET | `/api/v1/projects/{id}` | any member of the project's org |
| PATCH | `/api/v1/projects/{id}` | owner, admin, member (requires `version`) |
| DELETE | `/api/v1/projects/{id}` | owner, admin (deletes its tasks) |
| POST | `/api/v1/projects/{id}/tasks` | owner, admin, member |
| GET | `/api/v1/projects/{id}/tasks` | any member |
| GET | `/api/v1/organizations/{org}/tasks` | any member; `assignee_id=` or `assigned_to_me=true` |
| GET | `/api/v1/tasks/{id}` | any member of the task's org |
| PATCH | `/api/v1/tasks/{id}` | owner, admin, member: edit, assign, status, due date (requires `version`) |
| DELETE | `/api/v1/tasks/{id}` | the creator, or owner/admin |

**Lists** take `page` (1 or more), `page_size` (1 to 100), `sort` (e.g. `-priority,due_date`; allowlisted fields only), `q` (case-insensitive search on names and titles) and filters (`status`, `priority`, `assignee_id`, `workspace_id`, `due_before`, `due_after`). They return `{items, page, page_size, total, total_pages}`.

**Task status flow:** `todo -> in_progress -> in_review -> done`, plus `in_progress -> todo`, `in_progress -> done`, `in_review -> in_progress` and `done -> in_progress` (reopen). Other moves return 422 `INVALID_STATUS_TRANSITION`.

**Concurrent edits:** PATCH on projects and tasks must send the `version` you last read. If someone saved in between, you get 409 `VERSION_CONFLICT` instead of silently overwriting their change.

### Errors

Every error has the same shape. Branch on `code`, and quote `request_id` when reporting a problem (it is also in the `X-Request-ID` header and in every log line):

```json
{"error": {"code": "PROJECT_NOT_FOUND", "message": "Project not found.", "request_id": "9f1c..."}}
```

Validation errors add `details: [{field, message, type}]`. Submitted values are never echoed back.

## Docs

- [Architecture](docs/architecture.md)
- [Database schema](docs/database-schema.md)
- [Security](docs/security.md)
