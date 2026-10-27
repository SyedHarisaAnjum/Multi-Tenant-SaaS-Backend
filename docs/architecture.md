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

## Testing

- `tests/conftest.py` downgrades and upgrades the test DB through Alembic at session start, so every run proves the schema builds from migrations alone.
- Each test runs inside a transaction that is rolled back; app commits become savepoints.
- `tests/unit` (no DB), `tests/integration` (API + DB), `tests/security` (attack-oriented cases).
- The `tenants` fixture (conftest) builds Acme with one user per role, plus Globex owned by an outsider.
- `tests/security/test_tenant_isolation.py` mounts probe routes that use the real `Accessible*` dependencies, so cross-tenant project and task access is tested before those APIs exist.
- Tests swap in cheap Argon2 parameters; production parameters are unchanged.
