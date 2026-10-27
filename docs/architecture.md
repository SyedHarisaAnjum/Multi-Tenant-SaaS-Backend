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

Next step: a `get_current_membership(org_id)` dependency that every tenant-scoped route uses, so the tenant check can't be forgotten.

## Testing

- `tests/conftest.py` downgrades and upgrades the test DB through Alembic at session start, so every run proves the schema builds from migrations alone.
- Each test runs inside a transaction that is rolled back; app commits become savepoints.
- `tests/unit` (no DB), `tests/integration` (API + DB), `tests/security` (attack-oriented cases).
