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

## Docs

- [Architecture](docs/architecture.md)
- [Database schema](docs/database-schema.md)
- [Security](docs/security.md)
