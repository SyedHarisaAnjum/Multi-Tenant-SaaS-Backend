# TeamFlow SaaS

Multi-tenant project and task management API: organizations → workspaces → projects → tasks.

**Stack:** FastAPI · SQLAlchemy 2 · PostgreSQL 17 · Alembic · Argon2id · JWT

## Quick start (Windows / PowerShell)

Prerequisites: Python 3.10+ (3.12 recommended), Docker Desktop.

```powershell
# 1. Configure secrets (edit .env: set POSTGRES_PASSWORD, matching DATABASE_URLs, JWT_SECRET_KEY)
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(64))"   # paste as JWT_SECRET_KEY

# 2. Start PostgreSQL (host port 5433; also creates the teamflow_test database)
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

- Health: http://127.0.0.1:8000/health
- Interactive docs: http://127.0.0.1:8000/docs

## Development

Run from `backend/`:

| Task | Command |
| --- | --- |
| Tests (rebuilds the test DB from migrations) | `pytest` |
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

## Docs

- [Architecture](docs/architecture.md)
- [Database schema](docs/database-schema.md)
- [Security](docs/security.md)
