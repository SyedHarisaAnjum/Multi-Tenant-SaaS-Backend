# TeamFlow SaaS

Multi-tenant project and task management API: organizations → workspaces → projects → tasks.

**Stack:** FastAPI · SQLAlchemy 2 · PostgreSQL 17 · Redis 7 · Alembic · Argon2id · JWT

## Quick start (Windows / PowerShell)

Prerequisites: Python 3.10+ (3.12 recommended), Docker Desktop.

```powershell
# 1. Configure secrets (edit .env: set POSTGRES_PASSWORD, matching DATABASE_URLs, JWT_SECRET_KEY)
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(64))"   # paste as JWT_SECRET_KEY

# 2. Start PostgreSQL (host port 5433, also creates teamflow_test) and Redis (port 6380)
docker compose up -d --wait

# 3. Install the backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".\backend[dev]"

# 4. Create the schema and run the API
cd backend
alembic upgrade head
uvicorn app.main:app --reload
```

Behind a reverse proxy, run uvicorn with `--proxy-headers --forwarded-allow-ips=<proxy IP>` so per-IP rate limits see the real client address (and nobody else can spoof it).

- Health: http://127.0.0.1:8000/health
- Interactive docs: http://127.0.0.1:8000/docs

## Development

Run from `backend/`:

| Task | Command |
| --- | --- |
| Tests (rebuilds the test DB from migrations; needs Postgres + Redis running) | `pytest` |
| Only the real-concurrency race tests | `pytest tests/concurrency -v` |
| Lint / format | `ruff check .` / `ruff format .` |
| Type check | `mypy app` |
| New migration | `alembic revision --autogenerate -m "describe change"` (then **review it**) |
| Apply migrations | `alembic upgrade head` |

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
