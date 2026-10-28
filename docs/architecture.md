# Architecture

## Layers

```
HTTP request
  → api/v1/*            routers: parse/validate (schemas/), call a service, shape the response
  → dependencies/*      cross-cutting injection: DB session, current user (later: tenant context)
  → services/*          business rules and transactions (commit happens here)
  → repositories/*      SQLAlchemy queries only; no business logic
  → db/models/*         ORM models; PostgreSQL enforces integrity
```

- **core/config.py**: all configuration from environment variables / repo-root `.env` (Pydantic Settings). Nothing secret is hard-coded.
- **core/exceptions.py**: `AppError` subclasses map to HTTP status codes and one JSON error shape:
  `{"error": {"code": "...", "message": "..."}}`.
- **Sync SQLAlchemy** with psycopg 3. FastAPI runs sync endpoints in a thread pool. This is simpler than async and fast enough at this stage.

## Multi-tenancy model

Shared database, shared schema, with an `organization_id` column on every tenant-owned row.

- `organization_id` is **denormalized** onto projects and tasks (not only reachable via joins), so every tenant query can filter on it directly and be indexed for it.
- **Composite foreign keys** (`(workspace_id, organization_id) → workspaces(id, organization_id)`, same for tasks → projects) make it impossible at the database level for a child row to point at another tenant's parent.
- Users are global; `memberships` link users to organizations with a role.

### Authorization building blocks (`app/dependencies/`)

| Dependency | Gives the route | Fails with |
| --- | --- | --- |
| `CurrentMembership` | caller's membership in `{organization_id}` (re-read from DB **every request**) | 404 if not a member |
| `require_role(*roles)` / `OrgOwner`, `OrgAdmin`, `OrgContributor` | same, if role allowed | 403 |
| `AccessibleWorkspace` / `AccessibleProject` / `AccessibleTask` | the resource, loaded with `WHERE id = :id AND organization_id = :caller_org` | 404 |

Rules for new routes:

1. Nest tenant resources under `/organizations/{organization_id}/...`.
2. Never `db.get(Model, id)` for tenant data; use `load_tenant_resource` or an `Accessible*` dependency.
3. Combine a role dependency with a resource dependency for writes, e.g. `task: AccessibleTask, _: OrgContributor`.

People-management rules live in `app/core/permissions.py` (`ensure_can_manage`): you can only manage members ranked below you and only grant roles ranked below your own (owner > admin > member > viewer). Ownership moves only via `transfer-ownership`.

## Request pipeline

```
RequestIdMiddleware (X-Request-ID, access log) -> router -> dependencies -> service -> repository
exception handlers: one {"error": {code, message, request_id}} shape for AppError, validation,
framework 404/405, IntegrityError (409), StaleDataError (409) and anything else (500)
```

- `app/core/exceptions.py`: error classes take an optional specific `code` (e.g. `PROJECT_NOT_FOUND`). Unexpected errors are logged with the stack trace and request id. The client only sees `INTERNAL_ERROR`.
- `get_db` rolls back on any exception, so a failure half-way through a multi-step write (e.g. ownership transfer) leaves nothing behind.

## Lists: pagination, filtering, sorting, search

- `dependencies/pagination.py`: `Pagination` (`page >= 1`, `1 <= page_size <= 100`), `SortQuery`, `SearchQuery`.
- `repositories/query_utils.py`:
  - `apply_sort`: allowlist per resource, `-field` for descending, NULLs last, `id` tiebreaker for stable pages.
  - `contains_ci`: ILIKE with `%` and `_` escaped.
  - `paginate`: offset plus total count.
- Repositories always start from `WHERE organization_id = :caller_org` and only then add filters, so counts and pages never include other tenants' rows.
- Offset pagination is fine at this scale. Switch hot lists to keyset (cursor) pagination when deep pages or very large tenants appear.

## Caching (`app/core/cache.py`)

Cached: workspace list, project list and organization summary. These responses are identical for every member, and the route verifies membership *before* reading the cache.

- Key: `org:{org_id}:{namespace}:g{generation}:page:{p}:size:{s}:{hash of other params}`, TTL 60 s.
- Writes commit first, then `INCR` the namespace's generation, which orphans every old page at once. Readers read the generation *before* querying, so a reader racing a writer can only populate a key that nobody will read again.
- Invalidation after commit can be lost if the process dies in between. The TTL bounds that staleness. A transactional outbox is the upgrade path if that's ever not acceptable.
- If Redis is down, every cache call is a miss (logged) and reads go to PostgreSQL. Redis is then skipped for 5 s, so requests don't each wait for a timeout.

## Rate limiting (`app/core/rate_limit.py`)

Fixed-window counters in Redis (atomic Lua `INCR` + `EXPIRE`), applied per dimension:

| Endpoint | Dimensions (limit / window) |
| --- | --- |
| login | IP (30 / 5 min), account email (10 / 15 min) |
| register | IP (10 / h) |
| refresh | IP (60 / min) |
| create invitation | user (30 / h), organization (200 / day) |
| accept invitation | user (10 / 15 min) |

Over the limit, the endpoint returns 429 `RATE_LIMITED` with `Retry-After`. Identifiers are hashed in keys. If Redis is down the limiter fails open (logged); construct it with `fail_open=False` to fail closed. Password recovery doesn't exist yet; when added, it needs IP and account limits like login.

## Concurrency (`tests/concurrency/`)

| Situation | Protection |
| --- | --- |
| Two requests claim the same slug | unique index; `IntegrityError` becomes 409 with the domain code |
| Same invitation accepted twice | `SELECT ... FOR UPDATE` on the invitation |
| Two people edit the same task or project | `version` column (`version_id_col`): `UPDATE ... WHERE version = :read` |
| A task is assigned while the assignee is being removed | assignment holds `FOR SHARE` on the membership; removal's `FOR UPDATE` waits, then unassigns |
| Ownership transfer fails midway | single transaction + rollback; DB allows only one owner |
| Workspace deleted while a project is added | row lock on the workspace + `ON DELETE RESTRICT` FK |

## Frontend (`frontend/`)

React 19 + TypeScript (strict) + Vite, React Router for routing and TanStack Query for server state. There is no client-side copy of the data model: each page reads through query keys (`["projects", orgId, filters]`, `["task", id]`, ...), and mutations invalidate the keys they affect.

- **Routing:** the selected organization lives in the URL (`/orgs/:orgId/...`), so reloads and shared links keep context. List filters live in query params too.
- **Auth:** the access token is kept in memory only. On load, and on any 401, the client calls `/auth/refresh` with the HttpOnly cookie. Refreshes are serialized within a tab (shared promise) and across tabs (Web Locks API), because rotating refresh tokens plus reuse detection would otherwise log users out when two tabs refresh at once. If a refresh fails, the session is over: cached data is cleared and the user is sent to `/login?next=...` with a "session expired" notice.
- **Authorization stays in the backend.** Role checks in the UI (`can(role)`) only decide which controls to show. Every action is enforced server-side regardless.
- **Optimistic locking in the UI:** edit forms send only changed fields plus `version`. A `VERSION_CONFLICT` offers "Load latest version" instead of overwriting.
- Every data view has loading, empty and error states. Errors show the server's message and request id.

## Containers (`docker-compose*.yml`)

| Service | Image | Readiness |
| --- | --- | --- |
| db | postgres:17-alpine, named volume `pgdata` | `pg_isready` |
| redis | redis:7.4-alpine (no persistence, 128 MB cap) | `redis-cli ping` |
| migrate | backend image, `alembic upgrade head`, exits | backend waits for `service_completed_successfully` |
| backend | python:3.12-slim, deps pinned by `requirements.lock`, non-root, read-only root FS, no capabilities, no published port | `/health/ready` (DB round-trip); `/health/live` has no dependencies |
| frontend | nginx serving the built SPA, proxying `/api`, `/health*`, `/docs` | `/healthz` |
| proxy (prod only) | Caddy: TLS with automatic certificates, HSTS, HTTP→HTTPS | — |

Images contain no secrets. Everything comes from environment variables at runtime (`JWT_SECRET_KEY` is required, and compose refuses to start without it). nginx overwrites `X-Forwarded-For` with the real peer address, and only then does the backend trust it (`FORWARDED_ALLOW_IPS=*` is safe solely because nginx is the only route to the backend). The SPA is served with a strict Content-Security-Policy, and fingerprinted assets are cached as immutable; API responses are `Cache-Control: no-store`.

The three compose files have separate roles:

- `docker-compose.yml` is the production-safe base. It publishes nothing except through a proxy, and it sets read-only containers, dropped capabilities, `no-new-privileges` and rotated logs.
- `docker-compose.override.yml` is for local development and is loaded automatically. It publishes Postgres on :5433, Redis on :6380 and the UI on :8080, and it creates the test database.
- `docker-compose.prod.yml` adds Caddy and production settings. Because nginx then sits behind Caddy, it mounts `docker/nginx/trust-proxy.conf`, which takes the client address from Caddy's `X-Forwarded-For`. Without it, every user would share Caddy's address in the per-IP rate limits.

The full chain was verified end to end: the backend logs the real client IP, and a spoofed `X-Forwarded-For` is ignored.

**Runtime settings.** The DB pool is bounded (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`) and connections are recycled. Every connection gets a `statement_timeout` (15 s by default), so a runaway query can't hold locks forever. uvicorn runs `WEB_CONCURRENCY` workers and drains in-flight requests for up to 20 s on SIGTERM.

**CI** (`.github/workflows/ci.yml`) runs these jobs:

- Backend: ruff, ruff format, mypy, the full test suite with coverage, and `alembic check`, on Python 3.12 with the locked dependency versions, against real Postgres and Redis services.
- Frontend: typecheck, build and `npm audit`.
- Both Docker images are built, and the production compose file is validated.

Dependabot keeps npm packages, base images and Actions current.

## Testing

- `tests/conftest.py` downgrades and upgrades the test DB through Alembic at session start, so every run proves the schema builds from migrations alone.
- Each test runs inside a transaction that is rolled back; app commits become savepoints.
- `tests/unit` (no DB), `tests/integration` (API + DB), `tests/security` (attack-oriented cases).
- The `tenants` fixture (conftest) builds Acme with one user per role, plus Globex owned by an outsider.
- `tests/security/test_tenant_isolation.py` mounts probe routes that use the real `Accessible*` dependencies, so cross-tenant project and task access is tested before those APIs exist.
- Tests swap in cheap Argon2 parameters; production parameters are unchanged.
- Tests use Redis DB 15 (`TEST_REDIS_URL`), flushed before each test. Rate limiting is off by default and re-enabled by the `limited` fixture in `tests/security/test_rate_limits.py`.
- `tests/concurrency/` runs real parallel requests on separate connections with real commits. Thread barriers force the race, and the tables are truncated afterwards.
